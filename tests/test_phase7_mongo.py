"""Tests d'intégration pour phase7_mongo.py — persistance du cycle en MongoDB.

Le script fait `from pymongo import MongoClient` en interne, une fois par exécution : on
patche l'attribut `pymongo.MongoClient` (module réellement importé, jamais de vraie connexion
Atlas) avant d'exécuter le script, pour que ce `from ... import` récupère la version mockée.
`tg()` est mockée par précaution (appelée uniquement en cas d'erreur Mongo).

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import ANY, MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE7_MONGO_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase7_mongo.py")


def _run_phase7_mongo(doc, mongo_uri, mongo_client=None, mongo_client_side_effect=None):
    """Exécute phase7_mongo.py. Retourne (stdout_text, exit_code, mock_tg, mock_mongo_client)."""
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase7_input.json"
    with open(in_path, "w") as f:
        json.dump({"doc": doc}, f)

    stdout_capture = io.StringIO()
    try:
        with contextlib.ExitStack() as stack:
            # Valeur forcée à une clé *présente* (jamais absente) : core.env._load_env() utilise
            # os.environ.setdefault() au premier import de core.trade_helpers dans le process de
            # test, ce qui écraserait un simple `del` avec la vraie valeur de .env.
            stack.enter_context(patch.dict(os.environ, {"MONGODB_URI": mongo_uri or ""}))
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_mongo_client = stack.enter_context(
                patch(
                    "pymongo.MongoClient",
                    return_value=mongo_client, side_effect=mongo_client_side_effect,
                ),
            )
            stack.enter_context(contextlib.redirect_stdout(stdout_capture))

            exit_code = harness.exec_phase_script(PHASE7_MONGO_PATH, cycle_id)

        return stdout_capture.getvalue(), exit_code, mock_tg, mock_mongo_client
    finally:
        harness.remove_if_exists(in_path)


class TestMongoSkippedWhenUriMissing(unittest.TestCase):
    """MONGODB_URI absent/vide -> aucune connexion tentée, sortie 'skipped'."""

    def test_skips_without_mongodb_uri(self):
        stdout, exit_code, mock_tg, mock_mongo_client = _run_phase7_mongo(
            {"executed": 1}, mongo_uri=None, mongo_client=MagicMock(),
        )

        self.assertIn("PHASE7_MONGO_DONE|status=skipped", stdout)
        self.assertEqual(exit_code, 0)
        mock_mongo_client.assert_not_called()
        mock_tg.assert_not_called()


class TestMongoWriteSucceeds(unittest.TestCase):
    """MongoClient mocké, écriture réussie -> status=ok, upsert appelé avec le bon document."""

    def test_writes_doc_via_upsert_when_uri_set(self):
        mock_db = MagicMock()
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)

        stdout, exit_code, mock_tg, mock_mongo_client = _run_phase7_mongo(
            {"executed": 2}, mongo_uri="mongodb://fake", mongo_client=mock_client,
        )

        self.assertIn("PHASE7_MONGO_DONE|status=ok", stdout)
        self.assertIsNone(exit_code)
        mock_mongo_client.assert_called_once()
        mock_db.cycles.update_one.assert_called_once_with(
            {"_id": ANY}, {"$set": {"executed": 2}}, upsert=True,
        )
        mock_client.close.assert_called_once()
        mock_tg.assert_not_called()


class TestMongoWriteFails(unittest.TestCase):
    """Exception levée par MongoClient -> notification tg(), status=error, exit code 1."""

    def test_notifies_and_exits_nonzero_on_mongo_error(self):
        stdout, exit_code, mock_tg, mock_mongo_client = _run_phase7_mongo(
            {"executed": 1}, mongo_uri="mongodb://fake",
            mongo_client_side_effect=ConnectionError("boom"),
        )

        self.assertIn("PHASE7_MONGO_DONE|status=error", stdout)
        self.assertEqual(exit_code, 1)
        mock_tg.assert_called_once()
        self.assertIn("Mongo write failed", mock_tg.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
