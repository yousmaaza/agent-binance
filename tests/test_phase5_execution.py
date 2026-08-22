"""Tests d'intégration pour phase5_execution.py — drift check, BUY MARKET, fill, TP/SL (post #364).

Même approche que test_phase0_profit.py : trade_history.json intercepté via un patch de
builtins.open ciblé, _save_trade_history_atomic et tg() mockées (jamais le vrai fichier ni un
vrai curl), binance() redirigée vers le stub fake_kraken.py via core.trade_helpers._EXCHANGE_CLI.
Le champ "config" de l'input est fourni tel quel (phase5_execution.py utilise inp["config"] en
priorité sur _load_config()).

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

PHASE5_EXECUTION_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase5_execution.py")

DEFAULT_CONFIG = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 2}

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


def _run_phase5_execution(ordres_prepares, config=None, kraken_scenario=None, history_data=None):
    """Exécute phase5_execution.py. Retourne (output_json, mock_tg, mock_save, saved_history)."""
    cycle_id = harness.new_cycle_id()
    in_path = os.path.join(PROJECT_DIR, "state", f"cycle_{cycle_id}_phase5_input.json")
    out_path = os.path.join(PROJECT_DIR, "state", f"cycle_{cycle_id}_phase5_output.json")
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    text = json.dumps(history_data if history_data is not None else [])

    input_data = {
        "ordres_prepares": ordres_prepares,
        "config": config if config is not None else DEFAULT_CONFIG,
    }
    with open(in_path, "w") as f:
        json.dump(input_data, f)

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))

            harness.exec_phase_script(PHASE5_EXECUTION_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        saved_history = mock_save.call_args[0][0] if mock_save.call_args else None
        return output, mock_tg, mock_save, saved_history
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(in_path, out_path, scenario_path)


class TestSkipTypeCOnPriceDrift(unittest.TestCase):
    """Drift entre prix_entry (Phase 4) et prix re-fetché > price_deviation_max_pct -> skip TYPE_C."""

    def test_order_skipped_when_price_drift_exceeds_threshold(self):
        order = dict(BASE_ORDER)
        kraken_scenario = {"ticker": {"ETHUSDC": {"c": ["2200.0", "0.01"]}}}  # drift = 10% > 2%
        output, _mock_tg, mock_save, _ = _run_phase5_execution([order], kraken_scenario=kraken_scenario)

        self.assertEqual(output["executed"], 0)
        self.assertEqual(output["skipped"], 1)
        self.assertEqual(output["orders_skipped_detail"]["ETH"]["skip_type"], "TYPE_C")
        self.assertIn("Drift", output["orders_skipped_detail"]["ETH"]["skip_detail"])
        mock_save.assert_not_called()


class TestSkipTypeCOnInsufficientBalance(unittest.TestCase):
    """Solde USDC re-fetché insuffisant pour montant_ordre -> skip TYPE_C."""

    def test_order_skipped_when_usdc_balance_insufficient(self):
        order = dict(BASE_ORDER)
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["2000.0", "0.01"]}},  # drift nul
            "balance": {"USDC": "5.0"},  # < montant_ordre 200
        }
        output, _mock_tg, mock_save, _ = _run_phase5_execution([order], kraken_scenario=kraken_scenario)

        self.assertEqual(output["executed"], 0)
        self.assertEqual(output["skipped"], 1)
        self.assertEqual(output["orders_skipped_detail"]["ETH"]["skip_type"], "TYPE_C")
        self.assertIn("Solde USDC insuffisant", output["orders_skipped_detail"]["ETH"]["skip_detail"])
        mock_save.assert_not_called()


class TestNominalBuyAndStopLossSucceed(unittest.TestCase):
    """BUY MARKET rempli + pose du SL réussie -> position enregistrée, protection_failed=False."""

    def test_buy_filled_and_stop_loss_placed(self):
        order = dict(BASE_ORDER)
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["2000.0", "0.01"]}},  # drift nul, prix post-fill sous le TP
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1"}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC": {"txid": ["SLTX1"]},
        }
        output, _mock_tg, mock_save, saved_history = _run_phase5_execution([order], kraken_scenario=kraken_scenario)

        self.assertEqual(output["executed"], 1)
        self.assertEqual(output["skipped"], 0)
        executed = output["orders_executed"][0]
        self.assertEqual(executed["coin"], "ETH")
        self.assertEqual(executed["entry_order_id"], "BUYTX1")
        self.assertEqual(executed["sl_order_txid"], "SLTX1")
        self.assertFalse(executed["protection_failed"])
        self.assertFalse(executed["closed_at_fill"])

        mock_save.assert_called_once()
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["entry_order_id"], "BUYTX1")
        self.assertEqual(pos["sl_order_txid"], "SLTX1")
        self.assertFalse(pos["protection_failed"])
        self.assertAlmostEqual(pos["entry_price"], 2000.0)


class TestStopLossPriceRoundedToTickSize(unittest.TestCase):
    """actual_stop est arrondi au tick_size de la paire avant l'appel kraken order --price (#378)."""

    def test_actual_stop_rounded_to_tick_size_before_sl_order(self):
        order = dict(BASE_ORDER, prix_entry=70.0, stop_distance_pct=0.041234)
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["70.0", "0.01"]}},  # drift nul, prix post-fill sous le TP
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "700.0", "vol_exec": "10.0"}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"}},
            "order_sell_ETHUSDC": {"txid": ["SLTX1"]},
        }
        output, _mock_tg, mock_save, saved_history = _run_phase5_execution([order], kraken_scenario=kraken_scenario)

        # actual_entry=70.0, stop_distance_pct=0.041234 -> raw actual_stop = 70*(1-0.041234) = 67.11362
        # arrondi au tick 0.01 -> 67.11
        executed = output["orders_executed"][0]
        self.assertEqual(executed["actual_stop"], 67.11)

        pos = saved_history[0]
        self.assertEqual(pos["stop_price"], 67.11)


