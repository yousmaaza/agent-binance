"""Tests d'intégration pour phase0_oco_retry.py — retry OCO en cas d'échec de pose du SL.

Même approche que les autres tests phase0_* : trade_history.json intercepté via patch de
builtins.open ciblé, _save_trade_history_atomic/_load_config/log_phase0_event mockés, tg()
mockée, binance() redirigée vers le stub fake_kraken.py.

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

PHASE0_OCO_RETRY_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase0_oco_retry.py")


def _run_phase0_oco_retry(history_data, config=None, kraken_scenario=None):
    """Exécute phase0_oco_retry.py. Retourne (output_json, mock_tg, mock_save, saved_history)."""
    cycle_id = harness.new_cycle_id()
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    out_path = f"/tmp/cycle_{cycle_id}_phase0_oco_retry_output.json"
    text = json.dumps(history_data)
    cfg = config if config is not None else {"max_oco_retry": 3}

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(patch("core.trade_helpers._load_config", return_value=cfg))
            stack.enter_context(patch("core.trade_helpers.log_phase0_event"))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))

            harness.exec_phase_script(PHASE0_OCO_RETRY_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        saved_history = mock_save.call_args[0][0] if mock_save.call_args else None
        return output, mock_tg, mock_save, saved_history
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(scenario_path, out_path)


class TestOcoRetryIdempotentWhenSlAlreadyActive(unittest.TestCase):
    """Idempotence : un SL déjà actif corrige protection_failed sans repasser d'ordre."""

    def test_sl_already_open_marks_protection_recovered(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "protection_failed": True,
             "quantity": 1, "entry_price": 1000, "tp_price": 1200, "stop_price": 900,
             "sl_order_txid": "SLTX1", "oco_retry_count": 0},
        ]
        kraken_scenario = {
            "query-orders_SLTX1": {"SLTX1": {"status": "open"}},
        }
        output, mock_tg, _, saved_history = _run_phase0_oco_retry(history_data, kraken_scenario=kraken_scenario)

        self.assertEqual(output["retried"], 1)
        pos = saved_history[0]
        self.assertFalse(pos["protection_failed"])
        mock_tg.assert_called_once()
        self.assertIn("SL déjà actif", mock_tg.call_args[0][0])


class TestOcoRetryForceCloseAboveTp(unittest.TestCase):
    """Prix actuel > TP alors que protection_failed -> fermeture immédiate au marché."""

    def test_price_above_tp_forces_market_close(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "protection_failed": True,
             "quantity": 1, "entry_price": 1000, "tp_price": 1200, "stop_price": 900,
             "oco_retry_count": 0},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1300.0", "0.01"]}},  # > tp_price 1200
            "order_sell_ETHUSDC": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "1300.0", "vol_exec": "1.0"}},
        }
        output, _, _, saved_history = _run_phase0_oco_retry(history_data, kraken_scenario=kraken_scenario)

        self.assertEqual(output["retried"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["close_reason"], "market_above_tp")
        self.assertFalse(pos["protection_failed"])
        self.assertAlmostEqual(pos["exit_price"], 1300.0)


class TestOcoRetryNormalRetry(unittest.TestCase):
    """Prix sous le TP, retry count < max -> nouveau SL posé, oco_retry_count remis à 0."""

    def test_retry_below_max_places_new_sl(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "protection_failed": True,
             "quantity": 1, "entry_price": 1000, "tp_price": 1200, "stop_price": 900,
             "oco_retry_count": 1},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1050.0", "0.01"]}},  # < tp_price 1200
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC": {"txid": ["NEWSLTX"]},
        }
        output, _, _, saved_history = _run_phase0_oco_retry(
            history_data, config={"max_oco_retry": 3}, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["retried"], 1)
        pos = saved_history[0]
        self.assertFalse(pos["protection_failed"])
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX")
        self.assertEqual(pos["stop_price"], 900)
        self.assertEqual(pos["oco_retry_count"], 0)


class TestOcoRetryExhaustedFallback(unittest.TestCase):
    """Cas limite : retry count >= max_oco_retry -> fermeture forcée au marché (fallback)."""

    def test_retry_exhausted_forces_market_close(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "protection_failed": True,
             "quantity": 1, "entry_price": 1000, "tp_price": 1200, "stop_price": 900,
             "oco_retry_count": 3},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1050.0", "0.01"]}},  # < tp_price 1200
            "order_sell_ETHUSDC": {"txid": ["SELLTX2"]},
            "query-orders_SELLTX2": {"SELLTX2": {"status": "closed", "cost": "1050.0", "vol_exec": "1.0"}},
        }
        output, _, _, saved_history = _run_phase0_oco_retry(
            history_data, config={"max_oco_retry": 3}, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["retried"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["close_reason"], "protection_exhausted")
        self.assertEqual(pos["oco_retry_count"], 0)


if __name__ == "__main__":
    unittest.main()
