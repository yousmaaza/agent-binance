"""Tests d'intégration pour phase1_scan.py — univers USDC + filtre volume + mapping TV.

Même approche que test_phase3_scoring.py : import direct du script top-level via
importlib, appel réel au stub fake_kraken.py (core.trade_helpers._EXCHANGE_CLI), config
mockée via core.trade_helpers._load_config. tg() mockée par précaution (le script ne
l'appelle pas aujourd'hui, mais aucun risque de vrai curl si ça change).
"""
import contextlib
import importlib.util
import json
import os
import sys
import unittest
import uuid
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

PHASE1_SCAN_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase1_scan.py")
FAKE_KRAKEN_PATH = os.path.join(PROJECT_DIR, "tests", "fixtures", "fake_kraken.py")

DEFAULT_CONFIG = {"min_volume_usdc": 1_000_000, "portfolio_coins": []}


def _run_phase1_scan(pairs_data, ticker_data, config=None):
    """Exécute phase1_scan.py sur un scénario donné. Retourne (output_json, mock_tg)."""
    cycle_id = f"test_{uuid.uuid4().hex[:12]}"
    scenario_path = f"/tmp/fake_kraken_scenario_{cycle_id}.json"
    with open(scenario_path, "w") as f:
        json.dump({"pairs": pairs_data, "ticker": ticker_data}, f)

    out_path = f"/tmp/cycle_{cycle_id}_phase1_output.json"
    cfg = config if config is not None else DEFAULT_CONFIG

    old_argv = sys.argv
    old_env = os.environ.get("FAKE_KRAKEN_SCENARIO")
    sys.argv = ["phase1_scan.py", cycle_id]
    os.environ["FAKE_KRAKEN_SCENARIO"] = scenario_path
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            stack.enter_context(patch("core.trade_helpers._load_config", return_value=cfg))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", FAKE_KRAKEN_PATH))

            spec = importlib.util.spec_from_file_location(f"phase1_scan_{cycle_id}", PHASE1_SCAN_PATH)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

        output = None
        if os.path.exists(out_path):
            with open(out_path) as f:
                output = json.load(f)
        return output, mock_tg
    finally:
        sys.argv = old_argv
        if old_env is None:
            os.environ.pop("FAKE_KRAKEN_SCENARIO", None)
        else:
            os.environ["FAKE_KRAKEN_SCENARIO"] = old_env
        for p in (scenario_path, out_path):
            if os.path.exists(p):
                os.remove(p)


class TestVolumeFilter(unittest.TestCase):
    """Filtre min_volume_usdc : coin sous le seuil exclu, coin au-dessus inclus."""

    def test_low_volume_coin_excluded_high_volume_included(self):
        pairs_data = {"SOLUSDC": {}, "LOWUSDC": {}}
        ticker_data = {
            "SOLUSDC": {"c": ["100.0", "1"], "v": ["1000", "20000"]},  # 20000*100 = 2M >= seuil
            "LOWUSDC": {"c": ["10.0", "1"], "v": ["50", "100"]},        # 100*10 = 1000 < seuil
        }
        output, _ = _run_phase1_scan(pairs_data, ticker_data, DEFAULT_CONFIG)

        tradable = {c["coin"]: c for c in output["tradable"]}
        self.assertIn("SOL", tradable)
        self.assertEqual(tradable["SOL"]["tv_symbol"], "SOL")
        self.assertNotIn("LOW", tradable)

        non_tradable = {c["coin"]: c["reason"] for c in output["non_tradable"]}
        self.assertIn("LOW", non_tradable)
        self.assertIn("volume", non_tradable["LOW"])


class TestPortfolioCoinsAlwaysIncluded(unittest.TestCase):
    """portfolio_coins reste dans l'univers même sous le seuil de volume."""

    def test_portfolio_coin_included_despite_low_volume(self):
        pairs_data = {"SUIUSDC": {}}
        ticker_data = {"SUIUSDC": {"c": ["1.0", "1"], "v": ["10", "50"]}}  # 50*1 = 50 << seuil
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
            "XBTUSDC": {"c": ["60000.0", "1"], "v": ["100", "50"]},   # 50*60000 = 3M >= seuil
            "XDGUSDC": {"c": ["0.2", "1"], "v": ["1000000", "6000000"]},  # 6M*0.2 = 1.2M >= seuil
        }
        output, _ = _run_phase1_scan(pairs_data, ticker_data, DEFAULT_CONFIG)

        tv_symbols = {c["coin"]: c["tv_symbol"] for c in output["tradable"]}
        self.assertEqual(tv_symbols["XBT"], "BTC")
        self.assertEqual(tv_symbols["XDG"], "DOGE")


if __name__ == "__main__":
    unittest.main()
