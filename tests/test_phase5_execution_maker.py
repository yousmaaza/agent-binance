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
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE5_EXECUTION_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase5_execution.py")

MAKER_CONFIG = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 2, "fee_round_trip_pct": 0,
                 "maker_entry_enabled": True, "maker_max_concession_pct": 0.003}

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
    out_path = f"/tmp/cycle_{cycle_id}_phase5_output.json"
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

        # Un ordre POSÉ n'est pas un ordre EXÉCUTÉ (#397) : executed reste à 0 tant qu'aucun achat
        # n'a eu lieu, l'ordre en attente est compté à part dans "pending".
        self.assertEqual(output["executed"], 0)
        self.assertEqual(output["pending"], 1)
        self.assertEqual(output["skipped"], 0)
        placed = output["orders_executed"][0]
        self.assertEqual(placed["coin"], "ETH")
        self.assertEqual(placed["entry_order_id"], "MAKERTX1")
        self.assertTrue(placed["maker_pending"])
        self.assertAlmostEqual(placed["maker_limit_price"], 1999.5)

        mock_save.assert_not_called()  # pas de position tant que l'ordre n'est pas rempli
        mock_save_pending.assert_called_once()
        self.assertEqual(len(saved_pending), 1)
        pending_entry = saved_pending[0]
        self.assertEqual(pending_entry["coin"], "ETH")
        self.assertEqual(pending_entry["pair"], "ETHUSDC")
        self.assertEqual(pending_entry["txid"], "MAKERTX1")
        self.assertAlmostEqual(pending_entry["quantity"], 0.1)
        self.assertAlmostEqual(pending_entry["scan_price"], 2000.0)
        self.assertAlmostEqual(pending_entry["initial_limit_price"], 1999.5)
        self.assertAlmostEqual(pending_entry["current_limit_price"], 1999.5)
        # fee_round_trip_pct posé sur l'ordre pending pour un TP net de frais cohérent au fill (#411)
        self.assertAlmostEqual(pending_entry["fee_round_trip_pct"], 0)


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
        self.assertEqual(output["pending"], 0)
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
        config = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 2, "fee_round_trip_pct": 0,
                   "maker_entry_enabled": False}
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
        self.assertEqual(output["pending"], 0)
        executed = output["orders_executed"][0]
        self.assertNotIn("maker_pending", executed)
        self.assertEqual(executed["entry_order_id"], "BUYTX1")
        mock_save.assert_called_once()
        self.assertEqual(saved_history[0]["maker_or_taker"], "taker")
        mock_save_pending.assert_not_called()


class TestMixedCycleCountsFilledAndPendingSeparately(unittest.TestCase):
    """Un cycle qui remplit un ordre (repli marché) ET pose un ordre maker en attente doit
    refléter les deux sans les confondre : executed=1, pending=1 (#397)."""

    def test_one_filled_via_market_fallback_and_one_still_pending_maker(self):
        eth_order = dict(BASE_ORDER, coin="ETH", score=9)
        sol_order = dict(BASE_ORDER, coin="SOL", score=5, prix_entry=100.0, quantite=2.0,
                          montant_ordre=200.0)
        kraken_scenario = {
            "ticker": {
                "ETHUSDC": {"c": ["2000.0", "0.01"], "b": ["1999.5", "0.01"]},
                "SOLUSDC": {"c": ["100.0", "0.01"], "b": ["99.9", "0.01"]},
            },
            "balance": {"USDC": "500.0"},
            # ETH : pose post-only rejetée (pas de order_buy_ETHUSDC_limit) -> repli marché rempli
            "order_buy_ETHUSDC_market": {"txid": ["MARKETTX1"]},
            "query-orders_MARKETTX1": {"MARKETTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1", "fee": "0.3"}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["SLTX1"]},
            # SOL : pose post-only réussie -> reste en attente
            "order_buy_SOLUSDC_limit": {"txid": ["MAKERTX2"]},
        }
        output, _mock_tg, mock_save, saved_history, mock_save_pending, saved_pending = _run_phase5_execution(
            [eth_order, sol_order], kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["executed"], 1)
        self.assertEqual(output["pending"], 1)
        self.assertEqual(output["skipped"], 0)

        filled = [o for o in output["orders_executed"] if not o.get("maker_pending")]
        pending_placed = [o for o in output["orders_executed"] if o.get("maker_pending")]
        self.assertEqual(len(filled), 1)
        self.assertEqual(len(pending_placed), 1)
        self.assertEqual(filled[0]["coin"], "ETH")
        self.assertEqual(pending_placed[0]["coin"], "SOL")

        mock_save.assert_called_once()
        self.assertEqual(saved_history[0]["coin"], "ETH")
        self.assertEqual(saved_history[0]["maker_or_taker"], "taker")

        mock_save_pending.assert_called_once()
        self.assertEqual(len(saved_pending), 1)
        self.assertEqual(saved_pending[0]["coin"], "SOL")
        self.assertEqual(saved_pending[0]["txid"], "MAKERTX2")


if __name__ == "__main__":
    unittest.main()
