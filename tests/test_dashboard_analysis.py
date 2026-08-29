"""Tests pour dashboard/analysis.py — analyses recalculées à chaque affichage (#432).

Vérifie que les phrases de synthèse ("motif dominant", "tendance") sont dérivées des données
fournies et non des valeurs figées — c'est le piège explicitement signalé par le ticket #432."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "dashboard"))

import analysis  # noqa: E402


class TestBlockingReasons(unittest.TestCase):
    def test_counts_skip_types_across_all_cycles(self):
        cycles = [
            {"decisions": [{"skip_type": "TYPE_A"}, {"skip_type": "TYPE_A"}, {"skip_type": "TYPE_B"}]},
            {"decisions": [{"skip_type": "TYPE_A"}, {"skip_type": None}]},
        ]
        result = analysis.blocking_reasons(cycles)
        by_type = {b["type"]: b["count"] for b in result["breakdown"]}
        self.assertEqual(by_type, {"TYPE_A": 3, "TYPE_B": 1})
        self.assertEqual(result["total"], 4)

    def test_dominant_reason_is_first_and_named_in_comment(self):
        cycles = [{"decisions": [{"skip_type": "TYPE_C"}] * 5 + [{"skip_type": "TYPE_D"}]}]
        result = analysis.blocking_reasons(cycles)
        self.assertEqual(result["breakdown"][0]["type"], "TYPE_C")
        self.assertIn(analysis.SKIP_LABELS["TYPE_C"], result["comment"].lower())

    def test_no_skips_yields_neutral_comment(self):
        result = analysis.blocking_reasons([{"decisions": [{"skip_type": None}]}])
        self.assertEqual(result["breakdown"], [])
        self.assertEqual(result["total"], 0)


class TestReliabilityByPeriod(unittest.TestCase):
    def _cycle(self, days_ago, status="completed", error_type=None):
        ts = (datetime(2026, 8, 28, tzinfo=timezone.utc) - timedelta(days=days_ago)).isoformat()
        return {"timestamp": ts, "status": status, "error_type": error_type}

    def test_progressing_reliability_is_named_explicitly(self):
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        cycles = (
            [self._cycle(1), self._cycle(2), self._cycle(3), self._cycle(6)]  # 7j : 4/4 ok
            + [self._cycle(10, error_type="quota"), self._cycle(15, status="error")]  # 30j : 2 erreurs en plus
        )
        result = analysis.reliability_by_period(cycles, now=now)
        self.assertEqual(result["rate_7d"], 100)
        self.assertLess(result["rate_30d"], 100)
        self.assertIn("progresse", result["comment"])

    def test_declining_reliability_is_named_explicitly(self):
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        cycles = (
            [self._cycle(1, status="error"), self._cycle(2, error_type="quota")]  # 7j : 0/2 ok
            + [self._cycle(20), self._cycle(25), self._cycle(28)]  # 30j : ajoute des cycles ok
        )
        result = analysis.reliability_by_period(cycles, now=now)
        self.assertLess(result["rate_7d"], result["rate_30d"])
        self.assertIn("recule", result["comment"])

    def test_no_recent_cycles_yields_none_rates(self):
        result = analysis.reliability_by_period([], now=datetime(2026, 8, 28, tzinfo=timezone.utc))
        self.assertIsNone(result["rate_7d"])
        self.assertIsNone(result["rate_30d"])
        self.assertIn("Pas assez", result["comment"])

    def test_cycles_without_parsable_timestamp_are_ignored(self):
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        cycles = [{"timestamp": None, "status": "completed"}, self._cycle(1)]
        result = analysis.reliability_by_period(cycles, now=now)
        self.assertEqual(result["count_7d"], 1)



class TestWeeklyNote(unittest.TestCase):
    """#442 — bloc « note de la semaine » de la maquette : entièrement recalculé, jamais figé."""

    def test_reports_closed_trades_of_the_week(self):
        note = analysis.weekly_note(
            {"0_7d": {"count": 7, "net_usdc": -22.97, "gross_usdc": -16.60, "fees_usdc": -6.37}},
            [], {},
        )
        self.assertIn("7 trade(s)", note)
        self.assertIn("-22.97", note)
        self.assertIn("6.37", note)

    def test_says_so_when_nothing_was_closed(self):
        note = analysis.weekly_note({}, [], {})
        self.assertIn("Aucun trade", note)

    def test_counts_cycles_that_acted(self):
        band = [{"has_action": True}, {"has_action": False}, {"has_action": True}]
        note = analysis.weekly_note({}, band, {})
        self.assertIn("2 cycle(s) sur les 3", note)

    def test_mentions_maker_only_when_it_has_activity(self):
        self.assertNotIn("maker", analysis.weekly_note({}, [], {"total": 0}))
        note = analysis.weekly_note({}, [], {"total": 5, "fills": 5, "fallbacks": 0, "abandoned": 0})
        self.assertIn("maker a servi 5 ordre(s)", note)



if __name__ == "__main__":
    unittest.main()
