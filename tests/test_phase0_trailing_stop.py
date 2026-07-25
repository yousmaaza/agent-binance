"""Unit tests pour les fonctions utilitaires de phase0_trailing_stop.py + tests d'intégration
sur le recalcul du trailing stop lui-même (voir classes TestTrailingStopRecalc* en bas du
fichier). Ces derniers suivent la même approche que test_phase0_profit.py : trade_history.json
intercepté via patch de builtins.open ciblé, tg()/_save_trade_history_atomic/log_phase0_event
mockés, binance() redirigée vers le stub fake_kraken.py.

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import json
import math
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot", "core", "phases"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE0_TS_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase0_trailing_stop.py")


def _run_phase0_trailing_stop(history_data, kraken_scenario=None):
    """Exécute phase0_trailing_stop.py. Retourne (output_json, mock_tg, mock_save, saved_history)."""
    cycle_id = harness.new_cycle_id()
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    out_path = f"/tmp/cycle_{cycle_id}_phase0_trailing_stop_output.json"
    text = json.dumps(history_data)

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(patch("core.trade_helpers.log_phase0_event"))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))

            harness.exec_phase_script(PHASE0_TS_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        saved_history = mock_save.call_args[0][0] if mock_save.call_args else None
        return output, mock_tg, mock_save, saved_history
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(scenario_path, out_path)


def _round_price(p, tick):
    return round(round(p / tick) * tick, 8)


def _round_qty(q, step):
    return round(math.floor(q / step) * step, 8)


class TestRoundPrice(unittest.TestCase):
    """Tests pour _round_price()"""

    def test_exact_multiple(self):
        """Si p est un multiple exact de tick, retourner p."""
        self.assertEqual(_round_price(1.0, 0.01), 1.0)
        self.assertEqual(_round_price(10.5, 0.5), 10.5)
        self.assertEqual(_round_price(0.001, 0.0001), 0.001)

    def test_round_up(self):
        """Arrondir à la hausse quand p/tick > 0.5"""
        result = _round_price(1.009, 0.01)
        self.assertEqual(result, 1.01)

    def test_round_down(self):
        """Arrondir à la baisse quand p/tick < 0.5"""
        result = _round_price(1.004, 0.01)
        self.assertEqual(result, 1.0)

    def test_small_tick(self):
        """Tester avec très petit tick (8 décimales, limit float)."""
        result = _round_price(0.00000001, 0.00000001)
        self.assertEqual(result, 0.00000001)

    def test_large_price(self):
        """Tester avec grand prix."""
        result = _round_price(50000.123, 0.01)
        self.assertAlmostEqual(result, 50000.12, places=2)

    def test_binance_usdc_example(self):
        """Cas réaliste : Bitcoin/USDC avec tick_size=0.01."""
        price = 42567.8654
        tick = 0.01
        result = _round_price(price, tick)
        self.assertEqual(result, 42567.87)

    def test_kraken_example(self):
        """Cas réaliste : Ethereum/USDC avec tick_size=0.01."""
        price = 2345.567
        tick = 0.01
        result = _round_price(price, tick)
        self.assertEqual(result, 2345.57)


class TestRoundQty(unittest.TestCase):
    """Tests pour _round_qty()"""

    def test_exact_multiple(self):
        """Si q est un multiple exact de step, retourner q."""
        self.assertEqual(_round_qty(1.0, 0.1), 1.0)
        self.assertEqual(_round_qty(10.0, 1.0), 10.0)
        self.assertEqual(_round_qty(0.001, 0.0001), 0.001)

    def test_floor_behavior(self):
        """math.floor() tronque vers le bas."""
        result = _round_qty(1.99, 0.1)
        self.assertEqual(result, 1.9)

    def test_small_step(self):
        """Tester avec très petit step."""
        result = _round_qty(0.12345, 0.00001)
        self.assertEqual(result, 0.12345)

    def test_large_qty(self):
        """Tester avec grande quantité."""
        result = _round_qty(1000.5, 0.1)
        self.assertEqual(result, 1000.5)

    def test_binance_lot_size_example(self):
        """Cas réaliste : lot_size=0.001 avec quantité."""
        qty = 10.9876
        lot = 0.001
        result = _round_qty(qty, lot)
        self.assertEqual(result, 10.987)

    def test_lot_decimals_8(self):
        """lot_decimals=8 → step=10^(-8)=0.00000001."""
        qty = 0.123456789
        step = 0.00000001
        result = _round_qty(qty, step)
        self.assertEqual(result, 0.12345678)

    def test_precision_8_decimals(self):
        """Vérifier la précision à 8 décimales."""
        result = _round_qty(0.999999999, 0.00000001)
        self.assertEqual(result, 0.99999999)


class TestRoundingAccuracy(unittest.TestCase):
    """Tests d'intégration : précision combinée."""

    def test_price_then_qty_workflow(self):
        """Simule le workflow réel : arrondir prix puis qty."""
        # Exemple : arrondir prix du stop et qty pour un ordre
        original_price = 42567.8654
        original_qty = 0.123456789

        tick = 0.01
        lot = 0.00000001

        rounded_price = _round_price(original_price, tick)
        rounded_qty = _round_qty(original_qty, lot)

        # Vérifier que les résultats sont dans les bonnes plages
        self.assertLessEqual(rounded_qty, original_qty)
        self.assertGreaterEqual(rounded_price, 0)

    def test_zero_handling(self):
        """Gérer le zéro."""
        self.assertEqual(_round_price(0, 0.01), 0)
        self.assertEqual(_round_qty(0, 0.1), 0)

    def test_very_small_values(self):
        """Tester avec valeurs très proches de zéro."""
        result_p = _round_price(0.00000001, 0.00000001)
        result_q = _round_qty(0.00000001, 0.00000001)
        self.assertEqual(result_p, 0.00000001)
        self.assertEqual(result_q, 0.00000001)


