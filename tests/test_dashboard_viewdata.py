"""Tests pour dashboard/viewdata.py — mise en forme des documents Mongo pour les templates (#432).

Tests unitaires purs : aucun réseau, aucun Mongo, aucun fichier state/."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "dashboard"))

import viewdata  # noqa: E402


class TestResolveTimezone(unittest.TestCase):
    def test_uses_config_display_timezone_when_present(self):
        state = {"config": {"display_timezone": "America/New_York"}}
        self.assertEqual(viewdata.resolve_timezone(state, "Europe/Paris"), "America/New_York")

    def test_falls_back_to_default_when_absent(self):
        state = {"config": {}}
        self.assertEqual(viewdata.resolve_timezone(state, "Europe/Paris"), "Europe/Paris")

    def test_falls_back_when_config_key_missing_entirely(self):
        self.assertEqual(viewdata.resolve_timezone({}, "Europe/Paris"), "Europe/Paris")


class TestFreshness(unittest.TestCase):
    def test_fresh_document_is_not_stale(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        updated = now - timedelta(minutes=30)
        state = {"updated_at": updated.isoformat(), "cycle_status": "completed", "cycle_id": "c1"}
        f = viewdata.freshness(state, stale_threshold_minutes=300, now=now)
        self.assertFalse(f["is_stale"])
        self.assertAlmostEqual(f["age_minutes"], 30, delta=0.1)

    def test_stale_document_beyond_threshold(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        updated = now - timedelta(hours=6)
        state = {"updated_at": updated.isoformat(), "cycle_status": "error"}
        f = viewdata.freshness(state, stale_threshold_minutes=300, now=now)
        self.assertTrue(f["is_stale"])

    def test_missing_updated_at_is_treated_as_stale(self):
        f = viewdata.freshness({}, stale_threshold_minutes=300)
        self.assertTrue(f["is_stale"])
        self.assertIsNone(f["age_minutes"])


class TestEquityCurvePoints(unittest.TestCase):
    def test_empty_curve_yields_empty_string(self):
        self.assertEqual(viewdata.equity_curve_points([]), "")

    def test_single_point_does_not_crash(self):
        points = viewdata.equity_curve_points([{"date": "2026-08-01", "cumulative_pnl_usdc": 5.0}])
        self.assertEqual(len(points.split(" ")), 1)

    def test_multiple_points_produce_one_coordinate_pair_each(self):
        curve = [
            {"date": "2026-08-01", "cumulative_pnl_usdc": -5.0},
            {"date": "2026-08-02", "cumulative_pnl_usdc": 0.0},
            {"date": "2026-08-03", "cumulative_pnl_usdc": 10.0},
        ]
        points = viewdata.equity_curve_points(curve, width=300, height=80)
        pairs = points.split(" ")
        self.assertEqual(len(pairs), 3)
        for pair in pairs:
            x, y = pair.split(",")
            self.assertGreaterEqual(float(x), 0)
            self.assertLessEqual(float(y), 80)

    def test_flat_curve_does_not_divide_by_zero(self):
        curve = [{"date": "2026-08-01", "cumulative_pnl_usdc": 3.0}, {"date": "2026-08-02", "cumulative_pnl_usdc": 3.0}]
        points = viewdata.equity_curve_points(curve)
        self.assertEqual(len(points.split(" ")), 2)


class TestBuildPositionRow(unittest.TestCase):
    def test_computes_distances_when_price_available(self):
        pos = {"coin": "BTC", "entry_price": 50000, "stop_price": 48000, "tp_price": 55000}
        row = viewdata.build_position_row(pos, price=51000)
        self.assertAlmostEqual(row["distance_to_stop_pct"], (51000 - 48000) / 51000 * 100)
        self.assertAlmostEqual(row["distance_to_target_pct"], (55000 - 51000) / 51000 * 100)
        self.assertAlmostEqual(row["unrealized_pnl_pct"], (51000 - 50000) / 50000 * 100)
        self.assertEqual(row["current_price"], 51000)

    def test_distances_are_none_when_price_unavailable(self):
        pos = {"coin": "BTC", "entry_price": 50000, "stop_price": 48000, "tp_price": 55000}
        row = viewdata.build_position_row(pos, price=None)
        self.assertIsNone(row["distance_to_stop_pct"])
        self.assertIsNone(row["distance_to_target_pct"])
        self.assertIsNone(row["unrealized_pnl_pct"])
        self.assertIsNone(row["current_price"])

    def test_build_positions_maps_prices_by_coin(self):
        positions = [{"coin": "BTC", "entry_price": 1}, {"coin": "ETH", "entry_price": 2}]
        rows = viewdata.build_positions(positions, {"BTC": 1.5})
        by_coin = {r["coin"]: r for r in rows}
        self.assertEqual(by_coin["BTC"]["current_price"], 1.5)
        self.assertIsNone(by_coin["ETH"]["current_price"])


class TestBuildPeriodsTable(unittest.TestCase):
    def test_orders_periods_and_fills_missing_with_defaults(self):
        by_period = {"0_7d": {"net_usdc": 5}, "30d_plus": {"net_usdc": -2}}
        table = viewdata.build_periods_table(by_period)
        self.assertEqual([row["key"] for row in table], ["0_7d", "8_30d", "30d_plus"])
        self.assertEqual(table[1]["label"], "8-30 jours")
        self.assertNotIn("net_usdc", table[1])


class TestBuildMakerSummary(unittest.TestCase):
    def test_computes_fill_percentage_and_capital(self):
        watchers = {
            "maker_watcher": {"total_fills": 3, "total_fallbacks": 1, "total_abandoned": 0},
            "maker_pending_orders": [{"quantity": 2, "current_limit_price": 10}],
        }
        summary = viewdata.build_maker_summary(watchers)
        self.assertEqual(summary["fill_pct"], 75)
        self.assertEqual(summary["capital_immobilise"], 20)
        self.assertEqual(summary["pending_count"], 1)

    def test_no_watcher_activity_yields_none_fill_pct(self):
        summary = viewdata.build_maker_summary({})
        self.assertIsNone(summary["fill_pct"])
        self.assertEqual(summary["capital_immobilise"], 0)


class TestBuildCycleRow(unittest.TestCase):
    def test_flags_action_when_executed_or_pending(self):
        cycle = {"cycle_id": "c1", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed",
                  "execution": {"executed": 1, "pending": 0, "skipped": 2}}
        row = viewdata.build_cycle_row(cycle, tz_name="UTC")
        self.assertTrue(row["has_action"])

    def test_no_action_when_all_skipped(self):
        cycle = {"cycle_id": "c2", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed",
                  "execution": {"executed": 0, "pending": 0, "skipped": 3}}
        row = viewdata.build_cycle_row(cycle, tz_name="UTC")
        self.assertFalse(row["has_action"])


class TestBuildCadenceBand(unittest.TestCase):
    def test_height_scales_with_top_score(self):
        cycles = [
            {"cycle_id": "c1", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed", "top_score": 10, "execution": {"executed": 1}},
            {"cycle_id": "c2", "timestamp": "2026-08-28T06:00:00+00:00", "status": "completed", "top_score": 0, "execution": {}},
        ]
        band = viewdata.build_cadence_band(cycles)
        # ordre chronologique (le plus ancien d'abord) après inversion de l'ordre desc de Mongo
        self.assertEqual(band[0]["cycle_id"], "c2")
        self.assertEqual(band[1]["height_pct"], 100)
        self.assertTrue(band[1]["has_action"])

    def test_zero_score_still_shows_a_visible_bar(self):
        cycles = [{"cycle_id": "c1", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed", "top_score": 0, "execution": {}}]
        band = viewdata.build_cadence_band(cycles)
        self.assertGreater(band[0]["height_pct"], 0)


if __name__ == "__main__":
    unittest.main()
