"""Tests de la résistance 4h Kraken (#516) : calcul, bougie en cours exclue, repli Kraken
indisponible, recalibrage Phase 0 (stop d'origine, TP existant conservé).

Aucun appel réseau : le CLI Kraken n'est jamais invoqué (binance patché partout où il pourrait l'être).
"""
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot", "core", "phases"))

from core import trade_helpers  # noqa: E402
from phase0_calibrate_tp import recalibrate_tps  # noqa: E402

NOW = 1_000_000 * 14400 + 3600  # 1h après l'ouverture de la bougie en cours


def _candle(open_ts, high):
    return [open_ts, "1", str(high), "1", "1", "1", "1", 1]


class TestResistanceFromCandles(unittest.TestCase):
    def test_highest_of_last_n_closed(self):
        t = NOW // 14400 * 14400
        candles = [_candle(t - 14400 * k, h) for k, h in ((4, 500), (3, 120), (2, 110), (1, 100))]
        self.assertEqual(trade_helpers.resistance_from_candles(candles, 3, NOW), 120.0)
        self.assertEqual(trade_helpers.resistance_from_candles(candles, 2, NOW), 110.0)

    def test_current_candle_excluded(self):
        t = NOW // 14400 * 14400
        candles = [_candle(t - 14400, 100), _candle(t, 999)]
        self.assertEqual(trade_helpers.resistance_from_candles(candles, 30, NOW), 100.0)

    def test_candle_just_closed_is_included(self):
        t = NOW // 14400 * 14400
        self.assertEqual(trade_helpers.resistance_from_candles([_candle(t - 14400, 77)], 30, t), 77.0)

    def test_no_closed_candle_returns_none(self):
        t = NOW // 14400 * 14400
        self.assertIsNone(trade_helpers.resistance_from_candles([_candle(t, 5)], 30, NOW))
        self.assertIsNone(trade_helpers.resistance_from_candles([], 30, NOW))


class TestFetchResistanceFallback(unittest.TestCase):
    def test_kraken_failure_returns_none(self):
        with patch("core.trade_helpers.binance", side_effect=RuntimeError("kraken failed")):
            self.assertIsNone(trade_helpers.fetch_resistance_4h("ETH", 30))

    def test_garbage_response_returns_none(self):
        with patch("core.trade_helpers.binance", return_value="not json"):
            self.assertIsNone(trade_helpers.fetch_resistance_4h("ETH", 30))

    def test_uses_kraken_ohlc_240(self):
        t = int(trade_helpers.time.time()) // 14400 * 14400
        raw = '{"ETHUSDC": [[%d, "1", "50", "1", "1", "1", "1", 1]]}' % (t - 14400)
        with patch("core.trade_helpers.binance", return_value=raw) as m:
            self.assertEqual(trade_helpers.fetch_resistance_4h("ETH", 30), 50.0)
        self.assertEqual(m.call_args[0][:4], ("ohlc", "ETHUSDC", "--interval", "240"))


def _trade(**kw):
    base = {"coin": "ETH", "status": "open", "entry_price": 100.0, "stop_price": 100.9,
            "initial_stop_price": 93.0, "tp_price": 110.0, "quantity": 1}
    base.update(kw)
    return base


CFG = {"reward_risk_ratio": 1.5, "fee_round_trip_pct": 0.009, "max_tp_pct": 0.06, "resistance_lookback_4h": 30}


class TestRecalibrateTps(unittest.TestCase):
    def test_resistance_caps_and_initial_stop_used(self):
        history = [_trade()]
        changes = recalibrate_tps(history, CFG, lambda coin, n: 104.0)
        self.assertAlmostEqual(history[0]["tp_price"], 104.0 * 0.98)
        self.assertEqual(changes[0][0], "ETH")

    def test_stop_courant_remonte_ne_degrade_pas_la_cible(self):
        history = [_trade()]  # stop courant 100.9 : avec lui, tp_mecanique serait ~ +1.8 %
        recalibrate_tps(history, CFG, lambda coin, n: 200.0)
        self.assertAlmostEqual(history[0]["tp_price"], 106.0)  # plafond max_tp_pct, mécanique = +11.3 %

    def test_resistance_under_floor_gives_floor(self):
        history = [_trade()]
        recalibrate_tps(history, CFG, lambda coin, n: 100.5)
        self.assertAlmostEqual(history[0]["tp_price"], 101.8)

    def test_kraken_unavailable_keeps_existing_tp(self):
        history = [_trade()]
        changes = recalibrate_tps(history, CFG, lambda coin, n: None)
        self.assertEqual(changes, [])
        self.assertEqual(history[0]["tp_price"], 110.0)

    def test_lookback_passed_from_config(self):
        seen = []
        recalibrate_tps([_trade()], dict(CFG, resistance_lookback_4h=12), lambda c, n: seen.append(n))
        self.assertEqual(seen, [12])

    def test_closed_trades_ignored(self):
        history = [_trade(status="closed")]
        self.assertEqual(recalibrate_tps(history, CFG, lambda c, n: 104.0), [])


if __name__ == "__main__":
    unittest.main()
