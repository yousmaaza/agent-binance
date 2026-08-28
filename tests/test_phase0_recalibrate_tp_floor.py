"""Test de spécification pour le plancher de viabilité et le plafond absolu du recalibrage TP
(#411, #428).

Le recalibrage automatique du TP (Phase 0) vit dans prompts/phases/phase0_snapshot.txt, bloc
« RECALIBRAGE TP », exécuté par Claude comme raisonnement textuel — ce n'est PAS un script Python
invocable, donc pas testable via unittest de la même façon que phase4_sizing.py/phase5_execution.py
/maker_watcher.py (voir .claude/memory/contrat-prompts-scripts.md : « de la logique métier vit
dans les prompts, hors de portée de tout test »).

Ce module reproduit fidèlement l'algorithme documenté à l'ÉTAPE 3 du bloc RECALIBRAGE TP et
vérifie deux invariants : le TP recalibré ne descend jamais sous le prix d'entrée majoré des frais
aller-retour et d'une marge minimale de gain (plancher, #411), même quand la résistance 4h ou le
plafond absolu max_tp_pct le permettraient ; et il ne dépasse jamais max_tp_pct (plafond absolu,
#428), en plus du plafonnement existant à la résistance 4h. Toute modification de la formule dans
prompts/phases/phase0_snapshot.txt doit être répercutée ici pour que ce test conserve sa valeur de
garde-fou.

Les tests de la classe TestResistance* et TestNoResistance* isolent volontairement le plafond
absolu (max_tp_pct=1.0, hors de portée dans tous les scénarios testés) pour continuer à vérifier
le mécanisme de résistance seul, sans le confondre avec le nouveau plafond absolu — testé
séparément par TestAbsoluteCap*.
"""
import unittest


def _compute_tp_smart(entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=0.06):
    """Reproduit l'ÉTAPE 3 du bloc RECALIBRAGE TP de prompts/phases/phase0_snapshot.txt."""
    stop_distance_pct = (entry_price - stop_price) / entry_price
    tp_mecanique = entry_price * (1 + (stop_distance_pct + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
    tp_plancher = entry_price * (1 + 2 * fee_round_trip_pct)
    tp_plafond_absolu = entry_price * (1 + max_tp_pct)

    tp_candidat = min(tp_mecanique, tp_plafond_absolu)
    if r2_4h is not None and r2_4h > entry_price:
        tp_candidat = min(tp_candidat, r2_4h * 0.98)
    if tp_candidat >= tp_plancher:
        return tp_candidat
    return tp_mecanique


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


class TestFloorPrimesOverAbsoluteCapOnConflict(unittest.TestCase):
    """Si le plafond absolu configuré est plus bas que le plancher de viabilité (#411), c'est le
    plancher qui prime — le plafond est ignoré et la cible mécanique est conservée plutôt qu'une
    cible perdante (issue #428, section « Interaction avec le plancher de viabilité »)."""

    def test_max_tp_pct_below_floor_falls_back_to_mecanique(self):
        entry_price = 100.0
        stop_price = 97.0  # stop_distance_pct = 0.03
        reward_risk_ratio = 1.5
        fee_round_trip_pct = 0.009
        max_tp_pct = 0.01  # plafond absolu (+1%) < plancher (+1.8% = 2 × fee_round_trip_pct)

        tp_plancher = entry_price * (1 + 2 * fee_round_trip_pct)
        tp_plafond_absolu = entry_price * (1 + max_tp_pct)
        self.assertLess(tp_plafond_absolu, tp_plancher)  # le conflit est bien celui testé

        tp_smart = _compute_tp_smart(
            entry_price, stop_price, None, reward_risk_ratio, fee_round_trip_pct, max_tp_pct=max_tp_pct,
        )

        tp_mecanique = entry_price * (1 + (0.03 + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
        self.assertAlmostEqual(tp_smart, tp_mecanique, places=6)
        self.assertGreaterEqual(tp_smart, tp_plancher)


if __name__ == "__main__":
    unittest.main()
