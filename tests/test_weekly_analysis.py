"""Tests pour core/weekly_analysis.py — analyse hebdomadaire rédigée par Claude (#453).

Le garde-fou numérique est le cœur du ticket : un nombre du texte généré doit toujours être
retrouvé dans les données transmises (exact ou dérivé par somme/pourcentage/différence), sinon
la génération échoue et aucun document n'est écrit — le dashboard retombe sur weekly_note().
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core import weekly_analysis as wa  # noqa: E402


def _iso(days_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _trade(coin="BTC", pnl=1.0, fees=0.1, days_ago=1, close_reason="tp_watcher"):
    return {
        "coin": coin, "status": "closed", "pnl_usdc": pnl, "fees_usdc": fees,
        "exit_date": _iso(days_ago), "close_reason": close_reason,
    }


def _claude_stdout(text=None, cost=0.02, is_error=False):
    return json.dumps({"result": text, "total_cost_usd": cost, "is_error": is_error})


def _claude_process(text=None, cost=0.02, is_error=False, returncode=0, stdout=None):
    return MagicMock(returncode=returncode, stdout=stdout or _claude_stdout(text, cost, is_error), stderr="")


class _WeeklyAnalysisTestCase(unittest.TestCase):
    """Base : historique de trades sur fichier temporaire, jamais le vrai state/trade_history.json."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.history_path = os.path.join(self._tmpdir.name, "trade_history.json")
        self._history_patch = patch.object(wa, "_HISTORY_PATH", self.history_path)
        self._history_patch.start()

    def tearDown(self):
        self._history_patch.stop()
        self._tmpdir.cleanup()

    def _write_history(self, trades):
        with open(self.history_path, "w") as f:
            json.dump(trades, f)


# ---------------------------------------------------------------------------
# Sélection de la fenêtre (élargissement 7j -> 30j)
# ---------------------------------------------------------------------------

class TestSelectWindow(_WeeklyAnalysisTestCase):
    def test_stays_on_7_days_when_enough_trades(self):
        history = [_trade(pnl=1.0, days_ago=i % 6) for i in range(wa.MIN_TRADES_7D)]
        window = wa._select_window(history, datetime.now(timezone.utc))
        self.assertEqual(window["days"], 7)
        self.assertFalse(window["widened"])
        self.assertEqual(len(window["trades"]), wa.MIN_TRADES_7D)

    def test_widens_to_30_days_below_threshold(self):
        history = [_trade(pnl=1.0, days_ago=i) for i in range(wa.MIN_TRADES_7D - 1)]
        window = wa._select_window(history, datetime.now(timezone.utc))
        self.assertEqual(window["days"], 30)
        self.assertTrue(window["widened"])

    def test_widened_window_still_excludes_trades_beyond_30_days(self):
        history = [_trade(pnl=1.0, days_ago=1), _trade(pnl=2.0, days_ago=45)]
        window = wa._select_window(history, datetime.now(timezone.utc))
        self.assertEqual(window["days"], 30)
        self.assertEqual(len(window["trades"]), 1)


# ---------------------------------------------------------------------------
# Verdict de significativité transmis à Claude
# ---------------------------------------------------------------------------

class TestSignificance(unittest.TestCase):
    def test_single_trade_has_no_stdev_and_is_never_conclusive(self):
        sig = wa._significance([_trade(pnl=5.0)])
        self.assertEqual(sig["n"], 1)
        self.assertEqual(sig["mean_usdc"], 5.0)
        self.assertIsNone(sig["stdev_usdc"])
        self.assertFalse(sig["conclusive"])

    def test_small_noisy_sample_is_not_conclusive(self):
        trades = [_trade(pnl=p) for p in (-4.0, 3.5, -2.0, 1.0, -0.5, 2.5)]
        sig = wa._significance(trades)
        self.assertFalse(sig["conclusive"])
        self.assertIsNotNone(sig["n_required_for_significance"])

    def test_consistent_sample_is_conclusive(self):
        trades = [_trade(pnl=p) for p in (5.0, 5.1, 4.9, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0, 5.05)]
        sig = wa._significance(trades)
        self.assertTrue(sig["conclusive"])
        self.assertGreater(sig["ci95_low"], 0)


# ---------------------------------------------------------------------------
# Le garde-fou : contrôle numérique a posteriori
# ---------------------------------------------------------------------------

