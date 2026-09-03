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


class TestBuildWeeklyAnalysisView(unittest.TestCase):
    """#453 — l'analyse rédigée si elle existe et a passé le contrôle, sinon le repli signalé."""

    def test_missing_document_falls_back_with_flag(self):
        view = viewdata.build_weekly_analysis_view(None, "Note déterministe.", "Europe/Paris")
        self.assertTrue(view["is_fallback"])
        self.assertEqual(view["text"], "Note déterministe.")
        self.assertIsNone(view["generated_at"])

    def test_document_without_text_falls_back(self):
        view = viewdata.build_weekly_analysis_view({"_id": "2026-W35"}, "Note déterministe.", "Europe/Paris")
        self.assertTrue(view["is_fallback"])

    def test_valid_document_is_not_flagged_as_fallback(self):
        doc = {
            "text": "Semaine calme, rien de notable.",
            "generated_at": "2026-08-24T00:10:00+00:00",
            "window_days": 7,
            "window_widened": False,
        }
        view = viewdata.build_weekly_analysis_view(doc, "Note déterministe.", "Europe/Paris")
        self.assertFalse(view["is_fallback"])
        self.assertEqual(view["text"], doc["text"])
        self.assertEqual(view["window_days"], 7)
        self.assertFalse(view["window_widened"])
        self.assertIn("02:10", view["generated_at"])  # UTC+2 (été, Europe/Paris)

    def test_widened_window_is_carried_through(self):
        doc = {"text": "Peu de trades.", "generated_at": "2026-08-24T00:10:00+00:00",
               "window_days": 30, "window_widened": True}
        view = viewdata.build_weekly_analysis_view(doc, "Note déterministe.", "Europe/Paris")
        self.assertTrue(view["window_widened"])


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
    def test_summary_splits_idle_acted_and_failed_without_double_counting(self):
        cycles = [
            {"cycle_id": "a", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed", "top_score": 7, "execution": {"executed": 1}},
            {"cycle_id": "b", "timestamp": "2026-08-28T06:00:00+00:00", "status": "error", "top_score": 0, "execution": {"executed": 1}},
            {"cycle_id": "c", "timestamp": "2026-08-28T02:00:00+00:00", "status": "completed", "top_score": 2, "execution": {}},
        ]
        summary = viewdata.cadence_summary(viewdata.build_cadence_band(cycles))
        self.assertEqual((summary["acted"], summary["failed"], summary["idle"]), (1, 1, 1))
        self.assertEqual(summary["acted"] + summary["failed"] + summary["idle"], summary["total"])




class TestPnlByPeriod(unittest.TestCase):
    """#450 — PnL par période dérivé de la courbe cumulée publiée par la Phase 7."""

    CURVE = [
        {"date": "2026-05-22", "cumulative_pnl_usdc": -0.64},
        {"date": "2026-06-03", "cumulative_pnl_usdc": 3.65},
        {"date": "2026-06-19", "cumulative_pnl_usdc": 4.18},
        {"date": "2026-07-11", "cumulative_pnl_usdc": -1.43},
    ]

    def test_first_point_starts_from_zero(self):
        # le premier jour n'a pas de cumul précédent : son PnL est sa valeur cumulée
        day = viewdata.pnl_by_period(self.CURVE, "day")
        self.assertAlmostEqual(day[0]["value"], -0.64)

    def test_following_days_are_differences_of_cumulative(self):
        day = viewdata.pnl_by_period(self.CURVE, "day")
        self.assertAlmostEqual(day[1]["value"], 3.65 - (-0.64))
        self.assertAlmostEqual(day[3]["value"], -1.43 - 4.18)

    def test_months_group_the_days_they_contain(self):
        months = viewdata.pnl_by_period(self.CURVE, "month")
        self.assertEqual([m["key"] for m in months], ["2026-05", "2026-06", "2026-07"])
        self.assertAlmostEqual(months[1]["value"], (3.65 + 0.64) + (4.18 - 3.65))

    def test_sum_of_periods_equals_final_cumulative(self):
        """Garde-fou de cohérence : la somme des barres doit reconstituer le net global affiché
        ailleurs sur la page, sinon le graphe raconte autre chose que l'équation brut/frais/net."""
        final = self.CURVE[-1]["cumulative_pnl_usdc"]
        for granularity in ("day", "month"):
            total = sum(p["value"] for p in viewdata.pnl_by_period(self.CURVE, granularity))
            self.assertAlmostEqual(total, final, places=6, msg=granularity)

    def test_empty_curve_yields_no_period(self):
        self.assertEqual(viewdata.pnl_by_period([], "day"), [])
        self.assertEqual(viewdata.pnl_by_period([], "month"), [])

    def test_single_point_yields_one_period_per_granularity(self):
        curve = [{"date": "2026-08-28", "cumulative_pnl_usdc": 5.0}]
        self.assertEqual(len(viewdata.pnl_by_period(curve, "day")), 1)
        self.assertEqual(len(viewdata.pnl_by_period(curve, "month")), 1)

    def test_labels_are_readable_in_french(self):
        self.assertEqual(viewdata.pnl_by_period(self.CURVE, "day")[0]["label"], "22/05")
        self.assertEqual(viewdata.pnl_by_period(self.CURVE, "month")[0]["label"], "mai 2026")


class TestPnlBars(unittest.TestCase):
    def test_empty_periods_yield_empty_geometry(self):
        self.assertEqual(viewdata.pnl_bars([]), {})

    def test_scale_is_symmetric_around_zero(self):
        """Une perte de 20 et un gain de 10 ne doivent pas produire des barres de même longueur :
        sinon le graphe efface visuellement l'asymétrie entre gains et pertes."""
        geo = viewdata.pnl_bars([{"key": "a", "label": "a", "value": 10.0},
                                 {"key": "b", "label": "b", "value": -20.0}])
        gain, loss = geo["bars"]
        self.assertAlmostEqual(loss["height"] / gain["height"], 2.0, places=4)

    def test_bars_sit_on_the_correct_side_of_the_zero_line(self):
        geo = viewdata.pnl_bars([{"key": "a", "label": "a", "value": 5.0},
                                 {"key": "b", "label": "b", "value": -5.0}])
        gain, loss = geo["bars"]
        self.assertTrue(gain["positive"])
        self.assertAlmostEqual(gain["y"] + gain["height"], geo["zero_y"], places=4)
        self.assertFalse(loss["positive"])
        self.assertAlmostEqual(loss["y"], geo["zero_y"], places=4)

    def test_zero_value_period_stays_visible(self):
        geo = viewdata.pnl_bars([{"key": "a", "label": "a", "value": 0.0},
                                 {"key": "b", "label": "b", "value": 9.0}])
        self.assertGreater(geo["bars"][0]["height"], 0)

    def test_bars_stay_inside_the_viewbox_and_do_not_overlap(self):
        periods = [{"key": str(i), "label": str(i), "value": float(i - 20)} for i in range(41)]
        geo = viewdata.pnl_bars(periods, width=640)
        self.assertGreaterEqual(geo["bars"][0]["x"], 0)
        self.assertLessEqual(geo["bars"][-1]["x"] + geo["bars"][-1]["width"], 640)
        for previous, following in pairwise(geo["bars"]):
            self.assertLessEqual(previous["x"] + previous["width"], following["x"] + 0.01)

    def test_best_and_worst_are_reported_for_the_caption(self):
        geo = viewdata.pnl_bars([{"key": "a", "label": "a", "value": 3.0},
                                 {"key": "b", "label": "b", "value": -7.0},
                                 {"key": "c", "label": "c", "value": 1.0}])
        self.assertEqual(geo["best"]["label"], "a")
        self.assertEqual(geo["worst"]["label"], "b")
        self.assertAlmostEqual(geo["total"], -3.0)




class TestBuildCycleGrid(unittest.TestCase):
    """#450 — la grille part des créneaux attendus, seule façon de voir ce qui n'a jamais tourné."""

    NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

    def _cycle(self, iso, **kw):
        base = {"cycle_id": iso, "timestamp": iso, "status": "completed", "top_score": 5}
        base.update(kw)
        return base

    def test_covers_six_slots_per_day(self):
        grid = viewdata.build_cycle_grid([], days=3, tz_name="UTC", now=self.NOW)
        self.assertEqual(len(grid["columns"]), 3)
        self.assertEqual(len(grid["slot_labels"]), 6)

    def test_absent_cycle_is_reported_missing_not_ignored(self):
        """Le cœur du ticket : un cycle qui n'a jamais démarré n'écrit rien en base. Sans
        partir du calendrier, il serait invisible au lieu d'être signalé."""
        grid = viewdata.build_cycle_grid([], days=2, tz_name="UTC", now=self.NOW)
        self.assertEqual(grid["counts"]["missing"], grid["total"])
        self.assertEqual(grid["ran"], 0)

    def test_cycle_is_matched_to_its_slot(self):
        cycles = [self._cycle("2026-08-29T08:05:09+00:00", execution={"executed": 1})]
        grid = viewdata.build_cycle_grid(cycles, days=1, tz_name="UTC", now=self.NOW)
        states = [c["state"] for c in grid["columns"][0]["cells"] if c]
        self.assertIn("action", states)
        self.assertEqual(grid["counts"]["action"], 1)

    def test_cycle_late_within_tolerance_still_holds_its_slot(self):
        cycles = [self._cycle("2026-08-29T08:50:00+00:00")]
        grid = viewdata.build_cycle_grid(cycles, days=1, tz_name="UTC", now=self.NOW)
        self.assertEqual(grid["counts"]["missing"], grid["total"] - 1)

    def test_cycle_far_from_any_slot_does_not_fill_one(self):
        cycles = [self._cycle("2026-08-29T10:30:00+00:00")]
        grid = viewdata.build_cycle_grid(cycles, days=1, tz_name="UTC", now=self.NOW)
        self.assertEqual(grid["counts"]["missing"], grid["total"])

    def test_error_beats_action_in_the_cell_state(self):
        cycles = [self._cycle("2026-08-29T08:05:00+00:00", status="error", execution={"executed": 1})]
        grid = viewdata.build_cycle_grid(cycles, days=1, tz_name="UTC", now=self.NOW)
        self.assertEqual(grid["counts"]["error"], 1)
        self.assertEqual(grid["counts"]["action"], 0)

    def test_future_slots_of_today_are_neither_missing_nor_counted(self):
        """À 12:00, les créneaux de 12:05, 16:05 et 20:05 ne sont pas encore dus : les compter
        comme manqués ferait chuter le taux d'exécution pour la seule raison qu'il est tôt."""
        grid = viewdata.build_cycle_grid([], days=1, tz_name="UTC", now=self.NOW)
        cells = grid["columns"][0]["cells"]
        self.assertEqual(sum(1 for c in cells if c is None), 3)
        self.assertEqual(grid["total"], 3)   # seuls 00:05, 04:05 et 08:05 sont échus

    def test_slot_labels_use_the_display_timezone(self):
        """Les créneaux sont planifiés en UTC mais s'affichent en heure locale (CLAUDE.md
        règle 6) : à Paris en été, 00:05 UTC se lit 02:05."""
        grid = viewdata.build_cycle_grid([], days=1, tz_name="Europe/Paris", now=self.NOW)
        self.assertEqual(grid["slot_labels"][0], "02:05")
        self.assertEqual(grid["slot_labels"][3], "14:05")

    def test_percentages_are_none_rather_than_zero_when_nothing_ran(self):
        grid = viewdata.build_cycle_grid([], days=1, tz_name="UTC", now=self.NOW)
        self.assertEqual(grid["ran_pct"], 0)
        self.assertIsNone(grid["error_pct"])

    def test_closest_cycle_wins_when_two_land_on_one_slot(self):
        cycles = [
            self._cycle("2026-08-29T08:45:00+00:00", cycle_id="loin"),
            self._cycle("2026-08-29T08:06:00+00:00", cycle_id="proche"),
        ]
        grid = viewdata.build_cycle_grid(cycles, days=1, tz_name="UTC", now=self.NOW)
        ids = [c["cycle_id"] for c in grid["columns"][0]["cells"] if c and c["cycle_id"]]
        self.assertEqual(ids, ["proche"])

    def test_cycle_without_timestamp_is_skipped_without_crashing(self):
        grid = viewdata.build_cycle_grid([{"cycle_id": "x"}], days=1, tz_name="UTC", now=self.NOW)
        self.assertEqual(grid["counts"]["missing"], grid["total"])


class TestDateLabelSpacing(unittest.TestCase):
    def test_never_places_two_labels_side_by_side(self):
        """31/07 et 01/08 sont voisins : la règle hebdomadaire et celle du début de mois
        peuvent se déclencher sur deux colonnes contiguës et se chevaucher à l'écran."""
        columns = [{"is_month_start": i == 8} for i in range(21)]
        viewdata._mark_date_labels(columns)
        marked = [i for i, c in enumerate(columns) if c["show_label"]]
        for previous, following in pairwise(marked):
            self.assertGreaterEqual(following - previous, 3)

    def test_always_labels_the_first_column(self):
        columns = [{"is_month_start": False} for _ in range(10)]
        viewdata._mark_date_labels(columns)
        self.assertTrue(columns[0]["show_label"])




class TestSaleTriggerAndAnomaly(unittest.TestCase):
    """#455 — qui a vendu, et la sortie a-t-elle suivi le plan."""

    def test_trigger_read_from_close_reason_not_from_time(self):
        """Le déclencheur vient du motif : sur 15 ventes du TP watcher, 6 tombaient dans une
        fenêtre de cycle par coïncidence — un rattachement par horodatage serait faux 40 % du
        temps, d'où le refus de le déduire."""
        self.assertEqual(viewdata.sale_trigger("tp_watcher")[0], "watcher")
        self.assertEqual(viewdata.sale_trigger("sl_hit")[0], "kraken")
        self.assertEqual(viewdata.sale_trigger("signal_sell_score3")[0], "cycle")
        self.assertEqual(viewdata.sale_trigger("manual_sell_ios")[0], "manuel")

    def test_unknown_reason_is_named_not_guessed(self):
        self.assertEqual(viewdata.sale_trigger(None)[0], "inconnu")
        self.assertEqual(viewdata.sale_trigger("quelque_chose_de_neuf")[0], "inconnu")

    def test_target_reached_but_sold_by_something_else_is_flagged(self):
        # cas réel : ADA du 21/08, cible franchie mais vendue par le signal
        trade = {"tp_price": 0.203448, "exit_price": 0.207202, "close_reason": "signal_sell_score2"}
        self.assertIn("TP n'a pas déclenché", viewdata.sale_anomaly(trade))

    def test_profit_taking_below_target_is_not_an_anomaly(self):
        """La prise de profit de Phase 0 sort volontairement avant la cible."""
        trade = {"tp_price": 120.0, "exit_price": 105.0, "close_reason": "profit_target_phase0"}
        self.assertIsNone(viewdata.sale_anomaly(trade))

    def test_tp_sale_far_below_target_is_flagged(self):
        trade = {"tp_price": 67240.5, "exit_price": 62484.4, "close_reason": "tp_watcher_cycle"}
        self.assertIn("sous la cible", viewdata.sale_anomaly(trade))

    def test_tiny_slippage_on_tp_is_not_an_anomaly(self):
        trade = {"tp_price": 603.811, "exit_price": 603.798, "close_reason": "tp_watcher"}
        self.assertIsNone(viewdata.sale_anomaly(trade))

    def test_missing_reason_blames_nobody(self):
        """Sans motif enregistré, on ne peut reprocher la sortie à aucun mécanisme."""
        trade = {"tp_price": 10.0, "exit_price": 12.0, "close_reason": None}
        self.assertIsNone(viewdata.sale_anomaly(trade))


class TestSalesWindow(unittest.TestCase):
    NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

    def _trades(self):
        return [
            {"exit_date": "2026-09-02T10:00:00+00:00"},   # 1 jour
            {"exit_date": "2026-08-20T10:00:00+00:00"},   # 14 jours
            {"exit_date": "2026-06-01T10:00:00+00:00"},   # ~94 jours
        ]

    def test_window_keeps_only_recent_sales(self):
        self.assertEqual(len(viewdata.filter_sales_window(self._trades(), "7j", self.NOW)), 1)
        self.assertEqual(len(viewdata.filter_sales_window(self._trades(), "30j", self.NOW)), 2)
        self.assertEqual(len(viewdata.filter_sales_window(self._trades(), "180j", self.NOW)), 3)

    def test_tout_keeps_everything(self):
        self.assertEqual(len(viewdata.filter_sales_window(self._trades(), "tout", self.NOW)), 3)

    def test_unknown_key_does_not_silently_empty_the_list(self):
        self.assertEqual(len(viewdata.filter_sales_window(self._trades(), "n_importe_quoi", self.NOW)), 3)

    def test_sale_without_exit_date_is_dropped_from_a_window(self):
        self.assertEqual(viewdata.filter_sales_window([{"coin": "X"}], "30j", self.NOW), [])


class TestBuildSalesView(unittest.TestCase):
    TRADES = [
        {"coin": "SOL", "entry_date": "2026-08-25T08:00:00+00:00", "exit_date": "2026-08-27T12:00:00+00:00",
         "hold_hours": 52.0, "entry_price": 100.0, "exit_price": 104.0, "tp_price": 104.0, "quantity": 1.0,
         "pnl_gross_usdc": 4.0, "fees_usdc": 1.0, "pnl_usdc": 3.0, "close_reason": "tp_watcher",
         "maker_or_taker": "maker", "fees_estimated": False},
        {"coin": "ADA", "entry_date": "2026-08-20T08:00:00+00:00", "exit_date": "2026-08-21T08:00:00+00:00",
         "hold_hours": 24.0, "entry_price": 0.2, "exit_price": 0.19, "tp_price": 0.22, "quantity": 100.0,
         "pnl_gross_usdc": -1.0, "fees_usdc": 0.5, "pnl_usdc": -1.5, "close_reason": "sl_hit",
         "maker_or_taker": None, "fees_estimated": True},
    ]

    def test_totals_carry_their_effectif(self):
        view = viewdata.build_sales_view(self.TRADES, "UTC")
        self.assertEqual(view["totals"]["count"], 2)
        self.assertEqual(view["totals"]["wins"], 1)
        self.assertAlmostEqual(view["totals"]["net"], 1.5)

    def test_quality_counts_estimated_fees(self):
        view = viewdata.build_sales_view(self.TRADES, "UTC")
        self.assertEqual(view["quality"]["estimated"], 1)
        self.assertEqual(view["quality"]["reliable"], 1)

    def test_triggers_split_cycle_from_outside(self):
        view = viewdata.build_sales_view(self.TRADES, "UTC")
        by_key = {t["key"]: t["n"] for t in view["triggers"]}
        self.assertEqual(by_key, {"watcher": 1, "kraken": 1})

    def test_suspect_row_is_excluded_from_amounts_but_kept_in_net(self):
        """Un prix de sortie impossible creusait 42,57 USDC d'écart entre « retiré − investi »
        et le brut déclaré (#455). Il sort des montants, jamais du résultat."""
        corrupt = {**self.TRADES[1], "coin": "SYN", "entry_price": 0.34, "exit_price": 0.55,
                   "quantity": 200.0, "pnl_usdc": -1.17, "tp_price": 0.39}
        view = viewdata.build_sales_view([self.TRADES[0], corrupt], "UTC")
        self.assertEqual(view["totals"]["excluded_from_amounts"], 1)
        self.assertAlmostEqual(view["totals"]["invested"], 100.0)   # SOL seul
        self.assertAlmostEqual(view["totals"]["net"], 3.0 - 1.17)   # SYN compte quand même

    def test_amounts_are_coherent_with_gross(self):
        view = viewdata.build_sales_view(self.TRADES, "UTC")
        t = view["totals"]
        self.assertAlmostEqual(t["proceeds"] - t["invested"], t["gross"], places=2)

    def test_empty_list_yields_empty_view_without_crashing(self):
        view = viewdata.build_sales_view([], "UTC")
        self.assertEqual(view["rows"], [])
        self.assertEqual(view["totals"], {})

    def test_local_dates_use_the_display_timezone(self):
        view = viewdata.build_sales_view(self.TRADES, "Europe/Paris")
        self.assertEqual(view["rows"][0]["exit_local"], "27/08")

    def test_every_reason_seen_in_production_has_a_label(self):
        """Un motif non cartographié s'affiche brut dans le journal — c'est ainsi que
        signal_sell_score1 et tp_watcher_cycle ont été repérés. Ce test fige la liste connue."""
        for raw in ("sl_hit", "stop_hit", "sl", "tp_watcher", "tp_watcher_cycle",
                    "profit_target_phase0", "signal_sell_score1", "signal_sell_score2",
                    "signal_sell_score3", "protection_exhausted", "manual_sell_ios",
                    "oco_not_found", "oco_filled_detected"):
            self.assertIn(raw, viewdata.CLOSE_REASON_LABELS, raw)
            self.assertIn(raw, viewdata.SALE_TRIGGERS, raw)

    def test_unmapped_reason_shows_raw_rather_than_hiding(self):
        self.assertEqual(viewdata.close_reason_label("motif_inedit"), "motif_inedit")
        self.assertEqual(viewdata.close_reason_label(None), viewdata.UNKNOWN_REASON)

    def test_close_reasons_with_several_names_are_grouped(self):
        """sl_hit, stop_hit et sl sont le même événement : les compter séparément
        fragmenterait le total des stops."""
        trades = [{**self.TRADES[1], "close_reason": r} for r in ("sl_hit", "stop_hit", "sl")]
        view = viewdata.build_sales_view(trades, "UTC")
        self.assertEqual([r["label"] for r in view["reasons"]], ["stop touché"])
        self.assertEqual(view["reasons"][0]["n"], 3)



if __name__ == "__main__":
    unittest.main()
