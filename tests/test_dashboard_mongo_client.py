"""Tests pour dashboard/mongo_client.py — lecture seule MongoDB, jamais de vraie connexion Atlas
(#432). Contrairement à phase7_mongo.py (import `pymongo.MongoClient` fait à l'intérieur d'un
script exécuté à chaque appel), mongo_client.py fait `from pymongo import MongoClient` une seule
fois à l'import du module : on patche donc `mongo_client.MongoClient` (le nom lié dans ce module),
pas `pymongo.MongoClient` — jamais de connexion réseau réelle dans ces tests.

Le module a un cache TTL (dashboard/cache.py) et un client Mongo mémorisés en variables de
module : chaque test réinitialise les deux via setUp() pour rester indépendant des autres."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "dashboard"))

import mongo_client  # noqa: E402
import settings  # noqa: E402
from cache import cache  # noqa: E402


class TestMongoClientBase(unittest.TestCase):
    def setUp(self):
        cache.clear()
        mongo_client._client = None
        settings.MONGODB_URI = "mongodb://fake"
        settings.MONGODB_DB = "agent-binance"


class TestGetDashboardStateUnavailable(TestMongoClientBase):
    def test_missing_uri_raises_mongo_unavailable_without_connecting(self):
        settings.MONGODB_URI = ""
        with patch("mongo_client.MongoClient") as mock_ctor:
            with self.assertRaises(mongo_client.MongoUnavailable):
                mongo_client.get_dashboard_state()
            mock_ctor.assert_not_called()

    def test_connection_error_raises_mongo_unavailable(self):
        from pymongo.errors import ServerSelectionTimeoutError
        mock_db = MagicMock()
        mock_db.dashboard_state.find_one.side_effect = ServerSelectionTimeoutError("timeout")
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            with self.assertRaises(mongo_client.MongoUnavailable):
                mongo_client.get_dashboard_state()


class TestGetDashboardStateMissing(TestMongoClientBase):
    def test_no_document_raises_dashboard_state_missing(self):
        mock_db = MagicMock()
        mock_db.dashboard_state.find_one.return_value = None
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            with self.assertRaises(mongo_client.DashboardStateMissing):
                mongo_client.get_dashboard_state()


class TestGetDashboardStateSuccess(TestMongoClientBase):
    def test_returns_document_when_present(self):
        doc = {"_id": "current", "cycle_status": "completed"}
        mock_db = MagicMock()
        mock_db.dashboard_state.find_one.return_value = doc
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            self.assertEqual(mongo_client.get_dashboard_state(), doc)

    def test_second_call_within_ttl_does_not_hit_mongo_again(self):
        doc = {"_id": "current"}
        mock_db = MagicMock()
        mock_db.dashboard_state.find_one.return_value = doc
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client) as mock_ctor:
            mongo_client.get_dashboard_state()
            mongo_client.get_dashboard_state()
            self.assertEqual(mock_ctor.call_count, 1)
            self.assertEqual(mock_db.dashboard_state.find_one.call_count, 1)


class TestGetRecentCycles(TestMongoClientBase):
    def test_returns_list_from_cycles_collection(self):
        rows = [{"cycle_id": "c1"}, {"cycle_id": "c2"}]
        mock_db = MagicMock()
        mock_db.cycles.find.return_value.limit.return_value = rows
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            self.assertEqual(mongo_client.get_recent_cycles(60), rows)

    def test_connection_error_raises_mongo_unavailable(self):
        from pymongo.errors import ServerSelectionTimeoutError
        mock_db = MagicMock()
        mock_db.cycles.find.side_effect = ServerSelectionTimeoutError("timeout")
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            with self.assertRaises(mongo_client.MongoUnavailable):
                mongo_client.get_recent_cycles(60)


class TestGetLatestWeeklyAnalysis(TestMongoClientBase):
    """#453 — plus récent document weekly_analysis, ou None si jamais généré."""

    def test_returns_most_recent_document(self):
        doc = {"_id": "2026-W35", "text": "Semaine calme.", "generated_at": "2026-08-24T00:10:00+00:00"}
        mock_db = MagicMock()
        mock_db.weekly_analysis.find_one.return_value = doc
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            self.assertEqual(mongo_client.get_latest_weekly_analysis(), doc)
        mock_db.weekly_analysis.find_one.assert_called_once_with(sort=[("generated_at", -1)])

    def test_returns_none_when_never_generated(self):
        mock_db = MagicMock()
        mock_db.weekly_analysis.find_one.return_value = None
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            self.assertIsNone(mongo_client.get_latest_weekly_analysis())

    def test_connection_error_raises_mongo_unavailable(self):
        from pymongo.errors import ServerSelectionTimeoutError
        mock_db = MagicMock()
        mock_db.weekly_analysis.find_one.side_effect = ServerSelectionTimeoutError("timeout")
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("mongo_client.MongoClient", return_value=mock_client):
            with self.assertRaises(mongo_client.MongoUnavailable):
                mongo_client.get_latest_weekly_analysis()


if __name__ == "__main__":
    unittest.main()
