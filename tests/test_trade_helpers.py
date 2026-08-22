"""Tests pour core/trade_helpers.py — compute_net_pnl et maker_or_taker_from_ordertype (#382)."""
import os
import sys
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import compute_net_pnl, maker_or_taker_from_ordertype  # noqa: E402


class TestComputeNetPnl(unittest.TestCase):
    def test_pnl_pct_and_pnl_usdc_have_matching_signs(self):
        """Invariant clé : pnl_pct (net) et pnl_usdc (net) doivent toujours avoir le même signe,
        même quand le brut est positif et le net négatif (frais qui absorbent le gain brut)."""
        net = compute_net_pnl(entry_price=100.0, exit_price=101.0, qty=10.0, entry_fee_usdc=8.0, exit_fee_usdc=8.0)
        # pnl_gross = (101-100)*10 = 10.0 (positif) ; fees = 16.0 -> pnl_usdc net = -6.0 (négatif)
        self.assertGreater(net["pnl_gross_usdc"], 0)
        self.assertLess(net["pnl_usdc"], 0)
        self.assertLess(net["pnl_pct"], 0)
        self.assertEqual((net["pnl_usdc"] > 0), (net["pnl_pct"] > 0))
        self.assertEqual((net["pnl_usdc"] < 0), (net["pnl_pct"] < 0))

    def test_pnl_gross_pct_matches_legacy_price_only_formula(self):
        net = compute_net_pnl(entry_price=1000.0, exit_price=1100.0, qty=1.0, entry_fee_usdc=0, exit_fee_usdc=0)
        self.assertAlmostEqual(net["pnl_gross_pct"], 10.0)
        self.assertAlmostEqual(net["pnl_pct"], 10.0)  # sans frais, net == brut

    def test_pnl_pct_is_net_pnl_over_entry_notional(self):
        net = compute_net_pnl(entry_price=1000.0, exit_price=1100.0, qty=1.0, entry_fee_usdc=5.0, exit_fee_usdc=5.0)
        # pnl_usdc = 100 - 10 = 90 ; notionnel entrée = 1000 -> pnl_pct = 9.0%
        self.assertAlmostEqual(net["pnl_usdc"], 90.0)
        self.assertAlmostEqual(net["pnl_pct"], 9.0)
        self.assertAlmostEqual(net["pnl_gross_pct"], 10.0)

    def test_zero_entry_price_does_not_raise(self):
        net = compute_net_pnl(entry_price=0.0, exit_price=10.0, qty=1.0, entry_fee_usdc=0, exit_fee_usdc=0)
        self.assertEqual(net["pnl_gross_pct"], 0.0)
        self.assertEqual(net["pnl_pct"], 0.0)


class TestMakerOrTakerFromOrdertype(unittest.TestCase):
    def test_market_is_taker(self):
        self.assertEqual(maker_or_taker_from_ordertype("market"), "taker")

    def test_stop_loss_is_taker(self):
        self.assertEqual(maker_or_taker_from_ordertype("stop-loss"), "taker")

    def test_limit_without_post_only_returns_none_not_a_false_taker(self):
        """Pas déductible sans query-trades (le bot n'utilise pas de limit sans post-only),
        donc None plutôt qu'une valeur affirmative fausse."""
        self.assertIsNone(maker_or_taker_from_ordertype("limit"))

    def test_limit_with_post_only_is_maker(self):
        """#388 : un LIMIT post-only rempli est garanti maker par construction — Kraken rejette
        la pose s'il croiserait le carnet, donc tout fill constaté est un maker."""
        self.assertEqual(maker_or_taker_from_ordertype("limit", post_only=True), "maker")

    def test_market_with_post_only_flag_is_still_taker(self):
        """post_only n'a de sens que pour un limit — un market reste taker quel que soit le flag."""
        self.assertEqual(maker_or_taker_from_ordertype("market", post_only=True), "taker")

    def test_unknown_ordertype_returns_none(self):
        self.assertIsNone(maker_or_taker_from_ordertype("something-new"))


if __name__ == "__main__":
    unittest.main()
