"""Tests pour scripts/backfill_fees.py — rapprochement fills Kraken / trade_history.json (#382).

Tests unitaires purs sur les fonctions de rapprochement et de calcul — jamais d'appel réseau
(binance()) ni d'écriture sur le vrai state/trade_history.json.
"""
import importlib.util
import os
import sys
import unittest
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

_SCRIPT_PATH = os.path.join(PROJECT_DIR, "scripts", "backfill_fees.py")
_spec = importlib.util.spec_from_file_location("backfill_fees", _SCRIPT_PATH)
backfill_fees = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_fees)


def _fill(txid, ordertxid=None, pair=None, type_="buy", vol="0.1", fee="0.5", time=1700000000.0):
    return {
        "_txid": txid, "ordertxid": ordertxid, "pair": pair,
        "type": type_, "vol": vol, "fee": fee, "time": time,
    }


class TestEstimatedFeeRate(unittest.TestCase):
    def test_rate_tiers(self):
        self.assertAlmostEqual(backfill_fees._estimated_fee_rate(datetime(2026, 6, 1, tzinfo=timezone.utc)), 0.0040)
        self.assertAlmostEqual(backfill_fees._estimated_fee_rate(datetime(2026, 7, 15, tzinfo=timezone.utc)), 0.0080)
        self.assertAlmostEqual(backfill_fees._estimated_fee_rate(datetime(2026, 8, 1, tzinfo=timezone.utc)), 0.0060)


class TestMatchEntryFee(unittest.TestCase):
    def test_sums_all_fills_sharing_ordertxid(self):
        trade = {"entry_order_id": "OABC-1"}
        fills = [
            _fill("T1", ordertxid="OABC-1", fee="0.3"),
            _fill("T2", ordertxid="OABC-1", fee="0.2"),
            _fill("T3", ordertxid="OTHER", fee="9.9"),
        ]
        consumed = set()
        fee = backfill_fees._match_entry_fee(trade, fills, consumed)
        self.assertAlmostEqual(fee, 0.5)
        self.assertEqual(consumed, {"T1", "T2"})

    def test_returns_none_when_no_match(self):
        trade = {"entry_order_id": "UNKNOWN"}
        fills = [_fill("T1", ordertxid="OABC-1")]
        self.assertIsNone(backfill_fees._match_entry_fee(trade, fills, set()))

    def test_returns_none_when_entry_order_id_missing(self):
        self.assertIsNone(backfill_fees._match_entry_fee({}, [_fill("T1")], set()))

    def test_already_consumed_fill_not_reused(self):
        trade = {"entry_order_id": "OABC-1"}
        fills = [_fill("T1", ordertxid="OABC-1", fee="0.3")]
        consumed = {"T1"}
        self.assertIsNone(backfill_fees._match_entry_fee(trade, fills, consumed))


class TestMatchExitFee(unittest.TestCase):
    def test_matches_closest_sell_within_volume_tolerance_and_window(self):
        exit_dt = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
        trade = {"coin": "ETH", "quantity": 0.1, "exit_date": exit_dt.isoformat()}
        far = _fill("T_FAR", pair="ETHUSDC", type_="sell", vol="0.1",
                     time=(exit_dt.timestamp() - 3600 * 40))
        close = _fill("T_CLOSE", pair="ETHUSDC", type_="sell", vol="0.1", fee="0.42",
                       time=(exit_dt.timestamp() - 60))
        wrong_pair = _fill("T_WRONG_PAIR", pair="SOLUSDC", type_="sell", vol="0.1",
                            time=exit_dt.timestamp())
        wrong_vol = _fill("T_WRONG_VOL", pair="ETHUSDC", type_="sell", vol="5.0",
                           time=exit_dt.timestamp())
        buy_side = _fill("T_BUY", pair="ETHUSDC", type_="buy", vol="0.1",
                          time=exit_dt.timestamp())
        fills = [far, close, wrong_pair, wrong_vol, buy_side]
        consumed = set()

        fee = backfill_fees._match_exit_fee(trade, fills, consumed)
        self.assertAlmostEqual(fee, 0.42)
        self.assertEqual(consumed, {"T_CLOSE"})

    def test_sl_hit_up_to_48h_before_exit_date_still_matches(self):
        """SL déclenché côté Kraken bien avant la détection du bot au cycle suivant (#382)."""
        exit_dt = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
        trade = {"coin": "ETH", "quantity": 0.1, "exit_date": exit_dt.isoformat()}
        fill = _fill("T1", pair="ETHUSDC", type_="sell", vol="0.1", fee="0.11",
                      time=(exit_dt.timestamp() - 3600 * 18))  # 18h avant
        consumed = set()
        fee = backfill_fees._match_exit_fee(trade, fills=[fill], consumed=consumed)
        self.assertAlmostEqual(fee, 0.11)

    def test_beyond_48h_window_no_match(self):
        exit_dt = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
        trade = {"coin": "ETH", "quantity": 0.1, "exit_date": exit_dt.isoformat()}
        fill = _fill("T1", pair="ETHUSDC", type_="sell", vol="0.1",
                      time=(exit_dt.timestamp() - 3600 * 49))  # 49h avant, hors fenêtre
        self.assertIsNone(backfill_fees._match_exit_fee(trade, [fill], set()))

    def test_volume_outside_tolerance_no_match(self):
        exit_dt = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
        trade = {"coin": "ETH", "quantity": 0.1, "exit_date": exit_dt.isoformat()}
        fill = _fill("T1", pair="ETHUSDC", type_="sell", vol="0.10011",  # >0.0001 relatif
                      time=exit_dt.timestamp())
        self.assertIsNone(backfill_fees._match_exit_fee(trade, [fill], set()))


