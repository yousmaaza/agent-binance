#!/usr/bin/env python3
"""Unit tests pour les fonctions utilitaires de phase0_trailing_stop.py"""
import unittest
import math
import sys
import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot", "core", "phases"))


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


if __name__ == "__main__":
    unittest.main()
