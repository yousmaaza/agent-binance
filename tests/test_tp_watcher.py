"""Tests pour tp_watcher.py — traçabilité des frais Kraken sur la sortie TP (#382).

is_locked/acquire_lock/release_lock, load_trade_history/save_trade_history, send_telegram et
_write_watcher_state sont mockés (jamais le vrai state/*.json ni un vrai curl). binance() (alias
_cli) est mocké via un side_effect qui route sur la sous-commande, comme fake_kraken.py mais
in-process (tp_watcher._tp_watcher_tick() n'est pas un script top-level exécutable via
exec_phase_script, donc le harness tests/fixtures/test_harness.py ne s'applique pas ici).
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core import tp_watcher


def _fake_cli(*args, **_kwargs):
    if args[0] == "ticker":
        return json.dumps({"ETHUSDC": {"c": ["1100.0", "0.01"]}})
    if args[0] == "order" and args[1] == "sell":
        return json.dumps({"txid": ["SELLTX1"]})
    if args[0] == "query-orders":
        return json.dumps({"SELLTX1": {"status": "closed", "cost": "1100.0", "vol_exec": "1.0", "fee": "0.7"}})
    return "{}"


class TestTpWatcherFeeCapture(unittest.TestCase):
    """Le champ fee de la réponse query-orders du SELL est déduit du PnL net (#382).

    maker_exit_enabled: false (#390) -> comportement de vente au marché inchangé."""

    def test_pnl_usdc_net_of_entry_and_exit_fees(self):
        pos = {
            "trade_id": "T1", "coin": "ETH", "status": "open",
            "entry_price": 1000, "quantity": 1, "tp_price": 1100,
            "entry_fee_usdc": 0.5, "sl_order_txid": None,
        }
        history = [pos]

        with patch("core.tp_watcher.is_locked", return_value=False), \
             patch("core.tp_watcher.acquire_lock"), \
             patch("core.tp_watcher.release_lock"), \
             patch("core.tp_watcher.send_telegram"), \
             patch("core.tp_watcher._write_watcher_state"), \
             patch("core.tp_watcher._load_config", return_value={"maker_exit_enabled": False}), \
             patch("core.tp_watcher.load_trade_history", return_value=history), \
             patch("core.tp_watcher.save_trade_history") as mock_save, \
             patch("core.tp_watcher._cli", side_effect=_fake_cli):
            tp_watcher._tp_watcher_tick()

        mock_save.assert_called_once()
        # pnl_gross = (1100-1000)*1 = 100.0 ; fees = 0.5+0.7 = 1.2 ; pnl net = 98.8
        self.assertEqual(pos["status"], "closed")
        self.assertAlmostEqual(pos["pnl_gross_usdc"], 100.0)
        self.assertAlmostEqual(pos["fees_usdc"], 1.2)
        self.assertAlmostEqual(pos["pnl_usdc"], 98.8)
        self.assertAlmostEqual(pos["entry_fee_usdc"], 0.5)
        self.assertAlmostEqual(pos["exit_fee_usdc"], 0.7)
        self.assertEqual(pos["close_reason"], "tp_watcher")
        self.assertIsNone(pos["cycle_id"])


class TestTpWatcherMakerExitHandoff(unittest.TestCase):
    """#390 : quand maker_exit_enabled (défaut), le TP watcher ne vend plus au marché — il
    délègue à attempt_maker_exit() et enregistre le résultat dans
    state/maker_exit_pending_orders.json plutôt que de fermer la position lui-même."""

    def test_tp_reached_hands_off_to_maker_exit_instead_of_market_sell(self):
        pos = {
            "trade_id": "T1", "coin": "ETH", "status": "open",
            "entry_price": 1000, "quantity": 1, "tp_price": 1100,
            "entry_fee_usdc": 0.5, "sl_order_txid": "SLTX0", "stop_price": 950.0,
        }
        history = [pos]
        new_pending = {"trade_id": "T1", "coin": "ETH", "pair": "ETHUSDC", "txid": "SELLTX1",
                       "quantity": 1, "stop_price": 950.0, "close_reason": "tp_watcher"}

        with patch("core.tp_watcher.is_locked", return_value=False), \
             patch("core.tp_watcher.acquire_lock"), \
             patch("core.tp_watcher.release_lock"), \
             patch("core.tp_watcher.send_telegram"), \
             patch("core.tp_watcher._write_watcher_state"), \
             patch("core.tp_watcher._load_config", return_value={"maker_exit_enabled": True}), \
             patch("core.tp_watcher.load_trade_history", return_value=history), \
             patch("core.tp_watcher.save_trade_history") as mock_save, \
             patch("core.tp_watcher.load_maker_exit_pending_orders", return_value=[]), \
             patch("core.tp_watcher.save_maker_exit_pending_orders") as mock_save_pending, \
             patch("core.tp_watcher.attempt_maker_exit", return_value=new_pending) as mock_attempt, \
             patch("core.tp_watcher._cli", side_effect=_fake_cli):
            tp_watcher._tp_watcher_tick()

        mock_attempt.assert_called_once()
        self.assertEqual(mock_attempt.call_args[0][0], pos)
        self.assertEqual(mock_attempt.call_args[0][1], "tp_watcher")
        self.assertIsNone(mock_attempt.call_args.kwargs["cycle_id"])
        mock_save_pending.assert_called_once_with([new_pending])
        # La position reste "open" côté trade_history — c'est maker_exit_watcher.py qui la
        # clôturera au fill/repli marché, pas tp_watcher.py.
        self.assertEqual(pos["status"], "open")
        mock_save.assert_called_once()

    def test_position_already_in_maker_exit_pending_is_not_retriggered(self):
        pos = {
            "trade_id": "T1", "coin": "ETH", "status": "open",
            "entry_price": 1000, "quantity": 1, "tp_price": 1100,
            "entry_fee_usdc": 0.5, "sl_order_txid": "SLTX0", "stop_price": 950.0,
        }
        history = [pos]
        already_pending = [{"trade_id": "T1", "coin": "ETH", "pair": "ETHUSDC", "txid": "SELLTX1"}]

        with patch("core.tp_watcher.is_locked", return_value=False), \
             patch("core.tp_watcher.acquire_lock"), \
             patch("core.tp_watcher.release_lock"), \
             patch("core.tp_watcher.send_telegram"), \
             patch("core.tp_watcher._write_watcher_state"), \
             patch("core.tp_watcher._load_config", return_value={"maker_exit_enabled": True}), \
             patch("core.tp_watcher.load_trade_history", return_value=history), \
             patch("core.tp_watcher.save_trade_history") as mock_save, \
             patch("core.tp_watcher.load_maker_exit_pending_orders", return_value=already_pending), \
             patch("core.tp_watcher.save_maker_exit_pending_orders"), \
             patch("core.tp_watcher.attempt_maker_exit") as mock_attempt, \
             patch("core.tp_watcher._cli", side_effect=_fake_cli):
            tp_watcher._tp_watcher_tick()

        mock_attempt.assert_not_called()
        mock_save.assert_not_called()


class _StopLoop(BaseException):
    """Sentinelle pour interrompre tp_watcher_loop() — hérite de BaseException (pas Exception)
    pour ne pas être interceptée par le except Exception de la boucle (#463)."""


class TestTpWatcherLoopSurvivesUnlistedException(unittest.TestCase):
    """#463 : tp_watcher_loop() catche déjà `except Exception`, mais ne journalisait que
    `{e}` — sans le type ni la pile, un incident reste difficile à diagnostiquer. La boucle doit
    continuer au tick suivant ET la trace doit porter le type de l'exception."""

    def test_attribute_error_in_tick_is_caught_and_loop_continues(self):
        tick_calls = []

        def fake_tick():
            tick_calls.append(1)
            raise AttributeError("'NoneType' object has no attribute 'get'")

        with patch("core.tp_watcher._tp_watcher_tick", side_effect=fake_tick), \
             patch("core.tp_watcher.time.sleep", side_effect=[None, None, _StopLoop()]), \
             patch("core.tp_watcher.logger") as mock_logger:
            with self.assertRaises(_StopLoop):
                tp_watcher.tp_watcher_loop()

        self.assertEqual(len(tick_calls), 2)
        mock_logger.exception.assert_called()
        last_msg = mock_logger.exception.call_args[0][0]
        self.assertIn("AttributeError", last_msg)


if __name__ == "__main__":
    unittest.main()