class TestTrailingStopRecalcMovesUp(unittest.TestCase):
    """Prix monté suffisamment : SL annulé, nouveau SL posé plus haut, stop_price mis à jour."""

    def test_stop_moves_up_when_price_rises_enough(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "sl_order_txid": "SLTX1",
             "entry_price": 1000, "stop_price": 900, "quantity": 1},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1150.0", "0.01"]}},  # trail_dist=100 -> new_stop=1050
            "pairs": {"ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"}},
            "order_sell_ETHUSDC": {"txid": ["NEWSLTX"]},
        }
        output, mock_tg, _, saved_history = _run_phase0_trailing_stop(history_data, kraken_scenario)

        self.assertEqual(output["updated"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX")
        self.assertAlmostEqual(pos["stop_price"], 1050.0)
        mock_tg.assert_any_call(
            "📈 ETH trailing stop remonté\nStop : 900 → 1050\nPrix actuel : 1150"
        )


class TestTrailingStopSkipTooClose(unittest.TestCase):
    """Nouveau stop pas assez éloigné du stop courant (< 20% de la distance trail) -> pas de mise à jour."""

    def test_skip_when_new_stop_too_close_to_current_stop(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "sl_order_txid": "SLTX1",
             "entry_price": 1000, "stop_price": 900, "quantity": 1},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["1010.0", "0.01"]}},  # trail_dist=100 -> new_stop=910 <= 900+20
        }
        output, mock_tg, mock_save, _ = _run_phase0_trailing_stop(history_data, kraken_scenario)

        self.assertEqual(output["updated"], 0)
        mock_save.assert_not_called()
        mock_tg.assert_not_called()


class TestTrailingStopSkipTooHigh(unittest.TestCase):
    """Nouveau stop trop proche du prix courant (>= 98% du prix) -> pas de mise à jour."""

    def test_skip_when_new_stop_too_close_to_current_price(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "sl_order_txid": "SLTX1",
             "entry_price": 1000, "stop_price": 900, "quantity": 1},
        ]
        kraken_scenario = {
            "ticker": {"ETHUSDC": {"c": ["6000.0", "0.01"]}},  # trail_dist=100 -> new_stop=5900 >= 6000*0.98
        }
        output, mock_tg, mock_save, _ = _run_phase0_trailing_stop(history_data, kraken_scenario)

        self.assertEqual(output["updated"], 0)
        mock_save.assert_not_called()
        mock_tg.assert_not_called()


class TestTrailingStopIgnoresPositionsWithoutSl(unittest.TestCase):
    """Une position open sans sl_order_txid n'est pas concernée par le trailing stop."""

    def test_position_without_sl_order_txid_is_skipped(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": 1000,
             "stop_price": 900, "quantity": 1},
        ]
        output, mock_tg, mock_save, _ = _run_phase0_trailing_stop(history_data, kraken_scenario={})

        self.assertEqual(output["updated"], 0)
        mock_save.assert_not_called()
        mock_tg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