class TestVerifyNumbers(unittest.TestCase):
    def _payload(self):
        return wa._build_payload(
            window={
                "days": 30, "widened": True,
                "trades": [
                    _trade(coin="TRUMP", pnl=-13.20, fees=0.3, days_ago=5),
                    _trade(coin="BTC", pnl=2.5, fees=0.2, days_ago=2),
                ],
            },
            cycles=[],
            now=datetime.now(timezone.utc),
            week_key="2026-W35",
        )

    def test_no_numbers_in_text_always_passes(self):
        self.assertTrue(wa._verify_numbers("Aucun chiffre ici.", self._payload()))

    def test_number_taken_directly_from_payload_is_accepted(self):
        payload = self._payload()
        text = f"TRUMP a coûté {abs(payload['trades'][0]['pnl_usdc']):.2f} USDC sur un trade."
        self.assertTrue(wa._verify_numbers(text, payload))

    def test_percentage_derived_from_trade_and_aggregate_is_accepted(self):
        payload = self._payload()
        net = payload["aggregate"]["net_usdc"]
        trump_loss = abs(payload["trades"][0]["pnl_usdc"])
        pct = round(abs(trump_loss / net * 100))
        text = f"Cette perte représente {pct}% du recul de la période."
        self.assertTrue(wa._verify_numbers(text, payload))

    def test_sum_of_two_aggregates_is_accepted(self):
        payload = self._payload()
        gross = payload["aggregate"]["gross_usdc"]
        fees = payload["aggregate"]["fees_usdc"]
        text = f"Frais + net donnent {gross + fees:.2f} de brut."
        self.assertTrue(wa._verify_numbers(text, payload))

    def test_invented_unrelated_number_is_rejected(self):
        payload = self._payload()
        text = "La stratégie a rapporté 987654.32 USDC ce mois-ci."
        self.assertFalse(wa._verify_numbers(text, payload))

    def test_plausible_but_unrattachable_number_is_rejected(self):
        """Absence de preuve != preuve de conformité : un nombre 'proche' d'une vraie donnée
        mais qui ne correspond à aucune valeur ni dérivation transmise doit échouer."""
        payload = self._payload()
        text = "Il faudrait environ 110 trades pour conclure, un chiffre inventé ici : 42.17."
        self.assertFalse(wa._verify_numbers(text, payload))


def _realistic_payload(now=None):
    """37 trades sur 30 jours (10 gagnants, 27 perdants -> win_rate ~27%), même ordre de
    grandeur que l'audit qui a mesuré le contrôle initial (#453) : sert à la fois à mesurer la
    couverture du garde-fou et à rejouer le scénario de fabrication démontré."""
    now = now or datetime(2026, 8, 29, tzinfo=timezone.utc)
    trades = [
        _trade(coin=f"W{i}", pnl=round(1.0 + i * 0.2, 2), fees=0.1, days_ago=i, close_reason="tp_watcher")
        for i in range(10)
    ] + [
        _trade(coin=f"L{i}", pnl=round(-0.8 - (i % 5) * 0.3, 2), fees=0.1, days_ago=i % 29, close_reason="sl_hit")
        for i in range(27)
    ]
    cycles = [{"status": "completed", "executed": 1} for _ in range(20)] + [{"status": "error"} for _ in range(3)]
    return wa._build_payload(
        window={"days": 30, "widened": True, "trades": trades},
        cycles=cycles, now=now, week_key="2026-W35",
    )


class TestPercentageGuardStrength(unittest.TestCase):
    """Le garde-fou doit rester une contrainte réelle, pas décorative (#453 — audit post-review :
    un produit croisé de toutes les paires de nombres laissait passer 89% des entiers 0-100 comme
    pourcentage). Sans un test de force, rien n'empêche une future évolution de rouvrir la faille
    — c'est ce qui s'est produit trois fois de suite sur le test #403."""

    def test_integer_percentage_coverage_stays_low(self):
        payload = _realistic_payload()
        _, percentages = wa._allowed_numbers(payload)
        accepted = sum(
            1 for i in range(101)
            if any(abs(i - p) <= wa._PCT_TOLERANCE for p in percentages)
        )
        coverage = accepted / 101
        # Repère historique : le produit croisé initial acceptait 89% des entiers 0-100. Un
        # catalogue de ratios nommés doit rester très en dessous, quel que soit le nombre de
        # trades de la fenêtre (ici 37).
        self.assertLess(coverage, 0.35, f"couverture des entiers 0-100 trop large : {coverage:.0%}")

    def test_named_percentage_catalog_stays_bounded(self):
        """Quelques dizaines de ratios nommés, pas des centaines (demande explicite de la review)."""
        payload = _realistic_payload()
        _, percentages = wa._allowed_numbers(payload)
        self.assertLess(len(percentages), 50)