class TestImmediateCloseWhenPriceAboveTpAtFill(unittest.TestCase):
    """Prix post-fill >= TP recalculé -> clôture immédiate au marché (close_reason dédié)."""

    def test_position_closed_at_market_when_price_already_above_recalculated_tp(self):
        order = dict(BASE_ORDER, stop_distance_pct=0.01)
        config = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 1}
        kraken_scenario = {
            # actual_entry=2000 (200/0.1) -> actual_tp = 2000*(1+0.01*1) = 2020
            # ticker à 2020 : drift = 1% (< 2%, passe le check) ET prix_post_fill >= actual_tp
            "ticker": {"ETHUSDC": {"c": ["2020.0", "0.01"]}},
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1"}},
            "order_sell_ETHUSDC": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "202.0", "vol_exec": "0.1"}},
        }
        output, _mock_tg, mock_save, saved_history = _run_phase5_execution(
            [order], config=config, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["executed"], 1)
        executed = output["orders_executed"][0]
        self.assertTrue(executed["closed_at_fill"])
        self.assertAlmostEqual(executed["actual_entry"], 2000.0)

        mock_save.assert_called_once()
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["close_reason"], "market_above_tp_at_fill")
        self.assertAlmostEqual(pos["exit_price"], 2020.0)
        self.assertAlmostEqual(pos["pnl_usdc"], 2.0, places=6)


class TestEntryFeeCapturedFromFill(unittest.TestCase):
    """Le champ fee de la réponse query-orders du BUY est capturé dans entry_fee_usdc (#382)."""

    def test_entry_fee_and_maker_or_taker_stored_on_open_position(self):
        order = dict(BASE_ORDER)
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["2000.0", "0.01"]}},
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1", "fee": "1.2"}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC": {"txid": ["SLTX1"]},
        }
        _output, _mock_tg, mock_save, saved_history = _run_phase5_execution([order], kraken_scenario=kraken_scenario)

        pos = saved_history[0]
        self.assertAlmostEqual(pos["entry_fee_usdc"], 1.2)
        self.assertEqual(pos["maker_or_taker"], "taker")
        self.assertIsNone(pos["exit_fee_usdc"])
        self.assertIsNone(pos["fees_usdc"])
        self.assertIsNone(pos["pnl_gross_usdc"])
        mock_save.assert_called_once()


