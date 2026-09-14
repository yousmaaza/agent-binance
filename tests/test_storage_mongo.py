"""Tests pour storage/mongo.py — MongoRepository.save_maker_pending_orders (#498).

`_FakeDashboardStateCollection` applique la sémantique réelle de MongoDB pour un `$set` à
chemins pointés (`"watchers.maker_pending_orders"`) : fusion dans les sous-documents imbriqués,
jamais un remplacement de tout le document — un `dict.update()` naïf sur les clés pointées ne
prouverait rien face au bug précis de #498 (Phase 7 écrasée par le watcher). Elle modélise aussi
le cas `_id` absent sans `upsert` : `update_one` ne matche rien et ne crée rien (retour de review
#498 — un document créé avec pour seul contenu ces deux champs serait amputé aux yeux du
dashboard, `find_one` ne renverrait plus `None` donc `DashboardStateMissing` ne se déclencherait
plus)."""
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from storage.mongo import mongo_repo  # noqa: E402


def _set_dotted(doc: dict, dotted_key: str, value) -> None:
    parts = dotted_key.split(".")
    cursor = doc
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


class _FakeDashboardStateCollection:
    """`doc=None` modélise un document absent (avant le premier passage de la Phase 7)."""

    def __init__(self, doc: dict | None):
        self.doc = doc
        self.update_one_calls = []

    def update_one(self, filt, update, upsert=False):
        self.update_one_calls.append((filt, update, upsert))
        if self.doc is None:
            if not upsert:
                return  # ne matche rien, ne crée rien — sémantique réelle de Mongo
            self.doc = {"_id": filt["_id"]}
        for dotted_key, value in update.get("$set", {}).items():
            _set_dotted(self.doc, dotted_key, value)


class _FakeDb:
    def __init__(self, dashboard_state):
        self.dashboard_state = dashboard_state


class TestSaveMakerPendingOrders(unittest.TestCase):
    def test_no_mongo_uri_returns_false_without_attempting_write(self):
        with patch.object(mongo_repo, "_db", return_value=None):
            result = mongo_repo.save_maker_pending_orders([{"coin": "BTC"}])
        self.assertFalse(result)

    def test_successful_write_sets_orders_and_dedicated_timestamp(self):
        collection = _FakeDashboardStateCollection({"_id": "current"})
        fake_db = _FakeDb(collection)
        orders = [{"coin": "BTC", "txid": "TX1", "current_limit_price": 60000.0}]

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            result = mongo_repo.save_maker_pending_orders(orders)

        self.assertTrue(result)
        filt, update, upsert = collection.update_one_calls[0]
        self.assertEqual(filt, {"_id": "current"})
        self.assertFalse(upsert)
        self.assertEqual(set(update["$set"].keys()),
                          {"watchers.maker_pending_orders", "watchers.maker_pending_updated_at"})
        self.assertEqual(update["$set"]["watchers.maker_pending_orders"], orders)
        self.assertIsInstance(update["$set"]["watchers.maker_pending_updated_at"], str)

    def test_no_document_yet_is_not_created_by_the_watcher(self):
        """#498, retour de review : sans `upsert`, une publication avant le premier passage de la
        Phase 7 ne doit créer aucun document amputé (sans open_positions/financials/config)."""
        collection = _FakeDashboardStateCollection(None)
        fake_db = _FakeDb(collection)

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            mongo_repo.save_maker_pending_orders([{"coin": "BTC"}])

        self.assertIsNone(collection.doc)
        _filt, _update, upsert = collection.update_one_calls[0]
        self.assertFalse(upsert)

    def test_partial_set_preserves_the_rest_of_the_document(self):
        """#498, critère d'acceptation : le `$set` partiel ne doit écraser ni les champs de la
        Phase 7 (open_positions, financials, ...) ni les autres watchers (tp_watcher)."""
        existing_doc = {
            "_id": "current",
            "updated_at": "2026-09-14T08:00:00+00:00",
            "open_positions": [{"coin": "SOL"}],
            "financials": {"global": {"net_usdc": 42.0}},
            "watchers": {
                "tp_watcher": {"status": "ok"},
                "maker_watcher": {"total_fills": 5},
                "maker_pending_orders": [{"coin": "OLD", "txid": "OLDTX"}],
            },
        }
        collection = _FakeDashboardStateCollection(existing_doc)
        fake_db = _FakeDb(collection)
        new_orders = [{"coin": "BTC", "txid": "TX1", "current_limit_price": 60000.0}]

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            mongo_repo.save_maker_pending_orders(new_orders)

        self.assertEqual(collection.doc["updated_at"], "2026-09-14T08:00:00+00:00")
        self.assertEqual(collection.doc["open_positions"], [{"coin": "SOL"}])
        self.assertEqual(collection.doc["financials"], {"global": {"net_usdc": 42.0}})
        self.assertEqual(collection.doc["watchers"]["tp_watcher"], {"status": "ok"})
        self.assertEqual(collection.doc["watchers"]["maker_watcher"], {"total_fills": 5})
        self.assertEqual(collection.doc["watchers"]["maker_pending_orders"], new_orders)
        self.assertIn("maker_pending_updated_at", collection.doc["watchers"])

    def test_write_exception_is_caught_and_returns_false(self):
        class _RaisingCollection:
            def update_one(self, *a, **kw):
                raise RuntimeError("Mongo injoignable")

        fake_db = _FakeDb(_RaisingCollection())
        with patch.object(mongo_repo, "_db", return_value=fake_db):
            result = mongo_repo.save_maker_pending_orders([{"coin": "BTC"}])
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
