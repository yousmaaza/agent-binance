"""Tests d'intégration pour phase7_hb_check.py — détection de heartbeats manquants.

Le script lit `logs/cycle_{CYCLE_ID}_phases.jsonl` (format écrit par core.heartbeat.hb(), voir
tests/test_phase7_hb_check.py::_write_heartbeats) et complète les phases 0-6 manquantes via
core.heartbeat.hb() (status="recovered") + notifie via tg(). On laisse hb()/init() réellement
écrire dans logs/ avec un cycle_id unique (harness.new_cycle_id()) pour rester fidèle au
comportement réel, puis on nettoie le fichier généré à la fin de chaque test. `tg()` est mockée
(jamais de vrai curl).

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE7_HB_CHECK_PATH = os.path.join(
    PROJECT_DIR, "binance-bot", "core", "phases", "phase7_hb_check.py",
)


def _hb_log_path(cycle_id):
    return os.path.join(PROJECT_DIR, "logs", f"cycle_{cycle_id}_phases.jsonl")


def _write_heartbeats(cycle_id, phases):
    """Écrit un fichier logs/cycle_{cycle_id}_phases.jsonl minimal avec les phases données."""
    path = _hb_log_path(cycle_id)
    with open(path, "w") as f:
        f.writelines(json.dumps({"phase": p, "status": "ok", "duration_s": 1.0}) + "\n" for p in phases)


def _run_phase7_hb_check(cycle_id):
    """Exécute phase7_hb_check.py. Retourne (stdout_text, mock_tg)."""
    stdout_capture = io.StringIO()
    with contextlib.ExitStack() as stack:
        mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
        stack.enter_context(contextlib.redirect_stdout(stdout_capture))
        harness.exec_phase_script(PHASE7_HB_CHECK_PATH, cycle_id)
    return stdout_capture.getvalue(), mock_tg


class TestNoMissingHeartbeatsWhenAllPhasesPresent(unittest.TestCase):
    """Toutes les phases 0-6 présentes dans le jsonl -> aucune détection, aucune notif."""

    def test_missing_is_empty_when_all_phases_logged(self):
        cycle_id = harness.new_cycle_id()
        _write_heartbeats(cycle_id, [0, 1, 2, 3, 4, 5, 6])
        try:
            stdout, mock_tg = _run_phase7_hb_check(cycle_id)

            self.assertIn("PHASE7_HB_CHECK_DONE|missing=[]", stdout)
            mock_tg.assert_not_called()
        finally:
            harness.remove_if_exists(_hb_log_path(cycle_id))


class TestMissingHeartbeatsAreRecoveredAndNotified(unittest.TestCase):
    """Une phase manquante -> notification tg() + heartbeat 'recovered' ajouté pour elle."""

    def test_missing_phase_triggers_notification_and_recovery(self):
        cycle_id = harness.new_cycle_id()
        _write_heartbeats(cycle_id, [0, 1, 2, 3, 4, 5])  # phase 6 manquante
        try:
            stdout, mock_tg = _run_phase7_hb_check(cycle_id)

            self.assertIn("PHASE7_HB_CHECK_DONE|missing=[6]", stdout)
            mock_tg.assert_called_once()
            self.assertIn("phases [6]", mock_tg.call_args[0][0])

            with open(_hb_log_path(cycle_id)) as f:
                entries = [json.loads(ln) for ln in f if ln.strip()]
            recovered = [e for e in entries if e["phase"] == 6]
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["status"], "recovered")
        finally:
            harness.remove_if_exists(_hb_log_path(cycle_id))


class TestMissingHeartbeatsWhenLogFileAbsent(unittest.TestCase):
    """Cas limite documenté dans le code : fichier jsonl absent -> toutes les phases 0-6
    considérées manquantes, sans lever d'exception."""

    def test_all_phases_missing_when_log_file_does_not_exist(self):
        cycle_id = harness.new_cycle_id()  # aucun fichier écrit pour ce cycle_id
        try:
            stdout, mock_tg = _run_phase7_hb_check(cycle_id)

            self.assertIn("PHASE7_HB_CHECK_DONE|missing=[0, 1, 2, 3, 4, 5, 6]", stdout)
            mock_tg.assert_called_once()
        finally:
            harness.remove_if_exists(_hb_log_path(cycle_id))


if __name__ == "__main__":
    unittest.main()
