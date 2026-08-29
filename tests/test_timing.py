"""Tests pour core/timing.py — fmt_local() (#393) : fuseau d'affichage explicite,
indépendant du fuseau de la machine hôte (VPS en Etc/UTC)."""
import os
import sys
import unittest
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from config.app import APP_CONFIG  # noqa: E402
from core.timing import fmt_local, iso_week_key, next_weekly_slot  # noqa: E402


class TestFmtLocal(unittest.TestCase):
    def setUp(self):
        self._original_tz = APP_CONFIG.get("display_timezone")

    def tearDown(self):
        if self._original_tz is None:
            APP_CONFIG.pop("display_timezone", None)
        else:
            APP_CONFIG["display_timezone"] = self._original_tz

    def test_summer_utc_converted_to_paris_cest(self):
        """01/07 10:00 UTC -> 01/07 12:00 (heure d'été Paris, UTC+2)."""
        APP_CONFIG["display_timezone"] = "Europe/Paris"
        dt = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(fmt_local(dt), "01/07 12:00 (heure locale)")

    def test_winter_utc_converted_to_paris_cet(self):
        """01/01 10:00 UTC -> 01/01 11:00 (heure d'hiver Paris, UTC+1)."""
        APP_CONFIG["display_timezone"] = "Europe/Paris"
        dt = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(fmt_local(dt), "01/01 11:00 (heure locale)")

    def test_missing_display_timezone_falls_back_to_astimezone(self):
        """Clé absente de config.json -> repli sur astimezone() sans argument, pas de crash."""
        APP_CONFIG.pop("display_timezone", None)
        dt = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        expected = dt.astimezone().strftime("%d/%m %H:%M") + " (heure locale)"
        self.assertEqual(fmt_local(dt), expected)

    def test_unknown_timezone_falls_back_to_astimezone(self):
        """Fuseau inconnu -> repli sur astimezone() sans argument, pas de crash."""
        APP_CONFIG["display_timezone"] = "Not/AZone"
        dt = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        expected = dt.astimezone().strftime("%d/%m %H:%M") + " (heure locale)"
        self.assertEqual(fmt_local(dt), expected)


class TestIsoWeekKey(unittest.TestCase):
    def test_formats_year_and_zero_padded_week(self):
        self.assertEqual(iso_week_key(datetime(2026, 8, 24, tzinfo=timezone.utc)), "2026-W35")

    def test_first_week_of_year_is_zero_padded(self):
        self.assertEqual(iso_week_key(datetime(2026, 1, 1, tzinfo=timezone.utc)), "2026-W01")


class TestNextWeeklySlot(unittest.TestCase):
    def test_monday_before_slot_returns_today(self):
        now = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)  # lundi 00:00 UTC
        self.assertEqual(next_weekly_slot(now), datetime(2026, 8, 24, 0, 10, tzinfo=timezone.utc))

    def test_monday_after_slot_returns_next_monday(self):
        now = datetime(2026, 8, 24, 0, 15, tzinfo=timezone.utc)  # lundi 00:15 UTC, slot déjà passé
        self.assertEqual(next_weekly_slot(now), datetime(2026, 8, 31, 0, 10, tzinfo=timezone.utc))

    def test_midweek_returns_upcoming_monday(self):
        now = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)  # vendredi
        self.assertEqual(next_weekly_slot(now), datetime(2026, 8, 31, 0, 10, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
