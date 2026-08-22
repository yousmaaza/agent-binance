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

from core import tp_watcher  # noqa: E402


def _fake_cli(*args, **_kwargs):
    if args[0] == "ticker":
        return json.dumps({"ETHUSDC": {"c": ["1100.0", "0.01"]}})
    if args[0] == "order" and args[1] == "sell":
        return json.dumps({"txid": ["SELLTX1"]})
    if args[0] == "query-orders":
        return json.dumps({"SELLTX1": {"status": "closed", "cost": "1100.0", "vol_exec": "1.0", "fee": "0.7"}})
    return "{}"


class TestTpWatcherFeeCapture(unittest.TestCase):
    """Le champ fee de la réponse query-orders du SELL est déduit du PnL net (#382)."""

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


if __name__ == "__main__":
    unittest.main()