class TestPercentageGuardRejectsFabrication(unittest.TestCase):
    """Rejoue la démonstration de la review (#453) : un texte qui invente un taux de réussite
    opposé à la réalité (26% réel) doit être rejeté dans son intégralité."""

    def test_fabricated_win_rate_narrative_is_rejected(self):
        payload = _realistic_payload()
        text = (
            "La performance s'améliore nettement : 64% des trades sont désormais gagnants "
            "contre 29% le mois dernier, soit une progression de 35%."
        )
        self.assertFalse(wa._verify_numbers(text, payload))

    def test_fabricated_success_rate_and_maker_coverage_is_rejected(self):
        payload = _realistic_payload()
        text = (
            "Le taux de réussite atteint 73% ce mois-ci, en hausse de 41% sur la période, "
            "et la stratégie maker couvre 88% des entrées."
        )
        self.assertFalse(wa._verify_numbers(text, payload))

    def test_unrelated_money_amount_is_still_rejected(self):
        payload = _realistic_payload()
        text = "Le portefeuille a gagné 812.44 USDC cette semaine."
        self.assertFalse(wa._verify_numbers(text, payload))

    def test_true_win_rate_of_this_payload_is_accepted(self):
        """Contre-épreuve : le vrai taux de réussite (10/37 ≈ 27%) doit, lui, passer."""
        payload = _realistic_payload()
        win_rate = round(payload["aggregate"]["wins"] / payload["aggregate"]["count"] * 100)
        text = f"Le taux de réussite est de {win_rate}% sur la période."
        self.assertTrue(wa._verify_numbers(text, payload))


# ---------------------------------------------------------------------------
# Point d'entrée complet : idempotence, élargissement, repli, absence de données
# ---------------------------------------------------------------------------

