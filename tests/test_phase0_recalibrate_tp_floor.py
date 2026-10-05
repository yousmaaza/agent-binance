"""Tests de la règle de cible TP partagée (plancher de viabilité #411, plafond absolu #428,
résistance 4h #516) — core.trade_helpers.compute_tp_target, utilisée à l'entrée (phase 4/5,
maker_watcher) et par le recalibrage Phase 0.

Règle : tp = min(tp_mecanique, entry x (1 + max_tp_pct)), puis min(., résistance x 0.98) si la
résistance dépasse l'entrée ; si cette cible tombe sous le plancher entry x (1 + 2 x frais), la
résistance est ignorée mais le plafond max_tp_pct est conservé (jamais de cible non plafonnée).

Les classes TestResistance* et TestNoResistance* isolent le plafond absolu (max_tp_pct=1.0) pour ne
vérifier que le mécanisme de résistance ; TestAbsoluteCap* le testent séparément.
"""
import os
import sys
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import compute_tp_target  # noqa: E402


def _compute_tp_smart(entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=0.06):
    stop_distance_pct = (entry_price - stop_price) / entry_price
    return compute_tp_target(entry_price, stop_distance_pct, reward_risk_ratio, fee_round_trip_pct,
                             max_tp_pct, r2_4h)


