"""Tests d'intégration pour phase4_sizing.py — dimensionnement des ordres + filtres Kraken.

Même approche que test_phase0_profit.py / test_phase1_scan.py : le script lit son input
directement depuis /tmp/cycle_{cycle_id}_phase4_input.json (dont le champ "config" est fourni
tel quel, phase4_sizing.py utilise inp["config"] en priorité sur _load_config()), appelle
`kraken pairs` via le stub fake_kraken.py (core.trade_helpers._EXCHANGE_CLI), et notifie via
tg() (mockée, jamais de vrai curl).

Helpers partagés : voir tests/fixtures/test_harness.py.
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

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE4_SIZING_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase4_sizing.py")

DEFAULT_CONFIG = {
    "risk_per_trade_pct": 0.01,
    "atr_stop_multiplier": 2,
    "reward_risk_ratio": 2,
    "fee_round_trip_pct": 0,  # frais neutralisés par défaut : isole les tests des formules pré-#411
    "max_tp_pct": 1.0,  # plafond absolu neutralisé par défaut : isole les tests du plafond (#428)
    "limit_offset_pct": 0,
    "min_order_usdc": 9,
    "max_single_position_pct": 0.3,
}


def _run_phase4_sizing(buy_candidates, portfolio_total, budget_disponible, config=None, pairs_data=None):
    """Exécute phase4_sizing.py sur un scénario donné. Retourne (output_json, mock_tg)."""
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase4_input.json"
    out_path = f"/tmp/cycle_{cycle_id}_phase4_output.json"
    scenario_path = harness.write_kraken_scenario({"pairs": pairs_data or {}})

    input_data = {
        "buy_candidates": buy_candidates,
        "portfolio_total": portfolio_total,
        "budget_disponible": budget_disponible,
        "config": config if config is not None else DEFAULT_CONFIG,
    }
    with open(in_path, "w") as f:
        json.dump(input_data, f)

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))

            harness.exec_phase_script(PHASE4_SIZING_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        return output, mock_tg
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(in_path, out_path, scenario_path)


class TestStopCalculationFromAtrMultiplier(unittest.TestCase):
    """prix_stop = prix_entry * (1 - atr_pct * atr_stop_multiplier)."""

    def test_stop_price_uses_atr_stop_multiplier(self):
        candidates = [{"coin": "ETH", "prix_actuel": 2000, "atr_pct": 0.02, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2)
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10000, budget_disponible=100000, config=config)

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # stop_distance_pct = 0.02 * 2 = 0.04 -> prix_stop = 2000 * 0.96 = 1920
        self.assertAlmostEqual(order["prix_stop"], 1920.0, places=6)
        self.assertAlmostEqual(order["stop_distance_pct"], 0.04, places=6)


class TestTpCalculationFromRewardRiskRatio(unittest.TestCase):
    """prix_tp = prix_entry * (1 + atr_pct * atr_stop_multiplier * reward_risk_ratio) (frais nuls)."""

    def test_tp_price_uses_reward_risk_ratio(self):
        candidates = [{"coin": "ETH", "prix_actuel": 2000, "atr_pct": 0.02, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2, reward_risk_ratio=3)
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10000, budget_disponible=100000, config=config)

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # stop_distance_pct = 0.04, fee_round_trip_pct=0 -> prix_tp = 2000 * (1 + 0.04 * 3) = 2240
        self.assertAlmostEqual(order["prix_tp"], 2240.0, places=6)


class TestTpCalculationNetOfFees(unittest.TestCase):
    """prix_tp = prix_entry * (1 + (stop_distance_pct + fee_round_trip_pct) * reward_risk_ratio
    + fee_round_trip_pct) — le gain net vise reward_risk_ratio × la perte nette (#411)."""

    def test_tp_price_integrates_fee_round_trip_pct(self):
        candidates = [{"coin": "ETH", "prix_actuel": 1000, "atr_pct": 0.015, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2, reward_risk_ratio=1.5, fee_round_trip_pct=0.009)
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10000, budget_disponible=100000, config=config)

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # stop_distance_pct = 0.03 -> prix_tp = 1000 * (1 + (0.03+0.009)*1.5 + 0.009) = 1000 * 1.0675
        self.assertAlmostEqual(order["prix_tp"], 1067.5, places=6)


class TestSizingBudgetsFeesIntoRiskUsdc(unittest.TestCase):
    """quantite = risk_usdc / (prix_entry * (stop_distance_pct + fee_round_trip_pct)) (#411) — la
    perte réelle (stop + frais) doit rentrer dans le budget de risque, pas seulement le glissement
    de prix au stop."""

    def test_quantity_accounts_for_fee_round_trip_pct(self):
        candidates = [{"coin": "ETH", "prix_actuel": 1000, "atr_pct": 0.015, "score": 8}]
        config = dict(DEFAULT_CONFIG, risk_per_trade_pct=0.01, atr_stop_multiplier=2, fee_round_trip_pct=0.009)
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10000, budget_disponible=100000, config=config)

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # risk_usdc = 100, stop_distance_pct = 0.03 -> quantite = 100 / (1000 * (0.03+0.009)) = 2.5641...
        self.assertAlmostEqual(order["quantite"], 100 / (1000 * 0.039), places=6)


