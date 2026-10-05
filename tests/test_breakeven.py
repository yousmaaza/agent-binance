"""Tests du break-even (#513) : initial_stop_price, déclenchement dans tp_watcher, trailing stop et
recalibrage TP après break-even.

tp_watcher : même approche in-process que test_tp_watcher.py (lock, historique, Telegram et CLI
mockés). Trailing stop : script exécuté via le harness de test_phase0_trailing_stop.py.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from core import tp_watcher  # noqa: E402
from core.trade_helpers import initial_stop_price  # noqa: E402
from test_phase0_trailing_stop import _run_phase0_trailing_stop  # noqa: E402

CFG = {"maker_exit_enabled": False, "breakeven_enabled": True, "breakeven_trigger_pct": 0.015,
       "breakeven_include_fees": True, "fee_round_trip_pct": 0.009}


def _pos(**kw):
    p = {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": 1000.0, "quantity": 1.0,
         "stop_price": 930.0, "tp_price": 1100.0, "sl_order_txid": "SL_OLD", "risk_usdc": 79.0}
    p.update(kw)
    return p


class _CliRecorder:
    """Stub binance() : ticker fixe, journal des appels, échecs de pose de stop paramétrables."""

    def __init__(self, price, sl_failures=0, cancel_fails=False):
        self.price = price
        self.calls = []
        self.sl_failures = sl_failures  # nb de poses de stop-loss qui échouent avant succès
        self.cancel_fails = cancel_fails
        self.sl_seq = 0

    def __call__(self, *args, **_kw):
        self.calls.append(args)
        if args[0] == "ticker":
            return json.dumps({"ETHUSDC": {"c": [str(self.price), "0.01"]}})
        if args[0] == "pairs":
            return json.dumps({"ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"}})
        if args[:2] == ("order", "cancel"):
            if self.cancel_fails:
                raise RuntimeError("cancel failed")
            return "{}"
        if args[:2] == ("order", "sell") and "stop-loss" in args:
            if self.sl_failures > 0:
                self.sl_failures -= 1
                raise RuntimeError("place failed")
            self.sl_seq += 1
            return json.dumps({"txid": [f"SL_NEW{self.sl_seq}"]})
        return "{}"

    def stop_prices_placed(self):
        return [float(c[c.index("--price") + 1]) for c in self.calls if "stop-loss" in c]


def _tick(history, cli, cfg=CFG, locked=False):
    with patch("core.tp_watcher.is_locked", return_value=locked), \
         patch("core.tp_watcher.acquire_lock") as acq, \
         patch("core.tp_watcher.release_lock") as rel, \
         patch("core.tp_watcher.send_telegram") as tg, \
         patch("core.tp_watcher._write_watcher_state"), \
         patch("core.tp_watcher.publish_trade_history_slices"), \
         patch("core.tp_watcher._load_config", return_value=cfg), \
         patch("core.tp_watcher.load_trade_history", return_value=history), \
         patch("core.tp_watcher.save_trade_history") as save, \
         patch("core.tp_watcher._cli", side_effect=cli), \
         patch("core.maker_exit_watcher._cli", side_effect=cli):  # _place_stop_loss : ne jamais toucher le vrai Kraken
        tp_watcher._tp_watcher_tick()
    return tg, save, acq, rel


class TestInitialStopPrice(unittest.TestCase):
    def test_stored_value_wins(self):
        self.assertEqual(initial_stop_price(_pos(initial_stop_price=925.0, stop_price=1010.0)), 925.0)

    def test_reconstructed_from_risk(self):
        # risk 79 = 1000 x 1 x (sd + 0.009) -> sd = 0.07 -> stop d'origine 930, même si stop courant = 1010
        self.assertAlmostEqual(initial_stop_price(_pos(stop_price=1010.0)), 930.0)

    def test_fallback_to_current_stop(self):
        self.assertEqual(initial_stop_price(_pos(risk_usdc=None, stop_price=905.0)), 905.0)


class TestBreakevenTrigger(unittest.TestCase):
    def test_applies_at_trigger(self):
        pos = _pos()
        cli = _CliRecorder(1016.0)
        tg, save, acq, rel = _tick([pos], cli)
        self.assertEqual(pos["sl_order_txid"], "SL_NEW1")
        self.assertAlmostEqual(pos["stop_price"], 1009.0)  # entry x (1 + 0.009)
        self.assertTrue(pos["breakeven_applied"])
        self.assertAlmostEqual(pos["initial_stop_price"], 930.0)
        self.assertIn(("order", "cancel", "SL_OLD", "-o", "json", "--yes"), cli.calls)
        acq.assert_called_once()
        rel.assert_called_once()
        save.assert_called()
        self.assertIn("🔒", tg.call_args[0][0])

    def test_level_without_fees(self):
        pos = _pos()
        _tick([pos], _CliRecorder(1016.0), cfg={**CFG, "breakeven_include_fees": False})
        self.assertAlmostEqual(pos["stop_price"], 1000.0)

    def test_below_trigger_does_nothing(self):
        pos = _pos()
        cli = _CliRecorder(1010.0)
        _tick([pos], cli)
        self.assertEqual(pos["sl_order_txid"], "SL_OLD")
        self.assertNotIn("breakeven_applied", pos)
        self.assertEqual([c[0] for c in cli.calls], ["ticker"])

    def test_no_double_application(self):
        pos = _pos()
        _tick([pos], _CliRecorder(1016.0))
        cli2 = _CliRecorder(1030.0)
        _tick([pos], cli2)
        self.assertEqual([c[0] for c in cli2.calls], ["ticker"])
        self.assertEqual(pos["sl_order_txid"], "SL_NEW1")

    def test_stop_already_above_level_not_lowered(self):
        pos = _pos(stop_price=1020.0)
        cli = _CliRecorder(1050.0)
        _tick([pos], cli)
        self.assertEqual(pos["sl_order_txid"], "SL_OLD")
        self.assertEqual([c[0] for c in cli.calls], ["ticker"])

    def test_disabled(self):
        pos = _pos()
        cli = _CliRecorder(1050.0)
        _tick([pos], cli, cfg={**CFG, "breakeven_enabled": False})
        self.assertEqual(pos["sl_order_txid"], "SL_OLD")
        self.assertEqual([c[0] for c in cli.calls], ["ticker"])

    def test_locked_cycle_skips_everything(self):
        pos = _pos()
        cli = _CliRecorder(1050.0)
        _tick([pos], cli, locked=True)
        self.assertEqual(cli.calls, [])
        self.assertEqual(pos["sl_order_txid"], "SL_OLD")

    def test_pending_maker_exit_is_left_alone(self):
        pos = _pos()
        cli = _CliRecorder(1050.0)
        cfg = {**CFG, "maker_exit_enabled": True}
        with patch("core.tp_watcher.load_maker_exit_pending_orders", return_value=[{"trade_id": "T1"}]):
            _tick([pos], cli, cfg=cfg)
        self.assertEqual(cli.calls, [])
        self.assertEqual(pos["sl_order_txid"], "SL_OLD")

    def test_position_without_sl_is_skipped(self):
        pos = _pos(sl_order_txid=None)
        cli = _CliRecorder(1050.0)
        _tick([pos], cli)
        self.assertEqual([c[0] for c in cli.calls], ["ticker"])


class TestBreakevenReplacementFailure(unittest.TestCase):
    def test_cancel_failure_keeps_old_stop(self):
        pos = _pos()
        cli = _CliRecorder(1016.0, cancel_fails=True)
        _tick([pos], cli)
        self.assertEqual(pos["sl_order_txid"], "SL_OLD")
        self.assertNotIn("breakeven_applied", pos)
        self.assertEqual(cli.stop_prices_placed(), [])

    def test_new_stop_fails_old_stop_restored(self):
        pos = _pos()
        cli = _CliRecorder(1016.0, sl_failures=1)
        tg, save, _, rel = _tick([pos], cli)
        self.assertEqual(pos["sl_order_txid"], "SL_NEW1")  # repose de l'ancien niveau
        self.assertAlmostEqual(pos["stop_price"], 930.0)
        self.assertEqual(cli.stop_prices_placed(), [1009.0, 930.0])
        self.assertNotIn("breakeven_applied", pos)
        self.assertFalse(pos.get("protection_failed"))
        save.assert_called()
        rel.assert_called_once()

    def test_both_placements_fail_flags_protection_failed(self):
        pos = _pos()
        cli = _CliRecorder(1016.0, sl_failures=2)
        tg, save, _, rel = _tick([pos], cli)
        self.assertIsNone(pos["sl_order_txid"])
        self.assertTrue(pos["protection_failed"])  # rattrapage Phase 0 (phase0_oco_retry) prend le relais
        self.assertAlmostEqual(pos["stop_price"], 930.0)
        self.assertIn("🚨", tg.call_args[0][0])
        save.assert_called()
        rel.assert_called_once()


class TestTrailingStopAfterBreakeven(unittest.TestCase):
    def test_trailing_moves_with_initial_distance(self):
        # Stop au break-even 1009 (> entry) ; sans initial_stop_price trail_dist = 1000-1009 < 0 -> figé.
        history = [{"trade_id": "T1", "coin": "ETH", "status": "open", "sl_order_txid": "SLTX1",
                    "entry_price": 1000, "stop_price": 1009, "quantity": 1,
                    "initial_stop_price": 930, "breakeven_applied": True}]
        scenario = {
            "ticker": {"ETHUSDC": {"c": ["1150.0", "0.01"]}},  # trail_dist=70 -> new_stop=1080
            "pairs": {"ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"}},
            "order_sell_ETHUSDC": {"txid": ["NEWSLTX"]},
        }
        output, _, _, saved = _run_phase0_trailing_stop(history, scenario)
        self.assertEqual(output["updated"], 1)
        self.assertAlmostEqual(saved[0]["stop_price"], 1080.0)
        self.assertEqual(saved[0]["initial_stop_price"], 930)

    def test_trailing_reconstructs_initial_stop_for_existing_trade(self):
        history = [{"trade_id": "T1", "coin": "ETH", "status": "open", "sl_order_txid": "SLTX1",
                    "entry_price": 1000, "stop_price": 1009, "quantity": 1, "risk_usdc": 79.0}]
        scenario = {
            "ticker": {"ETHUSDC": {"c": ["1150.0", "0.01"]}},
            "pairs": {"ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"}},
            "order_sell_ETHUSDC": {"txid": ["NEWSLTX"]},
        }
        output, _, _, saved = _run_phase0_trailing_stop(history, scenario)
        self.assertEqual(output["updated"], 1)
        self.assertAlmostEqual(saved[0]["stop_price"], 1080.0)


def _tp_smart_mecanique(entry, stop_for_distance, rr=1.5, fee=0.009):
    """ÉTAPE 3 du bloc RECALIBRAGE TP de prompts/phases/phase0_snapshot.txt (tp_mecanique)."""
    sd = (entry - stop_for_distance) / entry
    return entry * (1 + (sd + fee) * rr + fee)


class TestRecalibrageTpAfterBreakeven(unittest.TestCase):
    def test_tp_not_degraded_with_initial_stop(self):
        pos = _pos(stop_price=1009.0)  # stop courant remonté au break-even
        degraded = _tp_smart_mecanique(1000.0, pos["stop_price"])
        correct = _tp_smart_mecanique(1000.0, initial_stop_price(pos))
        self.assertLess(degraded, 1015)  # le piège : cible ramenée à ~+0,9 %
        self.assertAlmostEqual(correct, 1000.0 * (1 + (0.07 + 0.009) * 1.5 + 0.009))
        self.assertGreater(correct, 1100)

    def test_prompt_uses_initial_stop(self):
        with open(os.path.join(PROJECT_DIR, "prompts", "phases", "phase0_snapshot.txt")) as f:
            text = f.read()
        self.assertIn("initial_stop_price", text)
        self.assertIn("stop_distance_pct = (entry_price - stop_origine) / entry_price", text)


if __name__ == "__main__":
    unittest.main()
