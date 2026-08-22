"""Tests d'intégration pour la branche maker_entry_enabled de phase5_execution.py (#388).

Même harness que tests/test_phase5_execution.py : trade_history.json intercepté via un patch de
builtins.open ciblé, tg()/_save_trade_history_atomic mockées, binance() redirigée vers le stub
fake_kraken.py. load_maker_pending_orders/save_maker_pending_orders sont mockées séparément
(state/maker_pending_orders.json n'est jamais touché).

fake_kraken.py distingue order_buy_<PAIR>_limit (pose LIMIT post-only) de order_buy_<PAIR>_market
(repli BUY MARKET) sur le même pair — voir tests/fixtures/fake_kraken.py.
"""
import contextlib
import json
import os
import sys
import unittest
import tempfile
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE5_EXECUTION_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase5_execution.py")

MAKER_CONFIG = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 2, "maker_entry_enabled": True,
                 "maker_max_concession_pct": 0.003}

BASE_ORDER = {
    "coin": "ETH",
    "quantite": 0.1,
    "prix_entry": 2000.0,
    "prix_stop": 1900.0,
    "prix_tp": 2200.0,
    "montant_ordre": 200.0,
    "risk_usdc": 20.0,
    "stop_distance_pct": 0.05,
    "score": 8,
}


def _run_phase5_execution(ordres_prepares, config=None, kraken_scenario=None, history_data=None,
                           pending_orders=None):
    """Exécute phase5_execution.py avec maker_entry_enabled. Retourne (output_json, mock_tg,
    mock_save_trade_history, saved_history, mock_save_pending, saved_pending)."""
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase5_input.json"
    fd_out, out_path = tempfile.mkstemp(prefix=f"cycle_{cycle_id}_phase5_output_", suffix=".json")
    os.close(fd_out)
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    text = json.dumps(history_data if history_data is not None else [])

    input_data = {
        "ordres_prepares": ordres_prepares,
        "config": config if config is not None else MAKER_CONFIG,
    }
    with open(in_path, "w") as f:
        json.dump(input_data, f)

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(
                patch("core.trade_helpers.load_maker_pending_orders", return_value=pending_orders or []),
            )
            mock_save_pending = stack.enter_context(patch("core.trade_helpers.save_maker_pending_orders"))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))

            harness.exec_phase_script(PHASE5_EXECUTION_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        saved_history = mock_save.call_args[0][0] if mock_save.call_args else None
        saved_pending = mock_save_pending.call_args[0][0] if mock_save_pending.call_args else None
        return output, mock_tg, mock_save, saved_history, mock_save_pending, saved_pending
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(in_path, out_path, scenario_path)


class TestMakerEntryPlacesPostOnlyLimitAndDefersToWatcher(unittest.TestCase):
    """maker_entry_enabled=True, pose réussie -> ordre enregistré en pending, pas de position
    ouverte tout de suite (elle sera créée par maker_watcher.py au fill)."""

    def test_post_only_limit_placed_and_registered_pending_no_trade_history_write(self):
        order = dict(BASE_ORDER)
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["2000.0", "0.01"], "b": ["1999.5", "0.01"]}},
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC_limit": {"txid": ["MAKERTX1"]},
        }
        output, _mock_tg, mock_save, _saved_history, mock_save_pending, saved_pending = _run_phase5_execution(
            [order], kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["executed"], 1)
        self.assertEqual(output["skipped"], 0)
        executed = output["orders_executed"][0]
        self.assertEqual(executed["coin"], "ETH")
        self.assertEqual(executed["entry_order_id"], "MAKERTX1")
        self.assertTrue(executed["maker_pending"])
        self.assertAlmostEqual(executed["maker_limit_price"], 1999.5)

        mock_save.assert_not_called()  # pas de position tant que l'ordre n'est pas rempli
        mock_save_pending.assert_called_once()
        self.assertEqual(len(saved_pending), 1)
        pending = saved_pending[0]
        self.assertEqual(pending["coin"], "ETH")
        self.assertEqual(pending["pair"], "ETHUSDC")
        self.assertEqual(pending["txid"], "MAKERTX1")
        self.assertAlmostEqual(pending["quantity"], 0.1)
        self.assertAlmostEqual(pending["scan_price"], 2000.0)
        self.assertAlmostEqual(pending["initial_limit_price"], 1999.5)
        self.assertAlmostEqual(pending["current_limit_price"], 1999.5)


class TestMakerEntryFallsBackToMarketAfterRepeatedPostOnlyRejection(unittest.TestCase):
    """Pose post-only rejetée à chaque tentative (3) -> repli immédiat sur BUY MARKET legacy."""

    def test_post_only_rejected_three_times_falls_back_to_legacy_market_buy(self):
        order = dict(BASE_ORDER)
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["2000.0", "0.01"], "b": ["1999.5", "0.01"]}},
            "balance": {"USDC": "500.0"},
            # order_buy_ETHUSDC_limit absent -> réponse {} -> pas de txid -> rejet à chaque tentative
            "order_buy_ETHUSDC_market": {"txid": ["MARKETTX1"]},
            "query-orders_MARKETTX1": {"MARKETTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1", "fee": "0.3"}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["SLTX1"]},
        }
        output, _mock_tg, mock_save, saved_history, mock_save_pending, _saved_pending = _run_phase5_execution(
            [order], kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["executed"], 1)
        executed = output["orders_executed"][0]
        self.assertNotIn("maker_pending", executed)
        self.assertEqual(executed["entry_order_id"], "MARKETTX1")

        mock_save.assert_called_once()
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["maker_or_taker"], "taker")
        self.assertEqual(pos["sl_order_txid"], "SLTX1")
        mock_save_pending.assert_not_called()  # jamais rien à persister, la pose n'a jamais abouti


class TestMakerEntryDisabledKeepsLegacyBehaviorUnchanged(unittest.TestCase):
    """maker_entry_enabled=False -> comportement identique à l'ancien flux BUY MARKET."""

    def test_maker_entry_disabled_uses_market_buy_directly_without_pending_placement(self):
        order = dict(BASE_ORDER)
        config = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 2, "maker_entry_enabled": False}
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["2000.0", "0.01"]}},
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1"}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC": {"txid": ["SLTX1"]},
        }
        output, _mock_tg, mock_save, saved_history, mock_save_pending, _saved_pending = _run_phase5_execution(
            [order], config=config, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["executed"], 1)
        executed = output["orders_executed"][0]
        self.assertNotIn("maker_pending", executed)
        self.assertEqual(executed["entry_order_id"], "BUYTX1")
        mock_save.assert_called_once()
        self.assertEqual(saved_history[0]["maker_or_taker"], "taker")
        mock_save_pending.assert_not_called()


if __name__ == "__main__":
    unittest.main()