class TestMinOrderUsdcFilter(unittest.TestCase):
    """Montant d'ordre calculé sous min_order_usdc -> skip."""

    def test_order_below_min_order_usdc_is_skipped(self):
        candidates = [{"coin": "ETH", "prix_actuel": 2000, "atr_pct": 0.02, "score": 5}]
        # portfolio_total minuscule -> risk_usdc minuscule -> montant_ordre << min_order_usdc
        config = dict(DEFAULT_CONFIG, min_order_usdc=9)
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10, budget_disponible=100000, config=config)

        self.assertEqual(output["ordres_prepares"], [])
        self.assertEqual(len(output["skipped"]), 1)
        self.assertEqual(output["skipped"][0]["coin"], "ETH")
        self.assertIn("seuil", output["skipped"][0]["reason"])


class TestOrderMinCostMinFilter(unittest.TestCase):
    """Filtre ordermin/costmin retourné par `kraken pairs` -> skip si sous le minimum."""

    def test_quantity_below_ordermin_is_skipped(self):
        candidates = [{"coin": "ETH", "prix_actuel": 2000, "atr_pct": 0.02, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2)
        pairs_data = {"ETHUSDC": {"lot_decimals": 8, "ordermin": "2.0", "costmin": "5.0"}}
        output, _ = _run_phase4_sizing(
            candidates, portfolio_total=10000, budget_disponible=100000, config=config, pairs_data=pairs_data,
        )

        # quantite calculée ~1.25 < ordermin 2.0
        self.assertEqual(output["ordres_prepares"], [])
        self.assertEqual(len(output["skipped"]), 1)
        self.assertIn("ordermin", output["skipped"][0]["reason"])

    def test_amount_below_costmin_is_skipped(self):
        candidates = [{"coin": "ETH", "prix_actuel": 2000, "atr_pct": 0.02, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2)
        # montant_ordre ~2500 USDC < costmin 3000
        pairs_data = {"ETHUSDC": {"lot_decimals": 8, "ordermin": "0", "costmin": "3000"}}
        output, _ = _run_phase4_sizing(
            candidates, portfolio_total=10000, budget_disponible=100000, config=config, pairs_data=pairs_data,
        )

        self.assertEqual(output["ordres_prepares"], [])
        self.assertEqual(len(output["skipped"]), 1)
        self.assertIn("costmin", output["skipped"][0]["reason"])


class TestLotDecimalsRounding(unittest.TestCase):
    """La quantité est arrondie à l'inférieur (floor) au pas défini par lot_decimals."""

    def test_quantity_floored_to_lot_decimals_step(self):
        candidates = [{"coin": "ETH", "prix_actuel": 1000, "atr_pct": 0.03, "score": 8}]
        config = dict(DEFAULT_CONFIG, risk_per_trade_pct=0.01, atr_stop_multiplier=2)
        pairs_data = {"ETHUSDC": {"lot_decimals": 2, "ordermin": "0.01", "costmin": "5.0"}}
        output, _ = _run_phase4_sizing(
            candidates, portfolio_total=10000, budget_disponible=100000, config=config, pairs_data=pairs_data,
        )

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # risk_usdc=100, stop_distance_pct=0.06 -> quantite brute = 100/(1000*0.06) = 1.6666...
        # floor à 2 décimales -> 1.66 (pas un round naïf qui donnerait 1.67)
        self.assertAlmostEqual(order["quantite"], 1.66, places=6)


class TestMaxTpPctCapsWideStopTarget(unittest.TestCase):
    """Plafond absolu (#428) : un stop large produit une cible mécanique au-dessus de max_tp_pct
    -> la cible finale est ramenée au plafond."""

    def test_wide_stop_tp_capped_to_max_tp_pct(self):
        candidates = [{"coin": "ETH", "prix_actuel": 1000, "atr_pct": 0.035, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2, reward_risk_ratio=1.5,
                      fee_round_trip_pct=0.009, max_tp_pct=0.06)
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10000, budget_disponible=100000, config=config)

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # stop_distance_pct = 0.07 -> tp_mecanique = 1000*(1+(0.079)*1.5+0.009) = 1127.5 (+12.75%)
        # tp_plafond = 1000*1.06 = 1060 < tp_mecanique -> plafond appliqué
        self.assertAlmostEqual(order["prix_tp"], 1060.0, places=6)


class TestMaxTpPctDoesNotAffectLowTarget(unittest.TestCase):
    """Plafond absolu (#428) : une cible mécanique déjà sous max_tp_pct n'est pas modifiée."""

    def test_narrow_stop_tp_unaffected_by_max_tp_pct(self):
        candidates = [{"coin": "ETH", "prix_actuel": 1000, "atr_pct": 0.01, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2, reward_risk_ratio=1.5,
                      fee_round_trip_pct=0.009, max_tp_pct=0.06)
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10000, budget_disponible=100000, config=config)

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # stop_distance_pct = 0.02 -> tp_mecanique = 1000*(1+(0.029)*1.5+0.009) = 1052.5 (+5.25%)
        # sous le plafond de 1060 (+6%) -> inchangé
        self.assertAlmostEqual(order["prix_tp"], 1052.5, places=6)


class TestViabilityFloorPrimesOverMaxTpPctOnConflict(unittest.TestCase):
    """Plafond absolu (#428) vs plancher de viabilité (#411) : si max_tp_pct configuré ramène la
    cible sous le plancher (entrée + 2× frais), le plancher prime — le plafond est ignoré et la
    cible mécanique est conservée plutôt qu'une cible perdante."""

    def test_max_tp_pct_below_floor_falls_back_to_mecanique(self):
        candidates = [{"coin": "ETH", "prix_actuel": 1000, "atr_pct": 0.015, "score": 8}]
        config = dict(DEFAULT_CONFIG, atr_stop_multiplier=2, reward_risk_ratio=1.5,
                      fee_round_trip_pct=0.009, max_tp_pct=0.01)  # plafond +1% < plancher +1.8%
        output, _ = _run_phase4_sizing(candidates, portfolio_total=10000, budget_disponible=100000, config=config)

        self.assertEqual(output["skipped"], [])
        order = output["ordres_prepares"][0]
        # stop_distance_pct = 0.03 -> tp_mecanique = 1000*(1+(0.039)*1.5+0.009) = 1067.5
        # tp_plafond = 1010 < tp_plancher = 1018 -> conflit, le plancher prime, mécanique conservée
        self.assertAlmostEqual(order["prix_tp"], 1067.5, places=6)


if __name__ == "__main__":
    unittest.main()
