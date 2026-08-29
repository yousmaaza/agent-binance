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


if __name__ == "__main__":
    unittest.main()