class TestRunWeeklyAnalysis(_WeeklyAnalysisTestCase):
    def setUp(self):
        super().setUp()
        self._mongo_uri_patch = patch.object(wa, "MONGO_URI", "mongodb://fake")
        self._mongo_uri_patch.start()
        self.mongo_repo = MagicMock()
        self.mongo_repo.find_weekly_analysis.return_value = None
        self.mongo_repo.find_cycles_since.return_value = []
        self.mongo_repo.save_weekly_analysis.return_value = True
        self._mongo_repo_patch = patch.object(wa, "mongo_repo", self.mongo_repo)
        self._mongo_repo_patch.start()

    def tearDown(self):
        self._mongo_repo_patch.stop()
        self._mongo_uri_patch.stop()
        super().tearDown()

    def test_skips_entirely_without_mongodb_uri(self):
        self._mongo_uri_patch.stop()
        with patch.object(wa, "MONGO_URI", ""), patch("core.weekly_analysis.subprocess.run") as mock_run:
            wa.run_weekly_analysis()
        mock_run.assert_not_called()
        self.mongo_repo.find_weekly_analysis.assert_not_called()
        self._mongo_uri_patch.start()  # évite un double stop() en tearDown

    def test_no_generation_without_any_trade_or_cycle(self):
        self._write_history([])
        with patch("core.weekly_analysis.subprocess.run") as mock_run:
            wa.run_weekly_analysis()
        mock_run.assert_not_called()
        self.mongo_repo.save_weekly_analysis.assert_not_called()

    def test_generates_when_cycles_exist_even_without_trades(self):
        self._write_history([])
        self.mongo_repo.find_cycles_since.return_value = [{"status": "completed", "executed": 0}]
        with patch("core.weekly_analysis.subprocess.run", return_value=_claude_process("Rien de notable.")):
            wa.run_weekly_analysis()
        self.mongo_repo.save_weekly_analysis.assert_called_once()

    def test_widens_window_and_records_it_in_saved_document(self):
        self._write_history([_trade(pnl=1.0, days_ago=2)])  # 1 trade < MIN_TRADES_7D
        with patch("core.weekly_analysis.subprocess.run", return_value=_claude_process("1 trade sur la période.")):
            wa.run_weekly_analysis()
        saved = self.mongo_repo.save_weekly_analysis.call_args[0][0]
        self.assertEqual(saved["window_days"], 30)
        self.assertTrue(saved["window_widened"])

    def test_idempotent_within_the_same_iso_week(self):
        self._write_history([_trade(pnl=1.0, days_ago=1) for _ in range(wa.MIN_TRADES_7D)])
        self.mongo_repo.find_weekly_analysis.return_value = {"_id": "already-there"}
        with patch("core.weekly_analysis.subprocess.run") as mock_run:
            wa.run_weekly_analysis()
            wa.run_weekly_analysis()
        mock_run.assert_not_called()
        self.mongo_repo.save_weekly_analysis.assert_not_called()

    def test_stores_cost_and_data_snapshot_on_success(self):
        self._write_history([_trade(pnl=1.0, days_ago=1) for _ in range(wa.MIN_TRADES_7D)])
        with patch("core.weekly_analysis.subprocess.run", return_value=_claude_process("Semaine calme.", cost=0.03)):
            wa.run_weekly_analysis(trigger="auto")
        saved = self.mongo_repo.save_weekly_analysis.call_args[0][0]
        self.assertEqual(saved["cost_usd"], 0.03)
        self.assertIn("aggregate", saved["data_snapshot"])
        self.assertEqual(saved["trigger"], "auto")

    def test_falls_back_when_claude_exits_nonzero(self):
        self._write_history([_trade(pnl=1.0, days_ago=1) for _ in range(wa.MIN_TRADES_7D)])
        with patch("core.weekly_analysis.subprocess.run", return_value=_claude_process(returncode=1, stdout="")):
            wa.run_weekly_analysis()
        self.mongo_repo.save_weekly_analysis.assert_not_called()

    def test_falls_back_when_claude_reports_is_error(self):
        self._write_history([_trade(pnl=1.0, days_ago=1) for _ in range(wa.MIN_TRADES_7D)])
        with patch("core.weekly_analysis.subprocess.run", return_value=_claude_process("panne", is_error=True)):
            wa.run_weekly_analysis()
        self.mongo_repo.save_weekly_analysis.assert_not_called()

    def test_falls_back_on_claude_timeout(self):
        import subprocess as _subprocess
        self._write_history([_trade(pnl=1.0, days_ago=1) for _ in range(wa.MIN_TRADES_7D)])
        with patch(
            "core.weekly_analysis.subprocess.run",
            side_effect=_subprocess.TimeoutExpired(cmd="claude", timeout=120),
        ):
            wa.run_weekly_analysis()
        self.mongo_repo.save_weekly_analysis.assert_not_called()

    def test_falls_back_when_generated_text_fails_numeric_check(self):
        self._write_history([_trade(pnl=1.0, days_ago=1) for _ in range(wa.MIN_TRADES_7D)])
        with patch(
            "core.weekly_analysis.subprocess.run",
            return_value=_claude_process("La stratégie a rapporté 999999.99 USDC."),
        ):
            wa.run_weekly_analysis()
        self.mongo_repo.save_weekly_analysis.assert_not_called()

    def test_never_raises_even_on_unexpected_internal_error(self):
        """L'analyse est accessoire : une exception inattendue ne doit jamais remonter (#453)."""
        with patch.object(wa, "_load_history", side_effect=RuntimeError("boom")):
            try:
                wa.run_weekly_analysis()
            except Exception as e:  # noqa: BLE001 -- le test vérifie précisément l'absence de levée
                self.fail(f"run_weekly_analysis() a laissé fuir une exception : {e}")



class TestNumberExtractionScope(unittest.TestCase):
    """#458 — le garde-fou rejetait les dates et bloquait 100 % des générations.

    Le contrôle ne porte plus que sur les affirmations financières : un nombre à décimale, ou
    un entier suivi d'une unité. La prose passe."""

    def test_dates_are_not_treated_as_financial_claims(self):
        """C'est le cas qui a fait échouer la génération du 31/08."""
        self.assertEqual(wa._extract_numbers("le 31 août, puis le 07/09"), [])

    def test_durations_are_not_treated_as_financial_claims(self):
        self.assertEqual(wa._extract_numbers("sur 7 jours et les 30 derniers jours"), [])

    def test_percentages_are_still_extracted(self):
        self.assertEqual(wa._extract_numbers("64% des trades"), [64.0])
        self.assertEqual(wa._extract_numbers("64 % des trades"), [64.0])

    def test_amounts_with_a_unit_are_still_extracted(self):
        self.assertEqual(wa._extract_numbers("a gagné 812 USDC"), [812.0])
        self.assertEqual(wa._extract_numbers("perdu 45 $"), [45.0])

    def test_any_decimal_is_extracted_even_without_a_unit(self):
        """Un décimal nu est presque toujours un chiffre financier."""
        self.assertEqual(wa._extract_numbers("écart-type de 3.81"), [3.81])
        self.assertEqual(wa._extract_numbers("net de -11.87 USDC"), [-11.87])

    def test_bare_counts_are_a_documented_gap_not_an_oversight(self):
        """LIMITE ASSUMÉE : un entier nu sous 31 est indistinguable d'un quantième. Ce test
        fige le compromis pour qu'il soit revu sciemment, jamais découvert par surprise."""
        self.assertEqual(wa._extract_numbers("27 trades clôturés"), [])