class TestNetPnlOnImmediateCloseAtFill(unittest.TestCase):
    """Clôture immédiate (market_above_tp_at_fill) : pnl_usdc net des frais entrée+sortie (#382)."""

    def test_pnl_usdc_net_of_entry_and_exit_fees(self):
        order = dict(BASE_ORDER, stop_distance_pct=0.01)
        config = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 1}
        kraken_scenario = {
            # actual_entry=2000 (200/0.1) -> actual_tp = 2000*(1+0.01*1) = 2020
            "ticker": {"ETHUSDC": {"c": ["2020.0", "0.01"]}},
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1", "fee": "0.5"}},
            "order_sell_ETHUSDC": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "202.0", "vol_exec": "0.1", "fee": "0.3"}},
        }
        output, _mock_tg, mock_save, saved_history = _run_phase5_execution(
            [order], config=config, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["executed"], 1)
        pos = saved_history[0]
        # pnl_gross = (2020-2000)*0.1 = 2.0 ; fees = 0.5+0.3 = 0.8 ; pnl net = 1.2
        self.assertAlmostEqual(pos["pnl_gross_usdc"], 2.0, places=6)
        self.assertAlmostEqual(pos["fees_usdc"], 0.8, places=6)
        self.assertAlmostEqual(pos["pnl_usdc"], 1.2, places=6)
        self.assertAlmostEqual(pos["entry_fee_usdc"], 0.5)
        self.assertAlmostEqual(pos["exit_fee_usdc"], 0.3)
        self.assertEqual(pos["maker_or_taker"], "taker")
        # pnl_gross_pct = (2020-2000)/2000*100 = 1.0 ; pnl_pct net = 1.2/(2000*0.1)*100 = 0.6
        self.assertAlmostEqual(pos["pnl_gross_pct"], 1.0, places=6)
        self.assertAlmostEqual(pos["pnl_pct"], 0.6, places=6)
        mock_save.assert_called_once()


class TestNetPnlSignInvariantWhenFeesFlipSign(unittest.TestCase):
    """pnl_pct et pnl_usdc doivent toujours avoir le même signe, même si les frais absorbent
    entièrement un gain brut positif (#382 — correction post-review PR #391)."""

    def test_pnl_pct_and_pnl_usdc_share_sign_when_fees_exceed_gross_gain(self):
        order = dict(BASE_ORDER, stop_distance_pct=0.01)
        config = {"price_deviation_max_pct": 0.02, "reward_risk_ratio": 1}
        kraken_scenario = {
            # actual_entry=2000 (200/0.1) -> actual_tp = 2020 ; gross = (2020-2000)*0.1 = 2.0 (positif)
            "ticker": {"ETHUSDC": {"c": ["2020.0", "0.01"]}},
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1", "fee": "2.0"}},
            "order_sell_ETHUSDC": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "202.0", "vol_exec": "0.1", "fee": "1.0"}},
        }
        _output, _mock_tg, _mock_save, saved_history = _run_phase5_execution(
            [order], config=config, kraken_scenario=kraken_scenario,
        )

        pos = saved_history[0]
        self.assertGreater(pos["pnl_gross_usdc"], 0)   # brut positif
        self.assertLess(pos["pnl_usdc"], 0)             # net négatif (fees = 3.0 > gross = 2.0)
        self.assertLess(pos["pnl_pct"], 0)              # même signe que pnl_usdc, pas de contradiction
        self.assertEqual((pos["pnl_usdc"] < 0), (pos["pnl_pct"] < 0))


class TestProtectionFailedWhenStopLossPlacementFails(unittest.TestCase):
    """BUY réussi mais pose du SL échoue -> protection_failed=True + notification Telegram."""

    def test_protection_failed_and_telegram_alert_when_sl_order_missing(self):
        order = dict(BASE_ORDER)
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["2000.0", "0.01"]}},
            "balance": {"USDC": "500.0"},
            "order_buy_ETHUSDC": {"txid": ["BUYTX1"]},
            "query-orders_BUYTX1": {"BUYTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1"}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            # pas de clé order_sell_ETHUSDC -> fake_kraken renvoie {} -> pas de txid -> SL échoue
        }
        output, mock_tg, mock_save, saved_history = _run_phase5_execution([order], kraken_scenario=kraken_scenario)

        self.assertEqual(output["executed"], 1)
        executed = output["orders_executed"][0]
        self.assertTrue(executed["protection_failed"])
        self.assertIsNone(executed["sl_order_txid"])

        mock_save.assert_called_once()
        pos = saved_history[0]
        self.assertTrue(pos["protection_failed"])
        self.assertEqual(pos["status"], "open")

        alert_calls = [c.args[0] for c in mock_tg.call_args_list if c.args]
        self.assertTrue(any("SL échoué" in msg for msg in alert_calls))


if __name__ == "__main__":
    unittest.main()
