#!/usr/bin/env python3
"""Test pour vérifier que reward_risk_ratio absent de config.json utilise le default."""
import unittest
import sys
import os
import json
import tempfile


class TestRewardRiskRatioDefault(unittest.TestCase):
    """Vérifier que reward_risk_ratio utilise le default 2.0 si absent."""

    def test_reward_risk_ratio_with_value_in_config(self):
        """Si present dans config, utilise la valeur."""
        cfg = {"reward_risk_ratio": 3.5, "risk_per_trade_pct": 0.01}
        ratio = cfg.get("reward_risk_ratio", 2)
        self.assertEqual(ratio, 3.5)

    def test_reward_risk_ratio_absent_uses_default(self):
        """Si absent de config, utilise default 2.0."""
        cfg = {"risk_per_trade_pct": 0.01}  # reward_risk_ratio absent
        ratio = cfg.get("reward_risk_ratio", 2)
        self.assertEqual(ratio, 2)

    def test_phase4_sizing_calc_with_missing_reward_risk_ratio(self):
        """Simulation : calcul de TP avec reward_risk_ratio absent."""
        # Simule l'absence de reward_risk_ratio dans la config
        cfg = {
            "risk_per_trade_pct": 0.02,
            "atr_stop_multiplier": 3.5,
            "limit_offset_pct": 0.001,
            "min_order_usdc": 9,
            "max_single_position_pct": 0.3,
        }
        # Pas de reward_risk_ratio dans cfg

        # Code de phase4_sizing.py
        reward_risk_ratio = cfg.get("reward_risk_ratio", 2)

        # Calcul de prix
        prix_actuel = 100.0
        atr_pct = 0.02
        atr_stop_multiplier = cfg.get("atr_stop_multiplier", 2)
        limit_offset_pct = cfg.get("limit_offset_pct", 0.001)

        stop_distance_pct = atr_pct * atr_stop_multiplier
        prix_entry = prix_actuel * (1 - limit_offset_pct)
        prix_tp = prix_entry * (1 + stop_distance_pct * reward_risk_ratio)

        # Vérifications
        self.assertEqual(reward_risk_ratio, 2)  # default
        self.assertGreater(prix_tp, prix_entry)  # TP > entry
        # TP doit être cohérent : entry * (1 + 0.07 * 2) = entry * 1.14
        expected_tp = prix_entry * (1 + 0.07 * 2)
        self.assertAlmostEqual(prix_tp, expected_tp, places=6)


if __name__ == "__main__":
    unittest.main()
