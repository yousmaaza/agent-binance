"""Tests pour core/dashboard_state.py — publish_trade_history_slices (#500).

Les fonctions de dérivation pure (_open_positions, _closed_trades, _financials, ...) sont déjà
couvertes en profondeur par tests/test_phase7_mongo.py (exécutées au travers de la Phase 7,
identique avant/après le déplacement de #500). Ce fichier couvre uniquement la glue ajoutée par
#500 : le calcul des slices à publier et les garde-fous de publication (jamais d'exception
remontée dans la boucle du watcher appelant, échec Mongo journalisé et non bloquant)."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

import core.dashboard_state as dashboard_state  # noqa: E402


class TestPublishTradeHistorySlices(unittest.TestCase):
    def _history(self):
        return [
            {"coin": "ETH", "status": "open", "entry_price": 2000.0, "quantity": 0.1},
            {"coin": "XBT", "status": "closed", "pnl_usdc": 1.43, "fees_usdc": 0.05,
             "exit_date": "2026-09-14T20:11:38+00:00"},
        ]

    def test_publishes_slices_derived_from_history(self):
        mock_mongo = MagicMock()
        mock_mongo.save_trade_history_slices.return_value = True

        with patch.object(dashboard_state, "mongo_repo", mock_mongo):
            result = dashboard_state.publish_trade_history_slices(self._history(), "Maker Watcher")

        self.assertTrue(result)
        mock_mongo.save_trade_history_slices.assert_called_once()
        open_positions, closed_trades, financials = mock_mongo.save_trade_history_slices.call_args[0]
        self.assertEqual(len(open_positions), 1)
        self.assertEqual(open_positions[0]["coin"], "ETH")
        self.assertEqual(len(closed_trades), 1)
        self.assertEqual(closed_trades[0]["coin"], "XBT")
        self.assertEqual(financials["global"]["net_usdc"], 1.43)

    def test_mongo_returning_false_is_propagated_without_raising(self):
        mock_mongo = MagicMock()
        mock_mongo.save_trade_history_slices.return_value = False

        with patch.object(dashboard_state, "mongo_repo", mock_mongo):
            result = dashboard_state.publish_trade_history_slices(self._history(), "TP Watcher")

        self.assertFalse(result)

    def test_mongo_exception_is_caught_logged_and_returns_false(self):
        """Confort d'affichage seulement (#500, même garde-fou que #498) : une exception levée par
        Mongo ne doit jamais remonter dans la boucle d'un watcher qui pose de vrais ordres."""
        mock_mongo = MagicMock()
        mock_mongo.save_trade_history_slices.side_effect = Exception("Mongo injoignable")

        with patch.object(dashboard_state, "mongo_repo", mock_mongo), \
             patch.object(dashboard_state, "logger") as mock_logger:
            result = dashboard_state.publish_trade_history_slices(self._history(), "Maker Exit Watcher")

        self.assertFalse(result)
        mock_logger.warning.assert_called_once()
        self.assertIn("Maker Exit Watcher", mock_logger.warning.call_args[0][0])

    def test_empty_history_publishes_empty_slices(self):
        mock_mongo = MagicMock()
        mock_mongo.save_trade_history_slices.return_value = True

        with patch.object(dashboard_state, "mongo_repo", mock_mongo):
            dashboard_state.publish_trade_history_slices([], "Maker Watcher")

        open_positions, closed_trades, financials = mock_mongo.save_trade_history_slices.call_args[0]
        self.assertEqual(open_positions, [])
        self.assertEqual(closed_trades, [])
        self.assertEqual(financials["global"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
