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


def _get_dotted(doc: dict, dotted_key: str):
    cursor = doc
    for part in dotted_key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


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
        for dotted_key, spec in update.get("$push", {}).items():
            existing = _get_dotted(self.doc, dotted_key) or []
            each = spec["$each"] if isinstance(spec, dict) and "$each" in spec else [spec]
            updated = existing + each
            if isinstance(spec, dict) and "$slice" in spec:
                updated = updated[spec["$slice"]:] if spec["$slice"] < 0 else updated[:spec["$slice"]]
            _set_dotted(self.doc, dotted_key, updated)


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


class TestSaveMakerAbandonedEntry(unittest.TestCase):
    """#502 : trace un abandon d'entrée maker sur dépassement du budget de concession — même
    garde-fous `$set`/sans `upsert` que save_maker_pending_orders (#498), plus un `$push`/`$slice`
    pour borner l'historique aux 20 derniers abandons."""

    def test_no_mongo_uri_returns_false_without_attempting_write(self):
        with patch.object(mongo_repo, "_db", return_value=None):
            result = mongo_repo.save_maker_abandoned_entry({"coin": "BTC"})
        self.assertFalse(result)

    def test_successful_write_pushes_entry_and_sets_dedicated_timestamp(self):
        collection = _FakeDashboardStateCollection({"_id": "current"})
        fake_db = _FakeDb(collection)
        entry = {"coin": "ETH", "concession_pct": 0.004, "max_concession_pct": 0.003}

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            result = mongo_repo.save_maker_abandoned_entry(entry)

        self.assertTrue(result)
        self.assertEqual(collection.doc["watchers"]["maker_abandoned_entries"], [entry])
        self.assertIn("maker_abandoned_updated_at", collection.doc["watchers"])

    def test_no_document_yet_is_not_created_by_the_watcher(self):
        collection = _FakeDashboardStateCollection(None)
        fake_db = _FakeDb(collection)

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            mongo_repo.save_maker_abandoned_entry({"coin": "BTC"})

        self.assertIsNone(collection.doc)
        _filt, _update, upsert = collection.update_one_calls[0]
        self.assertFalse(upsert)

    def test_history_is_bounded_to_the_last_20_entries(self):
        existing_doc = {
            "_id": "current",
            "watchers": {"maker_abandoned_entries": [{"coin": f"C{i}"} for i in range(20)]},
        }
        collection = _FakeDashboardStateCollection(existing_doc)
        fake_db = _FakeDb(collection)

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            mongo_repo.save_maker_abandoned_entry({"coin": "NEW"})

        entries = collection.doc["watchers"]["maker_abandoned_entries"]
        self.assertEqual(len(entries), 20)
        self.assertEqual(entries[-1], {"coin": "NEW"})
        self.assertEqual(entries[0], {"coin": "C1"})  # le plus ancien (C0) est sorti

    def test_partial_set_preserves_the_rest_of_the_document(self):
        existing_doc = {
            "_id": "current",
            "open_positions": [{"coin": "SOL"}],
            "watchers": {"maker_pending_orders": [{"coin": "OLD"}]},
        }
        collection = _FakeDashboardStateCollection(existing_doc)
        fake_db = _FakeDb(collection)

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            mongo_repo.save_maker_abandoned_entry({"coin": "ETH"})

        self.assertEqual(collection.doc["open_positions"], [{"coin": "SOL"}])
        self.assertEqual(collection.doc["watchers"]["maker_pending_orders"], [{"coin": "OLD"}])

    def test_write_exception_is_caught_and_returns_false(self):
        class _RaisingCollection:
            def update_one(self, *a, **kw):
                raise RuntimeError("Mongo injoignable")

        fake_db = _FakeDb(_RaisingCollection())
        with patch.object(mongo_repo, "_db", return_value=fake_db):
            result = mongo_repo.save_maker_abandoned_entry({"coin": "BTC"})
        self.assertFalse(result)


