"""Tests pour orchestration/runner.py — persistance Mongo d'un cycle en échec (#452).

Contexte : `_update_cost_in_mongo`, `_update_billing_mode_in_mongo` et `_update_perf_in_mongo`
faisaient un `update_one` sans `upsert`. Sur un cycle qui plante avant la Phase 7, le document
n'existe pas encore : ces trois écritures ne matchent rien et sont perdues sans exception (Mongo
considère qu'un update qui ne touche aucun document est un succès). Seul `_handle_error` créait
le document ensuite, avec un nom de champ de durée différent (`duration_seconds` au lieu de
`duration_s`).

_FakeCyclesCollection reproduit cette sémantique réelle : `update_one` sans upsert sur un `_id`
absent réussit et renvoie `matched_count == 0`, sans lever d'exception — un mock qui accepterait
tout sans modéliser ce cas ne prouverait rien face à ce bug précis."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from orchestration import (
    runner,
)

_SCRATCH_DIR = os.path.join(PROJECT_DIR, "tests", "_scratch_runner_cycle_mongo")


class _FakeUpdateResult:
    def __init__(self, matched_count, upserted_id=None):
        self.matched_count = matched_count
        self.modified_count = matched_count
        self.upserted_id = upserted_id


class _FakeCyclesCollection:
    """Reproduit la sémantique réelle de MongoDB pour `update_one` (cf. docstring module)."""

    def __init__(self, docs=None):
        self.docs = docs if docs is not None else {}

    def update_one(self, filt, update, upsert=False):
        _id = filt["_id"]
        set_fields = update.get("$set", {})
        if _id in self.docs:
            self.docs[_id].update(set_fields)
            return _FakeUpdateResult(matched_count=1)
        if upsert:
            self.docs[_id] = dict(set_fields)
            self.docs[_id]["_id"] = _id
            return _FakeUpdateResult(matched_count=0, upserted_id=_id)
        return _FakeUpdateResult(matched_count=0)


class _FakeDb:
    def __init__(self, cycles):
        self.cycles = cycles


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _cleanup():
    import shutil
    if os.path.isdir(_SCRATCH_DIR):
        shutil.rmtree(_SCRATCH_DIR)


class TestFailedCycleBeforePhase7SurvivesQuota(unittest.TestCase):
    """Un cycle qui plante avant la Phase 7 (document absent) conserve error_type='quota'."""

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_error_type_cost_and_duration_survive(self):
        cycle_id = "20260101_000000"
        stdout_path = os.path.join(_SCRATCH_DIR, "stdout.log")
        stderr_path = os.path.join(_SCRATCH_DIR, "stderr.log")
        _write(stdout_path, "some output\ncost=$0.42\nquota exceeded\n")
        _write(stderr_path, "quota exceeded, retry later\n")

        fake_db = _FakeDb(_FakeCyclesCollection())  # document absent : Phase 7 n'a jamais tourné

        with patch("orchestration.runner.mongo_repo._db", return_value=fake_db), \
             patch("orchestration.runner.send_telegram"):
            cycle_log = MagicMock()
            runner._handle_trade_post_run(
                cycle_id=cycle_id, trigger="auto", started_at=datetime.now(timezone.utc),
                duration=123.7, exit_code=1, stderr_path=stderr_path, stdout_path=stdout_path,
                cycle_log=cycle_log,
            )

        doc = fake_db.cycles.docs[cycle_id]
        self.assertEqual(doc["error_type"], "quota")
        self.assertEqual(doc["api_cost_usd"], 0.42)
        self.assertIn("duration_s", doc)
        self.assertNotIn("duration_seconds", doc)


class TestFailedCycleBeforePhase7SurvivesCrash(unittest.TestCase):
    """Même scénario côté crash (pas de mot-clé quota) : error_type='crash' conservé."""

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_error_type_crash_survives(self):
        cycle_id = "20260101_000001"
        stdout_path = os.path.join(_SCRATCH_DIR, "stdout.log")
        stderr_path = os.path.join(_SCRATCH_DIR, "stderr.log")
        _write(stdout_path, "some output\ncost=$0.10\n")
        _write(stderr_path, "Traceback (most recent call last):\nValueError: boom\n")

        fake_db = _FakeDb(_FakeCyclesCollection())

        with patch("orchestration.runner.mongo_repo._db", return_value=fake_db), \
             patch("orchestration.runner.send_telegram"):
            cycle_log = MagicMock()
            runner._handle_trade_post_run(
                cycle_id=cycle_id, trigger="auto", started_at=datetime.now(timezone.utc),
                duration=45.0, exit_code=1, stderr_path=stderr_path, stdout_path=stdout_path,
                cycle_log=cycle_log,
            )

        doc = fake_db.cycles.docs[cycle_id]
        self.assertEqual(doc["error_type"], "crash")
        self.assertEqual(doc["api_cost_usd"], 0.10)
        self.assertEqual(doc["duration_s"], 45)


class TestSuccessfulCycleNotRegressed(unittest.TestCase):
    """Un cycle réussi (document déjà créé par la Phase 7 en sous-processus) garde le
    comportement actuel : les trois champs sont mis à jour, error_type reste None."""

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_updates_existing_document_without_error_type(self):
        cycle_id = "20260101_000002"
        stdout_path = os.path.join(_SCRATCH_DIR, "stdout.log")
        stderr_path = os.path.join(_SCRATCH_DIR, "stderr.log")
        _write(stdout_path, "cost=$1.23\n")
        _write(stderr_path, "")

        # Document déjà créé par phase7_mongo.py (sous-processus, Phase 7 réussie).
        fake_db = _FakeDb(_FakeCyclesCollection({cycle_id: {"_id": cycle_id, "status": "completed"}}))

        with patch("orchestration.runner.mongo_repo._db", return_value=fake_db), \
             patch("orchestration.runner.send_telegram"):
            cycle_log = MagicMock()
            runner._handle_trade_post_run(
                cycle_id=cycle_id, trigger="auto", started_at=datetime.now(timezone.utc),
                duration=200.0, exit_code=0, stderr_path=stderr_path, stdout_path=stdout_path,
                cycle_log=cycle_log,
            )

        doc = fake_db.cycles.docs[cycle_id]
        self.assertIsNone(doc["error_type"])
        self.assertEqual(doc["api_cost_usd"], 1.23)
        self.assertEqual(doc["billing_mode"], "abonnement")
        self.assertEqual(doc["duration_s"], 200)
        self.assertEqual(doc["status"], "completed")  # champ Phase 7 non écrasé


class TestDurationUnificationDoesNotEraseHistoricalField(unittest.TestCase):
    """Un document historique qui ne porte que `duration_seconds` (102 cycles en base) n'est
    pas altéré : les nouvelles écritures ajoutent `duration_s` sans toucher au champ existant."""

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_legacy_duration_seconds_field_untouched(self):
        cycle_id = "20260101_000003"
        stdout_path = os.path.join(_SCRATCH_DIR, "stdout.log")
        stderr_path = os.path.join(_SCRATCH_DIR, "stderr.log")
        _write(stdout_path, "no cost line here\n")
        _write(stderr_path, "Traceback: boom\n")

        # Document historique créé par une ancienne version de _handle_error (avant #452).
        fake_db = _FakeDb(_FakeCyclesCollection({cycle_id: {"_id": cycle_id, "duration_seconds": 99.0}}))

        with patch("orchestration.runner.mongo_repo._db", return_value=fake_db), \
             patch("orchestration.runner.send_telegram"):
            cycle_log = MagicMock()
            runner._handle_trade_post_run(
                cycle_id=cycle_id, trigger="auto", started_at=datetime.now(timezone.utc),
                duration=30.0, exit_code=1, stderr_path=stderr_path, stdout_path=stdout_path,
                cycle_log=cycle_log,
            )

        doc = fake_db.cycles.docs[cycle_id]
        self.assertEqual(doc["duration_seconds"], 99.0)  # jamais supprimé, pas de migration (#452)
        self.assertEqual(doc["duration_s"], 30)  # nouvelle écriture, nom unifié


class TestUnmatchedUpdateIsTraced(unittest.TestCase):
    """Une écriture qui ne matche aucun document (créée via upsert) laisse une trace dans le
    cycle_log au lieu de passer en silence — coeur du bug #452."""

    def test_perf_update_on_missing_document_logs_warning(self):
        fake_db = _FakeDb(_FakeCyclesCollection())
        cycle_log = MagicMock()

        with patch("orchestration.runner.mongo_repo._db", return_value=fake_db):
            runner._update_perf_in_mongo("20260101_000004", 12, "crash", cycle_log)

        warning_msgs = [c.args[0] for c in cycle_log.warning.call_args_list]
        self.assertTrue(any("aucun document existant" in m for m in warning_msgs))

    def test_perf_update_on_existing_document_does_not_warn(self):
        cycle_id = "20260101_000005"
        fake_db = _FakeDb(_FakeCyclesCollection({cycle_id: {"_id": cycle_id}}))
        cycle_log = MagicMock()

        with patch("orchestration.runner.mongo_repo._db", return_value=fake_db):
            runner._update_perf_in_mongo(cycle_id, 12, None, cycle_log)

        cycle_log.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