class TestBackfillIntegration(unittest.TestCase):
    def test_measured_entry_and_exit_no_estimation(self):
        exit_dt = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
        history = [{
            "trade_id": "T1", "status": "closed", "coin": "ETH",
            "entry_order_id": "OABC-1", "entry_price": 1000.0, "exit_price": 1100.0,
            "quantity": 0.1, "date": "2026-07-05T00:00:00+00:00",
            "exit_date": exit_dt.isoformat(),
            "pnl_usdc": 10.0, "pnl_pct": 1.0,  # ancien calcul déjà stocké (pré-#382)
        }]
        fills = [
            _fill("T_ENTRY", ordertxid="OABC-1", fee="0.5"),
            _fill("T_EXIT", pair="ETHUSDC", type_="sell", vol="0.1", fee="0.6", time=exit_dt.timestamp()),
        ]
        updated, stats, incoherent = backfill_fees.backfill(history, fills, force=False)

        pos = updated[0]
        self.assertFalse(pos["fees_estimated"])
        self.assertAlmostEqual(pos["entry_fee_usdc"], 0.5)
        self.assertAlmostEqual(pos["exit_fee_usdc"], 0.6)
        self.assertAlmostEqual(pos["fees_usdc"], 1.1)
        self.assertAlmostEqual(pos["pnl_gross_usdc"], 10.0)
        self.assertAlmostEqual(pos["pnl_gross_pct"], 1.0)
        self.assertAlmostEqual(pos["pnl_usdc"], 8.9)
        self.assertEqual(stats["entries_measured"], 1)
        self.assertEqual(stats["exits_measured"], 1)
        self.assertEqual(stats["trades_updated"], 1)
        self.assertEqual(incoherent, [])

    def test_unmatched_trade_falls_back_to_estimated_rate(self):
        history = [{
            "trade_id": "T1", "status": "closed", "coin": "ETH",
            "entry_order_id": "UNKNOWN", "entry_price": 1000.0, "exit_price": 1100.0,
            "quantity": 0.1, "date": "2026-06-01T00:00:00+00:00",
            "exit_date": "2026-06-02T00:00:00+00:00",
            "pnl_usdc": 10.0, "pnl_pct": 1.0,
        }]
        updated, stats, _incoherent = backfill_fees.backfill(history, fills=[], force=False)

        pos = updated[0]
        self.assertTrue(pos["fees_estimated"])
        self.assertAlmostEqual(pos["entry_fee_usdc"], 1000.0 * 0.1 * 0.0040)
        self.assertAlmostEqual(pos["exit_fee_usdc"], 1100.0 * 0.1 * 0.0040)
        self.assertEqual(stats["entries_estimated"], 1)
        self.assertEqual(stats["exits_estimated"], 1)

    def test_already_backfilled_trade_skipped_without_force(self):
        history = [{
            "trade_id": "T1", "status": "closed", "coin": "ETH",
            "entry_price": 1000.0, "exit_price": 1100.0, "quantity": 0.1,
            "date": "2026-07-05T00:00:00+00:00", "exit_date": "2026-07-05T01:00:00+00:00",
            "fees_usdc": 1.0,
        }]
        _updated, stats, _incoherent = backfill_fees.backfill(history, fills=[], force=False)
        self.assertEqual(stats["trades_skipped_already_done"], 1)
        self.assertEqual(stats["trades_updated"], 0)

    def test_open_trade_skipped(self):
        history = [{"trade_id": "T1", "status": "open", "coin": "ETH"}]
        _updated, stats, _incoherent = backfill_fees.backfill(history, fills=[], force=False)
        self.assertEqual(stats["trades_skipped_not_closed"], 1)
        self.assertEqual(stats["trades_updated"], 0)


