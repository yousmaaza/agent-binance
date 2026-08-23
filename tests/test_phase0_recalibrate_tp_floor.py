"""Test de spécification pour le plancher de viabilité du recalibrage TP (#411).

Le recalibrage automatique du TP (Phase 0) vit dans prompts/phases/phase0_snapshot.txt, bloc
« RECALIBRAGE TP », exécuté par Claude comme raisonnement textuel — ce n'est PAS un script Python
invocable, donc pas testable via unittest de la même façon que phase4_sizing.py/phase5_execution.py
/maker_watcher.py (voir .claude/memory/contrat-prompts-scripts.md : « de la logique métier vit
dans les prompts, hors de portée de tout test »).

Ce module reproduit fidèlement l'algorithme documenté à l'ÉTAPE 3 du bloc RECALIBRAGE TP et
vérifie l'invariant central du plancher : le TP recalibré ne descend jamais sous le prix d'entrée
majoré des frais aller-retour et d'une marge minimale de gain, même quand la résistance 4h le
permettrait. Toute modification de la formule dans prompts/phases/phase0_snapshot.txt doit être
répercutée ici pour que ce test conserve sa valeur de garde-fou.
"""
import unittest


def _compute_tp_smart(entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct):
    """Reproduit l'ÉTAPE 3 du bloc RECALIBRAGE TP de prompts/phases/phase0_snapshot.txt."""
    stop_distance_pct = (entry_price - stop_price) / entry_price
    tp_mecanique = entry_price * (1 + (stop_distance_pct + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
    tp_plancher = entry_price * (1 + 2 * fee_round_trip_pct)

    if r2_4h is not None and r2_4h > entry_price:
        tp_smart_resistance = min(tp_mecanique, r2_4h * 0.98)
        if tp_smart_resistance >= tp_plancher:
            return tp_smart_resistance
        return tp_mecanique
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

        tp_smart = _compute_tp_smart(entry_price, stop_price, r2_4h, reward_risk_ratio, fee_round_trip_pct)

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

        tp_smart = _compute_tp_smart(entry_price, stop_price, None, reward_risk_ratio, fee_round_trip_pct)

        tp_mecanique = entry_price * (1 + (0.03 + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
        self.assertAlmostEqual(tp_smart, tp_mecanique, places=6)


if __name__ == "__main__":
    unittest.main()
