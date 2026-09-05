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


def _run_phase0_profit(history_data, config=None, kraken_scenario=None, exit_pending=None):
    """Exécute phase0_profit.py. Retourne (output_json, mock_tg, mock_save, mock_save_exit_pending).

    core.maker_exit_watcher.load_maker_exit_pending_orders/save_maker_exit_pending_orders sont
    toujours mockés ici (#390) — jamais le vrai state/maker_exit_pending_orders.json, sur le même
    principe que trade_history.json."""
    cycle_id = harness.new_cycle_id()
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    out_path = f"/tmp/cycle_{cycle_id}_phase0_profit_output.json"
    text = json.dumps(history_data)
    # maker_exit_enabled: false par défaut ici -> comportement historique (SELL MARKET direct)
    # inchangé, sauf override explicite du test (#390).
    cfg = config if config is not None else {"min_profit_pct_take": 5.0, "maker_exit_enabled": False}

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(patch("core.trade_helpers._load_config", return_value=cfg))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))
            stack.enter_context(patch("core.maker_exit_watcher.load_maker_exit_pending_orders",
                                       return_value=exit_pending if exit_pending is not None else []))
            mock_save_exit_pending = stack.enter_context(patch("core.maker_exit_watcher.save_maker_exit_pending_orders"))

            harness.exec_phase_script(PHASE0_PROFIT_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        return output, mock_tg, mock_save, mock_save_exit_pending
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
        output, mock_tg, mock_save, _mock_save_pending = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0, "maker_exit_enabled": False},
            kraken_scenario=kraken_scenario,
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


class TestProfitTargetNetOfFees(unittest.TestCase):
    """pnl_usdc devient le PnL net des frais entrée+sortie (#382)."""

    def test_pnl_usdc_net_of_entry_and_exit_fees(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1", "entry_fee_usdc": 0.6},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1100.0", "0.01"]}},  # +10% > seuil 5%
            "order_sell_ETHUSDC": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "1100.0", "vol_exec": "1.0", "fee": "0.7"}},
        }
        output, _mock_tg, mock_save, _mock_save_pending = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0, "maker_exit_enabled": False},
            kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        pos = mock_save.call_args[0][0][0]
        # pnl_gross = 100.0 ; fees = 0.6+0.7 = 1.3 ; pnl net = 98.7
        self.assertAlmostEqual(pos["pnl_gross_usdc"], 100.0)
        self.assertAlmostEqual(pos["fees_usdc"], 1.3)
        self.assertAlmostEqual(pos["pnl_usdc"], 98.7)
        self.assertAlmostEqual(pos["entry_fee_usdc"], 0.6)
        self.assertAlmostEqual(pos["exit_fee_usdc"], 0.7)


class TestProfitTargetEvaluatedNet(unittest.TestCase):
    """Le seuil min_profit_pct_take est évalué sur un pourcentage NET (frais de sortie estimés
    déduits), pas brut (#411) : un profit latent brut au-dessus du seuil mais net en-dessous ne
    doit pas déclencher la clôture."""

    def test_gross_above_threshold_but_net_below_does_not_close(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1"},
        ]
        # +5.5% brut > seuil 5%, mais net estimé = 5.5% - fee_round_trip_pct(0.9%) = 4.6% < 5%
        kraken_scenario = {"ticker": {"ETHUSDC": {"c": ["1055.0", "0.01"]}}}
        output, mock_tg, mock_save, _mock_save_pending = _run_phase0_profit(
            history_data,
            config={"min_profit_pct_take": 5.0, "fee_round_trip_pct": 0.009, "maker_exit_enabled": False},
            kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        mock_save.assert_not_called()
        mock_tg.assert_not_called()

    def test_net_above_threshold_closes(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1"},
        ]
        # +6% brut, net estimé = 6% - 0.9% = 5.1% >= seuil 5%
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1060.0", "0.01"]}},
            "order_sell_ETHUSDC": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "1060.0", "vol_exec": "1.0"}},
        }
        output, mock_tg, mock_save, _mock_save_pending = _run_phase0_profit(
            history_data,
            config={"min_profit_pct_take": 5.0, "fee_round_trip_pct": 0.009, "maker_exit_enabled": False},
            kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        mock_save.assert_called()
        mock_tg.assert_called()


class TestProfitBelowThresholdNoAction(unittest.TestCase):
    def test_position_untouched_when_profit_below_threshold(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1"},
        ]
        kraken_scenario = {"ticker": {"ETHUSDC": {"c": ["1020.0", "0.01"]}}}  # +2% < seuil 5%
        output, mock_tg, mock_save, _mock_save_pending = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0, "maker_exit_enabled": False},
            kraken_scenario=kraken_scenario,
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
        output, _, mock_save, _mock_save_pending = _run_phase0_profit(history_data, kraken_scenario={})

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
        output, _, mock_save, _mock_save_pending = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0, "maker_exit_enabled": False},
            kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        mock_save.assert_not_called()
        self.assertEqual(history_data[0]["status"], "open")


class TestProfitTargetMakerExitHandoff(unittest.TestCase):
    """#390 : maker_exit_enabled (défaut) -> phase0_profit.py ne vend plus au marché lui-même, il
    délègue à attempt_maker_exit() et enregistre le résultat dans
    state/maker_exit_pending_orders.json plutôt que de fermer la position."""

    def test_profit_target_hands_off_to_maker_exit_instead_of_market_sell(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1", "sl_order_txid": "SLTX0", "stop_price": 950.0},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"a": ["1100.5", "0.01"], "c": ["1100.0", "0.01"]}},  # +10% > seuil 5%
            "order_sell_ETHUSDC_limit": {"txid": ["SELLTX1"]},
        }
        output, _mock_tg, mock_save, mock_save_pending = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0, "maker_exit_enabled": True},
            kraken_scenario=kraken_scenario,
        )

        # Pas encore "closed" : posé en LIMIT, suivi par core/maker_exit_watcher.py.
        self.assertEqual(output["closed"], 0)
        self.assertEqual(history_data[0]["status"], "open")
        mock_save_pending.assert_called_once()
        saved_pending = mock_save_pending.call_args[0][0]
        self.assertEqual(len(saved_pending), 1)
        self.assertEqual(saved_pending[0]["trade_id"], "T1")
        self.assertEqual(saved_pending[0]["close_reason"], "profit_target_phase0")
        self.assertEqual(saved_pending[0]["txid"], "SELLTX1")
        mock_save.assert_called()  # trade_history persisté (protection_failed/status potentiel)

    def test_position_already_pending_maker_exit_is_not_retriggered(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": "1000",
             "quantity": "1", "sl_order_txid": "SLTX0", "stop_price": 950.0},
        ]
        kraken_scenario = {"ticker": {"ETHUSDC": {"c": ["1100.0", "0.01"]}}}  # +10% > seuil 5%
        already_pending = [{"trade_id": "T1", "coin": "ETH", "pair": "ETHUSDC", "txid": "SELLTX1"}]
        output, _mock_tg, mock_save, mock_save_pending = _run_phase0_profit(
            history_data, config={"min_profit_pct_take": 5.0, "maker_exit_enabled": True},
            kraken_scenario=kraken_scenario, exit_pending=already_pending,
        )

        self.assertEqual(output["closed"], 0)
        mock_save_pending.assert_not_called()
        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