class TestGuardStillRejectsFabricationAfterLoosening(unittest.TestCase):
    """#458 — assouplir ne doit pas rouvrir la faille démontrée en #453."""

    def _payload(self):
        return _realistic_payload()

    def test_fabricated_win_rate_is_still_rejected(self):
        text = ("La performance s'améliore : 64% des trades sont gagnants "
                "contre 29% le mois dernier.")
        self.assertFalse(wa._verify_numbers(text, self._payload()))

    def test_free_percentages_are_still_rejected(self):
        text = "Le taux atteint 73% ce mois-ci, en hausse de 41%, et le maker couvre 88%."
        self.assertFalse(wa._verify_numbers(text, self._payload()))

    def test_invented_amount_is_still_rejected(self):
        self.assertFalse(wa._verify_numbers("a gagné 812.44 USDC", self._payload()))

    def test_a_text_citing_a_date_now_passes(self):
        """Le scénario exact du 31/08 : une date dans le texte ne doit plus tout bloquer."""
        text = "Cette semaine du 31 août au 7 septembre, sur 7 jours, rien de notable."
        self.assertTrue(wa._verify_numbers(text, self._payload()))




class TestPayloadExposesSubtotals(unittest.TestCase):
    """#465 — le modèle cite naturellement « les stops ont coûté X ». Sans ces sous-totaux dans
    la charge utile, il les recalcule et le contrôle numérique les rejette : deux générations
    consécutives ont échoué ainsi, sur -33.04 puis sur un chiffre non rattachable."""

    TRADES = [
        {"coin": "SOL", "pnl_usdc": 5.0, "fees_usdc": 1.0, "close_reason": "tp_watcher"},
        {"coin": "SOL", "pnl_usdc": -2.0, "fees_usdc": 1.0, "close_reason": "sl_hit"},
        {"coin": "ETH", "pnl_usdc": -3.0, "fees_usdc": 1.0, "close_reason": "sl_hit"},
    ]

    def test_net_grouped_by_close_reason(self):
        grouped = wa._net_by(self.TRADES, lambda t: t.get("close_reason"))
        self.assertAlmostEqual(grouped["sl_hit"]["net_usdc"], -5.0)
        self.assertEqual(grouped["sl_hit"]["count"], 2)

    def test_net_grouped_by_coin(self):
        grouped = wa._net_by(self.TRADES, lambda t: t.get("coin"))
        self.assertAlmostEqual(grouped["SOL"]["net_usdc"], 3.0)
        self.assertEqual(grouped["ETH"]["count"], 1)

    def test_every_subtotal_carries_its_effectif(self):
        """Un total sans son effectif laisse croire à une tendance là où il n'y a qu'un trade."""
        for bucket in wa._net_by(self.TRADES, lambda t: t.get("coin")).values():
            self.assertIn("count", bucket)
            self.assertGreater(bucket["count"], 0)

    def test_missing_close_reason_is_named_not_dropped(self):
        grouped = wa._net_by([{"coin": "X", "pnl_usdc": 1.0}], lambda t: t.get("close_reason") or "non renseignée")
        self.assertIn("non renseignée", grouped)

    def test_subtotals_are_reachable_by_the_numeric_guard(self):
        """Le lien entre les deux : un sous-total cité dans le texte doit passer le contrôle."""
        payload = _realistic_payload()
        payload["by_close_reason"] = wa._net_by(self.TRADES, lambda t: t.get("close_reason"))
        self.assertTrue(wa._verify_numbers("Les stops ont coûté -5.00 USDC.", payload))
        # -777.77 est hors de portée des agrégats : -9.99 avait été choisi d'abord et se
        # trouvait dérivable par combinaison, ce qui rendait l'assertion vide.
        self.assertFalse(wa._verify_numbers("Les stops ont coûté -777.77 USDC.", payload))



if __name__ == "__main__":
    unittest.main()
