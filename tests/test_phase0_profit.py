"""Tests d'intégration pour phase0_profit.py — clôture auto si profit > min_profit_pct_take.

Même approche que test_phase0_snapshot.py : trade_history.json intercepté via un patch de
builtins.open ciblé, _save_trade_history_atomic et _load_config mockés (jamais le vrai
config.json ni le vrai trade_history.json), tg() mockée, binance() redirigée vers le stub
fake_kraken.py via core.trade_helpers._EXCHANGE_CLI.

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import json
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE0_PROFIT_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase0_profit.py")


def _run_phase0_profit(history_data, config=None, kraken_scenario=None):
    """Exécute phase0_profit.py. Retourne (output_json, mock_tg, mock_save)."""
    cycle_id = harness.new_cycle_id()
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    out_path = f"/tmp/cycle_{cycle_id}_phase0_profit_output.json"
    text = json.dumps(history_data)
    cfg = config if config is not None else {"min_profit_pct_take": 5.0}

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(patch("core.trade_helpers._load_config", return_value=cfg))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))

            harness.exec_phase_script(PHASE0_PROFIT_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        return output, mock_tg, mock_save
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(scenario_path, out_path)


class TestProfitTargetClosesPosition(unittest.TestCase):
    """Profit latent >= min_profit_pct_take -> position fermée au marché."""

    def test_position_closed_when_profit_above_threshold(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1"},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1100.0", "0.01"]}},  # +10% > seuil 5%
            "order_sell_ETHUSDC": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "1100.0", "vol_exec": "1.0"}},
        }
        output, mock_tg, mock_save = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0}, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        mock_save.assert_called()
        saved_history = mock_save.call_args[0][0]
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["close_reason"], "profit_target_phase0")
        self.assertAlmostEqual(pos["exit_price"], 1100.0)
        self.assertAlmostEqual(pos["pnl_usdc"], 100.0)
        mock_tg.assert_called()


class TestProfitBelowThresholdNoAction(unittest.TestCase):
    def test_position_untouched_when_profit_below_threshold(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1"},
        ]
        kraken_scenario = {"ticker": {"ETHUSDC": {"c": ["1020.0", "0.01"]}}}  # +2% < seuil 5%
        output, mock_tg, mock_save = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0}, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        mock_save.assert_not_called()
        mock_tg.assert_not_called()


class TestProfitMissingEntryOrQty(unittest.TestCase):
    """Cas limite documenté dans le code : entry_price ou quantity absent/nul -> position ignorée."""

    def test_position_skipped_when_entry_price_missing(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "0",
             "quantity": "1"},
        ]
        output, _, mock_save = _run_phase0_profit(history_data, kraken_scenario={})

        self.assertEqual(output["closed"], 0)
        mock_save.assert_not_called()


class TestProfitSellOrderNoTxid(unittest.TestCase):
    """Cas limite : l'ordre SELL market ne renvoie pas de txid -> position reste ouverte, pas de crash."""

    def test_position_stays_open_when_sell_order_returns_no_txid(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1"},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1100.0", "0.01"]}},
            # pas de clé order_sell_ETHUSDC -> fake_kraken renvoie {} -> pas de txid
        }
        output, _, mock_save = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0}, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        mock_save.assert_not_called()
        self.assertEqual(history_data[0]["status"], "open")


if __name__ == "__main__":
    unittest.main()