class TestBackfillCoherenceGuard(unittest.TestCase):
    """Reproduit le bug de prod #382 (trade SYN 38515bab) : pnl_usdc stocké incohérent avec
    (exit_price - entry_price) * quantity -> ne pas écraser, seulement signaler."""

    def test_incoherent_legacy_trade_preserved_and_flagged(self):
        history = [{
            "trade_id": "38515bab", "status": "closed", "coin": "SYN",
            "entry_order_id": 50609180,  # entier legacy Binance, pas un txid Kraken
            "entry_price": 0.34397, "exit_price": 0.5543, "quantity": 40.0,
            "date": "2026-06-26T00:00:00+00:00", "exit_date": "2026-06-26T01:00:00+00:00",
            "pnl_usdc": -1.165, "pnl_pct": -3.5,
            "close_reason": "sl_hit",
        }]
        updated, stats, incoherent = backfill_fees.backfill(history, fills=[], force=False)

        pos = updated[0]
        # Le trade n'est PAS modifié : ni pnl_usdc, ni pnl_gross_usdc, ni fees_usdc ajoutés.
        self.assertEqual(pos["pnl_usdc"], -1.165)
        self.assertNotIn("pnl_gross_usdc", pos)
        self.assertNotIn("fees_usdc", pos)
        self.assertNotIn("entry_fee_usdc", pos)

        self.assertEqual(stats["trades_incoherents"], 1)
        self.assertEqual(stats["trades_updated"], 0)
        self.assertEqual(len(incoherent), 1)
        self.assertEqual(incoherent[0]["trade_id"], "38515bab")
        self.assertEqual(incoherent[0]["coin"], "SYN")
        self.assertAlmostEqual(incoherent[0]["pnl_usdc_stored"], -1.165)
        # (0.5543 - 0.34397) * 40 = 8.41320... loin de -1.165 -> écart largement > 1%
        self.assertAlmostEqual(incoherent[0]["pnl_recomputed_from_prices"], 8.4132, places=3)
        self.assertGreater(incoherent[0]["rel_diff_pct"], 100)

    def test_closed_trade_without_stored_pnl_flagged_not_crashed(self):
        """Trade closed sans pnl_usdc stocké -> signalé, pas de crash sur trade["pnl_usdc"]."""
        history = [{
            "trade_id": "T2", "status": "closed", "coin": "ETH",
            "entry_price": 1000.0, "exit_price": 1100.0, "quantity": 0.1,
            "date": "2026-07-05T00:00:00+00:00", "exit_date": "2026-07-05T01:00:00+00:00",
        }]
        updated, stats, incoherent = backfill_fees.backfill(history, fills=[], force=False)

        self.assertEqual(stats["trades_incoherents"], 1)
        self.assertEqual(stats["trades_updated"], 0)
        self.assertEqual(len(incoherent), 1)
        self.assertIsNone(incoherent[0]["pnl_usdc_stored"])
        self.assertNotIn("fees_usdc", updated[0])

    def test_coherent_trade_within_tolerance_is_updated_normally(self):
        history = [{
            "trade_id": "T1", "status": "closed", "coin": "ETH",
            "entry_price": 1000.0, "exit_price": 1100.0, "quantity": 0.1,
            "date": "2026-07-05T00:00:00+00:00", "exit_date": "2026-07-05T01:00:00+00:00",
            "pnl_usdc": 10.0, "pnl_pct": 1.0,
        }]
        _updated, stats, incoherent = backfill_fees.backfill(history, fills=[], force=False)
        self.assertEqual(stats["trades_incoherents"], 0)
        self.assertEqual(stats["trades_updated"], 1)
        self.assertEqual(incoherent, [])


if __name__ == "__main__":
    unittest.main()