class TestSaveTradeHistorySlices(unittest.TestCase):
    """#500 : mêmes garde-fous que save_maker_pending_orders (#498), pour les trois slices
    dérivées de trade_history (open_positions, closed_trades, financials) publiées par les
    watchers entre deux passages de la Phase 7."""

    def test_no_mongo_uri_returns_false_without_attempting_write(self):
        with patch.object(mongo_repo, "_db", return_value=None):
            result = mongo_repo.save_trade_history_slices([{"coin": "BTC"}], [], {})
        self.assertFalse(result)

    def test_successful_write_sets_the_three_slices_and_dedicated_timestamp(self):
        collection = _FakeDashboardStateCollection({"_id": "current"})
        fake_db = _FakeDb(collection)
        open_positions = [{"coin": "ETH", "entry_price": 2000.0}]
        closed_trades = [{"coin": "XBT", "pnl_usdc": 1.43}]
        financials = {"global": {"net_usdc": 1.43}}

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            result = mongo_repo.save_trade_history_slices(open_positions, closed_trades, financials)

        self.assertTrue(result)
        filt, update, upsert = collection.update_one_calls[0]
        self.assertEqual(filt, {"_id": "current"})
        self.assertFalse(upsert)
        self.assertEqual(
            set(update["$set"].keys()),
            {"open_positions", "closed_trades", "financials", "watchers.trade_history_slices_updated_at"},
        )
        self.assertEqual(update["$set"]["open_positions"], open_positions)
        self.assertEqual(update["$set"]["closed_trades"], closed_trades)
        self.assertEqual(update["$set"]["financials"], financials)
        self.assertIsInstance(update["$set"]["watchers.trade_history_slices_updated_at"], str)

    def test_no_document_yet_is_not_created_by_the_watcher(self):
        """Sans `upsert` : une publication avant le premier passage de la Phase 7 ne doit créer
        aucun document amputé (sans `config`, `watchers.maker_pending_orders`, ...)."""
        collection = _FakeDashboardStateCollection(None)
        fake_db = _FakeDb(collection)

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            mongo_repo.save_trade_history_slices([{"coin": "BTC"}], [], {})

        self.assertIsNone(collection.doc)
        _filt, _update, upsert = collection.update_one_calls[0]
        self.assertFalse(upsert)

    def test_partial_set_preserves_the_rest_of_the_document(self):
        """Critère d'acceptation #500 : le `$set` partiel ne doit écraser ni les champs propres à
        la Phase 7 (`config`, `updated_at`) ni les autres watchers (`maker_pending_orders`)."""
        existing_doc = {
            "_id": "current",
            "updated_at": "2026-09-14T08:00:00+00:00",
            "config": {"min_signal_score": 6},
            "open_positions": [{"coin": "XBT"}],
            "closed_trades": [{"coin": "OLD"}],
            "financials": {"global": {"net_usdc": 0.0}},
            "watchers": {
                "tp_watcher": {"status": "ok"},
                "maker_watcher": {"total_fills": 5},
                "maker_pending_orders": [{"coin": "SOL", "txid": "PENDINGTX"}],
            },
        }
        collection = _FakeDashboardStateCollection(existing_doc)
        fake_db = _FakeDb(collection)
        new_positions = [{"coin": "ETH"}]
        new_closed = [{"coin": "XBT", "pnl_usdc": 1.43}]
        new_financials = {"global": {"net_usdc": 1.43}}

        with patch.object(mongo_repo, "_db", return_value=fake_db):
            mongo_repo.save_trade_history_slices(new_positions, new_closed, new_financials)

        self.assertEqual(collection.doc["updated_at"], "2026-09-14T08:00:00+00:00")
        self.assertEqual(collection.doc["config"], {"min_signal_score": 6})
        self.assertEqual(collection.doc["open_positions"], new_positions)
        self.assertEqual(collection.doc["closed_trades"], new_closed)
        self.assertEqual(collection.doc["financials"], new_financials)
        self.assertEqual(collection.doc["watchers"]["tp_watcher"], {"status": "ok"})
        self.assertEqual(collection.doc["watchers"]["maker_watcher"], {"total_fills": 5})
        self.assertEqual(collection.doc["watchers"]["maker_pending_orders"], [{"coin": "SOL", "txid": "PENDINGTX"}])
        self.assertIn("trade_history_slices_updated_at", collection.doc["watchers"])

    def test_write_exception_is_caught_and_returns_false(self):
        class _RaisingCollection:
            def update_one(self, *a, **kw):
                raise RuntimeError("Mongo injoignable")

        fake_db = _FakeDb(_RaisingCollection())
        with patch.object(mongo_repo, "_db", return_value=fake_db):
            result = mongo_repo.save_trade_history_slices([{"coin": "BTC"}], [], {})
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
