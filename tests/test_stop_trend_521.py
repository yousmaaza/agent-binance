"""Tests de #521 : stop de départ fixe -20 % (phase 4), filtre de tendance de fond EMA100 1d (phase 3,
trade_helpers) et cohabitation avec break-even / partiel / cible / stop suiveur.

Toute référence au CLI Kraken est patchée (binance() de trade_helpers, _cli des watchers, doublure
fake_kraken pour la phase 4) : aucun ordre réel ni appel réseau.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from core import trade_helpers  # noqa: E402
from core.trade_helpers import compute_tp_target, ema_last, fetch_daily_trend, initial_stop_price  # noqa: E402
from test_breakeven import CFG as BE_CFG, _CliRecorder, _tick as _be_tick  # noqa: E402
from test_breakeven import _pos as _be_pos  # noqa: E402
from test_partial_tp import CFG as PARTIAL_CFG, _Cli, _pos as _partial_pos, _tp_tick  # noqa: E402
from test_phase0_trailing_stop import _run_phase0_trailing_stop  # noqa: E402
from test_phase3_scoring import DEFAULT_CONFIG as P3_CFG, _run_phase3  # noqa: E402
from test_phase4_sizing import DEFAULT_CONFIG as P4_CFG, _run_phase4_sizing  # noqa: E402

DAY = 86400
NOW = 1_000_000 * DAY + 3600  # 1h après l'ouverture de la bougie 1d en cours


def _daily(closes, last_open=None):
    """Bougies 1d Kraken clôturées se terminant la veille de NOW ; last_open = bougie en cours en plus."""
    t0 = NOW // DAY * DAY - DAY * len(closes)
    rows = [[t0 + i * DAY, "1", "1", "1", str(c), "1", "1", 1] for i, c in enumerate(closes)]
    if last_open is not None:
        rows.append([NOW // DAY * DAY, "1", "1", "1", str(last_open), "1", "1", 1])
    return rows


class TestEmaAndFetchDailyTrend(unittest.TestCase):
    def test_ema_last_constant_series(self):
        self.assertAlmostEqual(ema_last([5.0] * 120, 100), 5.0)

    def test_ema_last_needs_n_values(self):
        self.assertIsNone(ema_last([1.0] * 99, 100))

    def test_ema_last_follows_trend(self):
        self.assertLess(ema_last(list(range(1, 201)), 100), 200)

    def test_current_candle_excluded(self):
        rows = _daily([100.0] * 120, last_open=1.0)
        with patch("core.trade_helpers.binance", return_value=json.dumps({"ETHUSDC": rows})):
            close, e = fetch_daily_trend("ETH", 100, now_ts=NOW)
        self.assertEqual(close, 100.0)
        self.assertAlmostEqual(e, 100.0)

    def test_kraken_failure_returns_none(self):
        with patch("core.trade_helpers.binance", side_effect=RuntimeError("kraken failed")):
            self.assertIsNone(fetch_daily_trend("ETH", 100, now_ts=NOW))

    def test_garbage_response_returns_none(self):
        with patch("core.trade_helpers.binance", return_value="not json"):
            self.assertIsNone(fetch_daily_trend("ETH", 100, now_ts=NOW))

    def test_not_enough_history_returns_none(self):
        with patch("core.trade_helpers.binance", return_value=json.dumps({"ETHUSDC": _daily([1.0] * 50)})):
            self.assertIsNone(fetch_daily_trend("ETH", 100, now_ts=NOW))

    def test_uses_kraken_ohlc_1440_and_other_key(self):
        raw = json.dumps({"XBTUSDC": _daily([100.0] * 120)})
        with patch("core.trade_helpers.binance", return_value=raw) as m:
            self.assertIsNotNone(fetch_daily_trend("BTC", 100, now_ts=NOW))
        self.assertEqual(m.call_args[0][:4], ("ohlc", "BTCUSDC", "--interval", "1440"))


def _trend_fn(table):
    """Doublure de fetch_daily_trend : table coin -> (close, ema) ou None (Kraken indisponible)."""
    calls = []

    def fn(coin, ema_days=100, now_ts=None):
        calls.append(coin)
        return table[coin]
    fn.calls = calls
    return fn


BUY = {"signal_4h": "STRONG_BUY", "signal_1d": "BUY", "rsi_4h": 45, "macd_bullish_4h": True, "volume_24h": 10}
P3_ON = dict(P3_CFG, trend_filter_enabled=True, trend_filter_ema_days=100)


def _p3(table, config=P3_ON, coin="ETH"):
    fn = _trend_fn(table)
    with patch("core.trade_helpers.fetch_daily_trend", side_effect=fn):
        out = _run_phase3({coin: dict(BUY)}, config=config)
    return out, fn


class TestPhase3TrendFilter(unittest.TestCase):
    def test_coin_and_btc_above_ema_buys(self):
        out, _ = _p3({"ETH": (110.0, 100.0), "BTC": (60000.0, 50000.0)})
        self.assertEqual(out["scores_detail"]["ETH"]["decision"], "BUY")
        self.assertEqual([c["coin"] for c in out["buy_candidates"]], ["ETH"])

    def test_coin_below_ema_is_skipped_type_a_with_figures(self):
        out, _ = _p3({"ETH": (90.0, 100.0), "BTC": (60000.0, 50000.0)})
        self.assertEqual(out["buy_candidates"], [])
        self.assertEqual(out["skip_coins_detail"]["ETH"]["skip_type"], "TYPE_A")
        detail = out["skip_coins_detail"]["ETH"]["skip_detail"]
        self.assertIn("ETH", detail)
        self.assertIn("EMA100", detail)
        self.assertIn("-10.0%", detail)
        self.assertEqual(out["scores_detail"]["ETH"]["decision"], "SKIP")

    def test_btc_below_ema_blocks_altcoin(self):
        out, _ = _p3({"ETH": (110.0, 100.0), "BTC": (40000.0, 50000.0)})
        self.assertEqual(out["buy_candidates"], [])
        self.assertIn("BTC", out["skip_coins_detail"]["ETH"]["skip_detail"])

    def test_kraken_unavailable_means_no_buy(self):
        out, _ = _p3({"ETH": None, "BTC": (60000.0, 50000.0)})
        self.assertEqual(out["buy_candidates"], [])
        self.assertEqual(out["skip_coins_detail"]["ETH"]["skip_type"], "TYPE_A")
        self.assertIn("indisponible", out["skip_coins_detail"]["ETH"]["skip_detail"])

    def test_btc_unavailable_means_no_buy(self):
        out, _ = _p3({"ETH": (110.0, 100.0), "BTC": None})
        self.assertEqual(out["buy_candidates"], [])
        self.assertIn("indisponible", out["skip_coins_detail"]["ETH"]["skip_detail"])

    def test_btc_is_checked_only_once(self):
        out, fn = _p3({"BTC": (60000.0, 50000.0)}, coin="BTC")
        self.assertEqual(fn.calls, ["BTC"])
        self.assertEqual(out["scores_detail"]["BTC"]["decision"], "BUY")

    def test_flag_off_means_no_kraken_call(self):
        out, fn = _p3({}, config=dict(P3_ON, trend_filter_enabled=False))
        self.assertEqual(fn.calls, [])
        self.assertEqual(out["scores_detail"]["ETH"]["decision"], "BUY")

    def test_flag_absent_defaults_to_off(self):
        out, fn = _p3({}, config=P3_CFG)
        self.assertEqual(fn.calls, [])
        self.assertEqual(out["scores_detail"]["ETH"]["decision"], "BUY")

    def test_config_json_enables_new_rules(self):
        with open(os.path.join(PROJECT_DIR, "config.json")) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["stop_mode"], "fixed")
        self.assertEqual(cfg["fixed_stop_pct"], 0.20)
        self.assertTrue(cfg["trend_filter_enabled"])
        self.assertEqual(cfg["trend_filter_ema_days"], 100)


class TestPhase4FixedStop(unittest.TestCase):
    CAND = [{"coin": "ETH", "prix_actuel": 1000, "atr_pct": 0.05, "score": 8}]
    FIXED = dict(P4_CFG, stop_mode="fixed", fixed_stop_pct=0.20, risk_per_trade_pct=0.02, fee_round_trip_pct=0.009,
                 max_stop_distance_pct=0.12, max_tp_pct=0.06, reward_risk_ratio=1.5, max_single_position_pct=0.65)

    def test_fixed_stop_ignores_atr_and_sizes_at_constant_risk(self):
        out, _ = _run_phase4_sizing(self.CAND, portfolio_total=380, budget_disponible=380, config=self.FIXED)
        self.assertEqual(out["skipped"], [])
        o = out["ordres_prepares"][0]
        self.assertAlmostEqual(o["stop_distance_pct"], 0.20)
        self.assertAlmostEqual(o["prix_stop"], 800.0)
        # risque 2 % de 380 = 7.6 ; montant = 7.6 / (0.20 + 0.009) ~ 36.4 USDC
        self.assertAlmostEqual(o["montant_ordre"], 7.6 / 0.209, places=2)
        self.assertAlmostEqual(o["risk_usdc"], 7.6)
        self.assertAlmostEqual(o["prix_tp"], 1060.0)  # plafond max_tp_pct, pas la cible mécanique (+32 %)

    def test_max_stop_distance_not_applied_in_fixed_mode(self):
        out, _ = _run_phase4_sizing(self.CAND, portfolio_total=380, budget_disponible=380, config=self.FIXED)
        self.assertEqual(len(out["ordres_prepares"]), 1)

    def test_atr_mode_still_available_and_still_capped(self):
        cfg = dict(self.FIXED, stop_mode="atr", atr_stop_multiplier=3)
        out, _ = _run_phase4_sizing(self.CAND, portfolio_total=380, budget_disponible=380, config=cfg)
        self.assertEqual(out["ordres_prepares"], [])  # 0.05 x 3 = 15 % > plafond 12 %
        self.assertIn("plafond 12.0%", out["skipped"][0]["reason"])

    def test_stop_mode_absent_defaults_to_atr(self):
        cfg = {k: v for k, v in self.FIXED.items() if k not in ("stop_mode", "fixed_stop_pct")}
        cfg["atr_stop_multiplier"] = 2
        out, _ = _run_phase4_sizing(self.CAND, portfolio_total=380, budget_disponible=380, config=cfg)
        self.assertAlmostEqual(out["ordres_prepares"][0]["stop_distance_pct"], 0.10)

    def test_small_account_below_min_order_is_skipped(self):
        out, _ = _run_phase4_sizing(self.CAND, portfolio_total=80, budget_disponible=80, config=self.FIXED)
        self.assertEqual(out["ordres_prepares"], [])  # 1.6 / 0.209 = 7.7 USDC < 9
        self.assertIn("< seuil", out["skipped"][0]["reason"])


class TestExistingMechanicsWithWideStop(unittest.TestCase):
    """Position de ~36 USDC, stop d'origine -20 % : break-even, partiel, cible, stop suiveur."""

    ENTRY, QTY, RISK = 1000.0, 0.036, 0.036 * 1000.0 * 0.209

    def test_initial_stop_reconstructed_from_risk(self):
        t = {"entry_price": self.ENTRY, "quantity": self.QTY, "risk_usdc": self.RISK, "stop_price": 1009.0}
        self.assertAlmostEqual(initial_stop_price(t), 800.0)

    def test_target_is_capped_not_mechanical(self):
        self.assertAlmostEqual(compute_tp_target(self.ENTRY, 0.20, 1.5, 0.009, 0.06, None), 1060.0)

    def test_breakeven_moves_stop_from_minus_20_to_entry_plus_fees(self):
        pos = _be_pos(quantity=self.QTY, stop_price=800.0, risk_usdc=self.RISK)
        cli = _CliRecorder(1016.0)
        _be_tick([pos], cli, cfg=BE_CFG)
        self.assertAlmostEqual(pos["stop_price"], 1009.0)
        self.assertTrue(pos["breakeven_applied"])
        self.assertAlmostEqual(pos["initial_stop_price"], 800.0)

    def test_partial_taken_on_36_usdc_position(self):
        pos = _partial_pos(quantity=self.QTY, stop_price=1009.0, breakeven_applied=True, risk_usdc=self.RISK)
        cli = _Cli(price=1031.0)
        pend, _, _ = _tp_tick([pos], cli)
        self.assertEqual(len(pend), 1)  # 1/3 ~ 12 USDC > min_order_usdc 9
        self.assertTrue(pos["partial_tp_done"])
        self.assertNotIn("partial_tp_skipped", pos)

    def test_partial_skipped_when_fraction_below_min_order(self):
        pos = _partial_pos(quantity=0.024, stop_price=1009.0, breakeven_applied=True, risk_usdc=0.024 * 209)
        cli = _Cli(price=1031.0)
        pend, _, _ = _tp_tick([pos], cli)  # 1/3 de 24 USDC ~ 8 USDC < 9
        self.assertIsNone(pend)
        self.assertEqual(pos["partial_tp_skipped"], "below_min")
        self.assertFalse(cli.sells("limit"))

    def test_trailing_stays_inactive_with_20_pct_distance(self):
        # Après break-even (stop 1009), prix = cible +6 % : price - 200 = 860 < 1009 -> aucun mouvement
        history = [{"trade_id": "T1", "coin": "ETH", "status": "open", "sl_order_txid": "SLTX1",
                    "entry_price": 1000, "stop_price": 1009, "quantity": self.QTY,
                    "initial_stop_price": 800, "breakeven_applied": True}]
        scenario = {
            "ticker": {"ETHUSDC": {"c": ["1060.0", "0.01"]}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"}},
            "order_sell_ETHUSDC": {"txid": ["NEWSLTX"]},
        }
        output, _, _, saved = _run_phase0_trailing_stop(history, scenario)
        self.assertEqual(output["updated"], 0)


if __name__ == "__main__":
    unittest.main()
