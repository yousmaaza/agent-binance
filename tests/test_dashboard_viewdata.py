"""Tests pour dashboard/viewdata.py — mise en forme des documents Mongo pour les templates (#432).

Tests unitaires purs : aucun réseau, aucun Mongo, aucun fichier state/."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from itertools import pairwise

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



class TestFormatPrice(unittest.TestCase):
    """#442 — Kraken renvoie des flottantes brutes, illisibles telles quelles."""

    def test_rounds_large_price_to_two_decimals(self):
        self.assertEqual(viewdata.format_price(706.4407567166553), "706.44")

    def test_keeps_significant_digits_below_one(self):
        self.assertEqual(viewdata.format_price(0.0920800000006901), "0.09208")
        self.assertEqual(viewdata.format_price(0.0976048000007315), "0.097605")

    def test_strips_trailing_zeros_below_one(self):
        self.assertEqual(viewdata.format_price(0.05), "0.05")

    def test_zero_does_not_become_empty(self):
        self.assertEqual(viewdata.format_price(0), "0")

    def test_none_is_not_displayed_as_a_number(self):
        self.assertEqual(viewdata.format_price(None), "n/d")

    def test_thousands_are_separated_for_readability(self):
        self.assertEqual(viewdata.format_price(112345.678), "112\u202f345.68")


class TestPositionAge(unittest.TestCase):
    def test_hours_below_two_days(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(viewdata.position_age("2026-08-28T06:00:00+00:00", now), "6 h")

    def test_days_beyond_two_days(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(viewdata.position_age("2026-08-22T12:00:00+00:00", now), "6 j")

    def test_missing_date_yields_none(self):
        self.assertIsNone(viewdata.position_age(None))


class TestTrackGeometry(unittest.TestCase):
    def test_places_price_between_stop_and_target(self):
        pos = {"coin": "BTC", "entry_price": 100, "stop_price": 90, "tp_price": 110}
        row = viewdata.build_position_row(pos, price=95)
        self.assertAlmostEqual(row["track_now_pct"], 25.0)
        self.assertAlmostEqual(row["track_entry_pct"], 50.0)

    def test_clamps_price_beyond_the_target(self):
        pos = {"coin": "BTC", "entry_price": 100, "stop_price": 90, "tp_price": 110}
        row = viewdata.build_position_row(pos, price=130)
        self.assertEqual(row["track_now_pct"], 100.0)

    def test_no_geometry_when_stop_equals_target(self):
        pos = {"coin": "BTC", "entry_price": 100, "stop_price": 100, "tp_price": 100}
        row = viewdata.build_position_row(pos, price=100)
        self.assertIsNone(row["track_now_pct"])

    def test_no_geometry_without_current_price(self):
        pos = {"coin": "BTC", "entry_price": 100, "stop_price": 90, "tp_price": 110}
        row = viewdata.build_position_row(pos, price=None)
        self.assertIsNone(row["track_now_pct"])


class TestEquityCurveGeometry(unittest.TestCase):
    def test_empty_curve_yields_empty_dict(self):
        self.assertEqual(viewdata.equity_curve_geometry([]), {})

    def test_polygon_closes_on_the_zero_line(self):
        curve = [{"cumulative_pnl_usdc": -5.0}, {"cumulative_pnl_usdc": 5.0}]
        geo = viewdata.equity_curve_geometry(curve, width=100, height=50, pad=5)
        first, last = geo["polygon"].split(" ")[0], geo["polygon"].split(" ")[-1]
        self.assertEqual(first.split(",")[1], f"{geo['zero_y']:.1f}")
        self.assertEqual(last.split(",")[1], f"{geo['zero_y']:.1f}")

    def test_zero_line_stays_inside_the_drawing_area(self):
        # courbe entièrement négative : le zéro sort du domaine, il doit être ramené au bord
        curve = [{"cumulative_pnl_usdc": -20.0}, {"cumulative_pnl_usdc": -10.0}]
        geo = viewdata.equity_curve_geometry(curve, width=100, height=50, pad=5)
        self.assertGreaterEqual(geo["zero_y"], 5)
        self.assertLessEqual(geo["zero_y"], 45)

    def test_final_value_is_the_last_point(self):
        curve = [{"cumulative_pnl_usdc": 1.0}, {"cumulative_pnl_usdc": -11.87}]
        self.assertEqual(viewdata.equity_curve_geometry(curve)["final_value"], -11.87)


class TestCadenceGeometry(unittest.TestCase):
    def test_bars_are_laid_out_left_to_right_without_overlap(self):
        cycles = [
            {"cycle_id": f"c{i}", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed",
             "top_score": 5, "execution": {}}
            for i in range(4)
        ]
        band = viewdata.build_cadence_band(cycles)
        xs = [b["x"] for b in band]
        self.assertEqual(xs, sorted(xs))
        for previous, following in pairwise(band):
            self.assertLessEqual(previous["x"] + previous["width"], following["x"] + 0.01)

    def test_last_bar_stays_inside_the_viewbox(self):
        cycles = [{"cycle_id": "c", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed",
                   "top_score": 10, "execution": {}}]
        band = viewdata.build_cadence_band(cycles)
        self.assertLessEqual(band[-1]["x"] + band[-1]["width"], viewdata.CADENCE_VIEWBOX_WIDTH)

    def test_summary_splits_idle_acted_and_failed_without_double_counting(self):
        cycles = [
            {"cycle_id": "a", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed", "top_score": 7, "execution": {"executed": 1}},
            {"cycle_id": "b", "timestamp": "2026-08-28T06:00:00+00:00", "status": "error", "top_score": 0, "execution": {"executed": 1}},
            {"cycle_id": "c", "timestamp": "2026-08-28T02:00:00+00:00", "status": "completed", "top_score": 2, "execution": {}},
        ]
        summary = viewdata.cadence_summary(viewdata.build_cadence_band(cycles))
        self.assertEqual((summary["acted"], summary["failed"], summary["idle"]), (1, 1, 1))
        self.assertEqual(summary["acted"] + summary["failed"] + summary["idle"], summary["total"])



if __name__ == "__main__":
    unittest.main()
