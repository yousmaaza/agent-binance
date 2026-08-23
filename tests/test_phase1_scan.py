"""Tests d'intégration pour phase1_scan.py — univers USDC + filtre volume/spread/persistance
+ mapping TV.

Même approche que test_phase3_scoring.py : import direct du script top-level via
importlib, appel réel au stub fake_kraken.py (core.trade_helpers._EXCHANGE_CLI), config
mockée via core.trade_helpers._load_config. tg() mockée par précaution (le script ne
l'appelle pas aujourd'hui, mais aucun risque de vrai curl si ça change).

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness

PHASE1_SCAN_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase1_scan.py")

DEFAULT_CONFIG = {"min_volume_usdc": 1_000_000, "portfolio_coins": []}


def _ticker(price, vol_base, ask=None, bid=None):
    """Construit une entrée kraken ticker (c/v/a/b) — spread tight par défaut (~0.02%)."""
    ask = ask if ask is not None else price * 1.0002
    bid = bid if bid is not None else price
    return {"c": [str(price), "1"], "v": ["0", str(vol_base)], "a": [str(ask), "1", "1"], "b": [str(bid), "1", "1"]}


def _persistent_candles(price, periods=6, per_period_usdc=200_000):
    """6 périodes OHLC qui tiennent chacune le seuil (1M/6 ≈ 166 667 USDC) — volume soutenu."""
    vol_base = per_period_usdc / price
    return [[1690000000 + i * 14400, str(price), str(price), str(price), str(price), str(price), str(vol_base), 100]
            for i in range(periods)]


def _spiky_candles(price, periods=6, spike_period_usdc=600_000, base_period_usdc=20_000):
    """5 périodes sous le seuil + 1 pic — reproduit le pattern TRUMP (x27 en une nuit)."""
    candles = []
    for i in range(periods):
        usdc = spike_period_usdc if i == periods - 1 else base_period_usdc
        vol_base = usdc / price
        candles.append([1690000000 + i * 14400, str(price), str(price), str(price), str(price), str(price),
                         str(vol_base), 100])
    return candles


def _run_phase1_scan(pairs_data, ticker_data, config=None, ohlc_data=None):
    """Exécute phase1_scan.py sur un scénario donné. Retourne (output_json, mock_tg)."""
    cycle_id = harness.new_cycle_id()
    scenario = {"pairs": pairs_data, "ticker": ticker_data, "ohlc": ohlc_data or {}}
    scenario_path = harness.write_kraken_scenario(scenario)
    out_path = f"/tmp/cycle_{cycle_id}_phase1_output.json"
    cfg = config if config is not None else DEFAULT_CONFIG

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            stack.enter_context(patch("core.trade_helpers._load_config", return_value=cfg))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))

            harness.exec_phase_script(PHASE1_SCAN_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        return output, mock_tg
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(scenario_path, out_path)


class TestVolumeFilter(unittest.TestCase):
    """Filtre min_volume_usdc : coin sous le seuil exclu, coin au-dessus inclus."""

    def test_low_volume_coin_excluded_high_volume_included(self):
        pairs_data = {"SOLUSDC": {}, "LOWUSDC": {}}
        ticker_data = {
            "SOLUSDC": _ticker(100.0, 20000),  # 20000*100 = 2M >= seuil
            "LOWUSDC": _ticker(10.0, 100),      # 100*10 = 1000 < seuil
        }
        ohlc_data = {"SOLUSDC": _persistent_candles(100.0)}
        output, _ = _run_phase1_scan(pairs_data, ticker_data, DEFAULT_CONFIG, ohlc_data)

        tradable = {c["coin"]: c for c in output["tradable"]}
        self.assertIn("SOL", tradable)
        self.assertEqual(tradable["SOL"]["tv_symbol"], "SOL")
        self.assertNotIn("LOW", tradable)

        non_tradable = {c["coin"]: c["reason"] for c in output["non_tradable"]}
        self.assertIn("LOW", non_tradable)
        self.assertIn("volume", non_tradable["LOW"])


class TestSpreadFilter(unittest.TestCase):
    """Filtre max_spread_pct : spread trop large exclu même à volume suffisant (cf. TRUMP, 0,126 %)."""

    def test_wide_spread_excluded_narrow_spread_included(self):
        pairs_data = {"WIDEUSDC": {}, "OKUSDC": {}}
        ticker_data = {
            # 20000*100 = 2M >= seuil, spread (100.13-100)/100.13 ≈ 0,13 % > 0,05 % défaut
            "WIDEUSDC": _ticker(100.0, 20000, ask=100.13, bid=100.0),
            "OKUSDC": _ticker(100.0, 20000, ask=100.01, bid=100.0),  # spread ≈ 0,01 %
        }
        ohlc_data = {"OKUSDC": _persistent_candles(100.0)}
        output, _ = _run_phase1_scan(pairs_data, ticker_data, DEFAULT_CONFIG, ohlc_data)

        tradable_coins = [c["coin"] for c in output["tradable"]]
        self.assertIn("OK", tradable_coins)
        self.assertNotIn("WIDE", tradable_coins)

        non_tradable = {c["coin"]: c["reason"] for c in output["non_tradable"]}
        self.assertIn("spread", non_tradable["WIDE"])


class TestVolumePersistenceFilter(unittest.TestCase):
    """Filtre volume_persistence_periods : pic de volume isolé exclu, volume soutenu inclus."""

    def test_volume_spike_excluded_sustained_volume_included(self):
        pairs_data = {"SPIKEUSDC": {}, "STABLEUSDC": {}}
        ticker_data = {
            "SPIKEUSDC": _ticker(1.0, 2_000_000),   # vol 24h = 2M, spread tight -> passe volume+spread
            "STABLEUSDC": _ticker(1.0, 2_000_000),
        }
        ohlc_data = {
            "SPIKEUSDC": _spiky_candles(1.0),        # 5 périodes basses + 1 pic (pattern TRUMP)
            "STABLEUSDC": _persistent_candles(1.0),  # 6 périodes qui tiennent le seuil
        }
        output, _ = _run_phase1_scan(pairs_data, ticker_data, DEFAULT_CONFIG, ohlc_data)

        tradable_coins = [c["coin"] for c in output["tradable"]]
        self.assertIn("STABLE", tradable_coins)
        self.assertNotIn("SPIKE", tradable_coins)

        non_tradable = {c["coin"]: c["reason"] for c in output["non_tradable"]}
        self.assertIn("pic isolé", non_tradable["SPIKE"])


class TestPortfolioCoinsAlwaysIncluded(unittest.TestCase):
    """portfolio_coins reste dans l'univers même sous le seuil de volume, spread large ou pic isolé."""

    def test_portfolio_coin_included_despite_low_volume_and_wide_spread(self):
        pairs_data = {"SUIUSDC": {}}
        # vol 50*1 = 50 << seuil, spread (1.2-1.0)/1.2 ≈ 17 % >> 0,05 % défaut
        ticker_data = {"SUIUSDC": _ticker(1.0, 50, ask=1.2, bid=1.0)}
        config = {"min_volume_usdc": 1_000_000, "portfolio_coins": ["SUI"]}
        output, _ = _run_phase1_scan(pairs_data, ticker_data, config)

        tradable_coins = [c["coin"] for c in output["tradable"]]
        self.assertIn("SUI", tradable_coins)
        self.assertEqual(output["non_tradable"], [])


class TestKrakenToTradingViewMapping(unittest.TestCase):
    """XBT -> BTC et XDG -> DOGE dans tv_symbol, coin non mappé -> lui-même."""

    def test_xbt_and_xdg_mapped_to_tv_symbols(self):
        pairs_data = {"XBTUSDC": {}, "XDGUSDC": {}}
        ticker_data = {
            "XBTUSDC": _ticker(60000.0, 50),   # 50*60000 = 3M >= seuil
            "XDGUSDC": _ticker(0.2, 6000000),  # 6M*0.2 = 1.2M >= seuil
        }
        ohlc_data = {
            "XBTUSDC": _persistent_candles(60000.0),
            "XDGUSDC": _persistent_candles(0.2),
        }
        output, _ = _run_phase1_scan(pairs_data, ticker_data, DEFAULT_CONFIG, ohlc_data)

        tv_symbols = {c["coin"]: c["tv_symbol"] for c in output["tradable"]}
        self.assertEqual(tv_symbols["XBT"], "BTC")
        self.assertEqual(tv_symbols["XDG"], "DOGE")


if __name__ == "__main__":
    unittest.main()
