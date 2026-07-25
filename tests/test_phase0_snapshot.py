"""Tests d'intégration pour phase0_snapshot.py — snapshot des positions ouvertes.

phase0_snapshot.py lit directement state/trade_history.json (chemin en dur basé sur
PROJECT_DIR) : intercepté ici via un patch de builtins.open ciblé sur ce chemin exact
(StringIO en mémoire), le vrai fichier n'est jamais touché. tg() et l'appel kraken (binance())
sont mockés comme dans test_phase3_scoring.py : tg() via core.trade_helpers.tg,
binance() via core.trade_helpers._EXCHANGE_CLI pointé vers le stub fake_kraken.py.
"""
import builtins
import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
import uuid
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

PHASE0_SNAPSHOT_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase0_snapshot.py")
FAKE_KRAKEN_PATH = os.path.join(PROJECT_DIR, "tests", "fixtures", "fake_kraken.py")
TRADE_HISTORY_PATH = os.path.join(PROJECT_DIR, "state", "trade_history.json")

_real_open = builtins.open


def _fake_open_factory(history_text):
    """Intercepte uniquement la lecture de trade_history.json — tout le reste passe par le vrai open()."""
    def _fake_open(path, mode="r", *args, **kwargs):
        if os.path.abspath(str(path)) == TRADE_HISTORY_PATH and "r" in mode:
            return io.StringIO(history_text)
        return _real_open(path, mode, *args, **kwargs)
    return _fake_open


def _run_phase0_snapshot(history_data=None, history_text=None, ticker_scenario=None):
    """Exécute phase0_snapshot.py sur un trade_history.json et un ticker Kraken simulés.

    Retourne (output_json_ou_None, mock_tg, exit_code_ou_None).
    """
    cycle_id = f"test_{uuid.uuid4().hex[:12]}"
    scenario_path = f"/tmp/fake_kraken_scenario_{cycle_id}.json"
    with open(scenario_path, "w") as f:
        json.dump({"ticker": ticker_scenario or {}}, f)

    out_path = f"/tmp/cycle_{cycle_id}_phase0_snapshot_output.json"
    text = history_text if history_text is not None else json.dumps(history_data or [])

    old_argv = sys.argv
    old_env = os.environ.get("FAKE_KRAKEN_SCENARIO")
    sys.argv = ["phase0_snapshot.py", cycle_id]
    os.environ["FAKE_KRAKEN_SCENARIO"] = scenario_path
    exit_code = None
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=_fake_open_factory(text)))

            spec = importlib.util.spec_from_file_location(f"phase0_snapshot_{cycle_id}", PHASE0_SNAPSHOT_PATH)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except SystemExit as e:
                exit_code = e.code

        output = None
        if os.path.exists(out_path):
            with open(out_path) as f:
                output = json.load(f)
        return output, mock_tg, exit_code
    finally:
        sys.argv = old_argv
        if old_env is None:
            os.environ.pop("FAKE_KRAKEN_SCENARIO", None)
        else:
            os.environ["FAKE_KRAKEN_SCENARIO"] = old_env
        for p in (scenario_path, out_path):
            if os.path.exists(p):
                os.remove(p)


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