class TestLowResistanceNeverProducesTpBelowFloor(unittest.TestCase):
    """Une résistance basse (proche ou sous l'entrée après le rabais 0.98) ne doit jamais produire
    un tp_smart sous l'entrée majorée des frais + marge minimale — le TP mécanique est conservé."""

    def test_resistance_just_above_entry_falls_back_to_mecanique(self):
        entry_price = 100.0
        stop_price = 97.0  # stop_distance_pct = 0.03
        r2_4h = 100.5  # résistance à peine au-dessus de l'entrée
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009

        tp_smart = _compute_tp_smart(entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct)

        tp_plancher = entry_price * (1 + 2 * fee_round_trip_pct)
        self.assertGreaterEqual(tp_smart, tp_plancher)
        # r2_4h * 0.98 = 98.49 < entry_price -> aurait produit un TP perdant sans le plancher
        self.assertGreater(tp_smart, entry_price)

    def test_xrp_like_case_from_issue_history_would_have_been_rejected(self):
        # Reproduit l'ordre de grandeur du cas XRP du 19/08 cité dans l'issue #411 (TP à -5.28%
        # brut sans plancher) : résistance nettement sous l'entrée majorée du rabais 0.98.
        entry_price = 3.00
        stop_price = 2.91  # stop_distance_pct = 0.03
        r2_4h = 2.90  # r2_4h <= entry_price -> ne passe même pas la garde existante
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009

        # max_tp_pct=1.0 : isole ce test du plafond absolu (#428, testé séparément par
        # TestAbsoluteCap*) pour ne vérifier ici que le mécanisme de plancher/résistance.
        tp_smart = _compute_tp_smart(
            entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=1.0,
        )

        # r2_4h <= entry_price -> branche résistance jamais empruntée, tp_smart = tp_mecanique
        tp_mecanique = entry_price * (1 + (0.03 + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
        self.assertAlmostEqual(tp_smart, tp_mecanique, places=6)
        self.assertGreater(tp_smart, entry_price)


class TestResistanceAboveFloorStillCapsTp(unittest.TestCase):
    """Le plafond de résistance reste appliqué quand il respecte le plancher — ce ticket ne
    supprime pas le plafonnement, il ajoute seulement un garde-fou de rentabilité."""

    def test_resistance_comfortably_above_floor_caps_tp(self):
        entry_price = 100.0
        stop_price = 97.0  # stop_distance_pct = 0.03
        r2_4h = 106.0  # résistance nettement au-dessus, plafond actif
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009

        tp_smart = _compute_tp_smart(entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct)

        tp_mecanique = entry_price * (1 + (0.03 + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
        self.assertAlmostEqual(tp_smart, r2_4h * 0.98, places=6)
        self.assertLess(tp_smart, tp_mecanique)


class TestNoResistanceUsesMecaniqueDirectly(unittest.TestCase):
    def test_no_r2_4h_uses_tp_mecanique(self):
        entry_price = 100.0
        stop_price = 97.0
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009

        # max_tp_pct=1.0 : isole ce test du plafond absolu (#428, testé séparément par
        # TestAbsoluteCap*) pour ne vérifier ici que le passthrough sans résistance.
        tp_smart = _compute_tp_smart(
            entry_price, stop_price, None, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=1.0,
        )

        tp_mecanique = entry_price * (1 + (0.03 + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
        self.assertAlmostEqual(tp_smart, tp_mecanique, places=6)


class TestAbsoluteCapAppliesWhenMecaniqueExceedsIt(unittest.TestCase):
    """Un stop large (issue #428, cas XBT/ETH/ADA/TRUMP) produit une cible mécanique bien
    au-dessus de ce que le marché délivre — le plafond absolu la ramène à max_tp_pct, même sans
    résistance 4h pour la contenir."""

    def test_wide_stop_without_resistance_is_capped_to_max_tp_pct(self):
        entry_price = 100.0
        stop_price = 93.0  # stop_distance_pct = 0.07, comme le cas XBT de l'issue
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009
        max_tp_pct = 0.06

        tp_smart = _compute_tp_smart(
            entry_price, stop_price, None, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=max_tp_pct,
        )

        tp_mecanique = entry_price * (1 + (0.07 + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
        self.assertLess(tp_mecanique, entry_price * 1.13)  # +11.275% -> mécanique bien au-dessus du marché
        self.assertAlmostEqual(tp_smart, entry_price * (1 + max_tp_pct), places=6)
        self.assertLess(tp_smart, tp_mecanique)

    def test_absolute_cap_also_applies_when_resistance_is_far_above_it(self):
        """Le plafond absolu s'ajoute au plafonnement de résistance existant, il ne le remplace
        pas (cf. issue #428) : une résistance haute ne doit pas empêcher le plafond absolu d'agir."""
        entry_price = 100.0
        stop_price = 93.0  # stop_distance_pct = 0.07
        r2_4h = 130.0  # résistance largement au-dessus -> ne contiendrait pas seule la cible
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009
        max_tp_pct = 0.06

        tp_smart = _compute_tp_smart(
            entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=max_tp_pct,
        )

        self.assertAlmostEqual(tp_smart, entry_price * (1 + max_tp_pct), places=6)


class TestAbsoluteCapDoesNotBiteWhenMecaniqueIsAlreadyLow(unittest.TestCase):
    """Un stop serré produit déjà une cible mécanique sous max_tp_pct — le plafond absolu ne doit
    rien changer (préserve les cibles basses qui, d'après l'issue #428, sont les seules à être
    atteintes en pratique)."""

    def test_narrow_stop_tp_unaffected_by_absolute_cap(self):
        entry_price = 100.0
        stop_price = 98.0  # stop_distance_pct = 0.02
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009
        max_tp_pct = 0.06

        tp_smart = _compute_tp_smart(
            entry_price, stop_price, None, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=max_tp_pct,
        )

        tp_mecanique = entry_price * (1 + (0.02 + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
        self.assertLess(tp_mecanique, entry_price * (1 + max_tp_pct))
        self.assertAlmostEqual(tp_smart, tp_mecanique, places=6)


class TestResistanceBelowFloorKeepsAbsoluteCap(unittest.TestCase):
    """#516 : résistance proche -> ignorée, mais le plafond max_tp_pct reste appliqué (avant, la
    cible retombait sur le mécanique non plafonné : résistance proche = cible plus lointaine)."""

    def test_resistance_below_floor_ignored_but_cap_kept(self):
        entry_price = 100.0
        stop_price = 85.0  # stop_distance_pct = 0.15 -> mécanique +24.5%
        tp_smart = _compute_tp_smart(entry_price, stop_price, 101.0, 1.5, 0.009, max_tp_pct=0.06)
        self.assertAlmostEqual(tp_smart, 106.0, places=6)  # 101 x 0.98 = 98.98 < plancher 101.8

    def test_resistance_exactly_at_floor_is_kept(self):
        entry_price = 100.0
        # 0.98 x R = 101.8 pile au plancher -> la résistance mord
        r = 101.8 / 0.98
        tp_smart = _compute_tp_smart(entry_price, 85.0, r, 1.5, 0.009, max_tp_pct=0.06)
        self.assertAlmostEqual(tp_smart, 101.8, places=6)


class TestTargetNeverExceedsAbsoluteCap(unittest.TestCase):
    def test_cap_holds_in_every_branch(self):
        for r in (None, 90.0, 100.5, 102.0, 104.0, 150.0):
            for stop in (99.0, 97.0, 90.0, 80.0):
                tp = _compute_tp_smart(100.0, stop, r, 1.5, 0.009, max_tp_pct=0.06)
                self.assertLessEqual(tp, 106.0 + 1e-9)


class TestMaxTpBelowFloorStillCaps(unittest.TestCase):
    """Un plafond absolu configuré sous le plancher de viabilité reste appliqué (#516 : plus de repli
    sur la cible mécanique non plafonnée)."""

    def test_max_tp_pct_below_floor_still_caps(self):
        tp_smart = _compute_tp_smart(100.0, 97.0, None, 1.5, 0.009, max_tp_pct=0.01)
        self.assertAlmostEqual(tp_smart, 101.0, places=6)


if __name__ == "__main__":
    unittest.main()
