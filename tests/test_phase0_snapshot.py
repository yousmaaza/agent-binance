"""Tests d'intégration pour phase0_snapshot.py — snapshot des positions ouvertes.

phase0_snapshot.py lit directement state/trade_history.json (chemin en dur basé sur
PROJECT_DIR) : intercepté ici via un patch de builtins.open ciblé sur ce chemin exact
(StringIO en mémoire), le vrai fichier n'est jamais touché. tg() et l'appel kraken (binance())
sont mockés comme dans test_phase3_scoring.py : tg() via core.trade_helpers.tg,
binance() via core.trade_helpers._EXCHANGE_CLI pointé vers le stub fake_kraken.py.

Helpers partagés (fake_open_factory, gestion du scénario kraken, exec du script) : voir
tests/fixtures/test_harness.py.
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

from fixtures import test_harness as harness  # noqa: E402

PHASE0_SNAPSHOT_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase0_snapshot.py")


def _run_phase0_snapshot(history_data=None, history_text=None, ticker_scenario=None):
    """Exécute phase0_snapshot.py sur un trade_history.json et un ticker Kraken simulés.

    Retourne (output_json_ou_None, mock_tg, exit_code_ou_None).
    """
    cycle_id = harness.new_cycle_id()
    scenario_path = harness.write_kraken_scenario({"ticker": ticker_scenario or {}})
    out_path = f"/tmp/cycle_{cycle_id}_phase0_snapshot_output.json"
    text = history_text if history_text is not None else json.dumps(history_data or [])

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))

            exit_code = harness.exec_phase_script(PHASE0_SNAPSHOT_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        return output, mock_tg, exit_code
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(scenario_path, out_path)


class TestSnapshotOpenPositions(unittest.TestCase):
    """Cas principal : positions ouvertes, calcul P&L et distinction bot/manuel."""

    def test_open_positions_pnl_and_pos_type(self):
        history_data = [
            {"coin": "ETH", "status": "open", "entry_price": "1800", "quantity": "0.5",
             "side": "BUY", "entry_order_id": "ORD1"},
            {"coin": "SOL", "status": "open", "entry_price": "100", "quantity": "2",
             "side": "BUY"},  # pas d'entry_order_id -> position manuelle
            {"coin": "XRP", "status": "closed", "entry_price": "0.5", "quantity": "1000"},
        ]
        ticker_scenario = {
            "ETHUSDC": {"c": ["1900.0", "0.01"]},
            "SOLUSDC": {"c": ["90.0", "0.01"]},
        }
        output, mock_tg, exit_code = _run_phase0_snapshot(history_data, ticker_scenario=ticker_scenario)

        self.assertIsNone(exit_code)
        self.assertEqual(output["open_positions"], 2)
        mock_tg.assert_called_once()
        message = mock_tg.call_args[0][0]
        self.assertIn("ETH", message)
        self.assertIn("SOL", message)
        self.assertIn("[bot]", message)      # ETH : side=BUY + entry_order_id présent -> bot
        self.assertIn("[manuel]", message)   # SOL : pas d'entry_order_id -> manuel
        self.assertIn("+5.6%", message)      # ETH : (1900-1800)/1800*100
        self.assertIn("+50.00 USDC", message)
        self.assertIn("-10.0%", message)     # SOL : (90-100)/100*100
        self.assertIn("-20.00 USDC", message)
        self.assertNotIn("XRP", message)  # position closed exclue du snapshot


class TestSnapshotNoOpenPositions(unittest.TestCase):
    def test_no_open_positions_sends_default_message(self):
        history_data = [
            {"coin": "XRP", "status": "closed", "entry_price": "0.5", "quantity": "1000"},
        ]
        output, mock_tg, exit_code = _run_phase0_snapshot(history_data)

        self.assertIsNone(exit_code)
        self.assertEqual(output["open_positions"], 0)
        mock_tg.assert_called_once_with("📊 Aucune position ouverte actuellement")


class TestSnapshotCorruptedHistory(unittest.TestCase):
    """Cas limite : trade_history.json corrompu -> erreur gérée, pas de crash silencieux."""

    def test_corrupted_history_triggers_error_path(self):
        output, mock_tg, exit_code = _run_phase0_snapshot(history_text="{ceci n'est pas du json")

        self.assertIsNone(output)  # le script sort avant d'écrire le fichier de sortie
        self.assertEqual(exit_code, 1)
        mock_tg.assert_called_once()
        self.assertIn("Snapshot positions échoué", mock_tg.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
