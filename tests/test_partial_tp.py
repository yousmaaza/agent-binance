"""Tests du profit partiel (#514) : déclenchement (tp_watcher), ordre SL/vente, fin de chasse,
échecs de repose, comptabilité parent/enfant (maker_exit_watcher) et cohérence /perf + dashboard.

Toute référence au CLI Kraken est patchée (core.tp_watcher._cli et core.maker_exit_watcher._cli
pointent sur la même doublure) : aucun ordre réel n'est jamais passé.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from commands import perf  # noqa: E402
from core import dashboard_state, maker_exit_watcher, tp_watcher  # noqa: E402
from core.position_helpers import fold_partial_trades  # noqa: E402
from core.trade_helpers import initial_stop_price  # noqa: E402

CFG = {
    "maker_exit_enabled": True, "breakeven_enabled": True, "breakeven_trigger_pct": 0.015,
    "breakeven_include_fees": True, "fee_round_trip_pct": 0.009, "min_order_usdc": 9,
    "partial_tp_enabled": True, "partial_tp_trigger_pct": 0.03, "partial_tp_fraction": 0.33,
    "maker_exit_timeout_seconds": 600, "maker_exit_max_concession_pct": 0.003,
}


def _pos(**kw):
    p = {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": 1000.0, "quantity": 1.0,
         "stop_price": 930.0, "tp_price": 1100.0, "sl_order_txid": "SL_OLD", "risk_usdc": 79.0,
         "entry_fee_usdc": 3.0, "date": "2026-10-01T00:00:00Z", "maker_or_taker": "maker",
         "maker_fill_seconds": 120}
    p.update(kw)
    return p


def _be_pos(**kw):
    """Position dont le break-even (1,5 %) a déjà été appliqué, cas nominal avant le partiel à 3 %."""
    return _pos(breakeven_applied=True, stop_price=1009.0, sl_order_txid="SL_BE", **kw)


class _Cli:
    """Doublure de binance(), partagée par tp_watcher et maker_exit_watcher."""

    def __init__(self, price=1031.0, sl_fail_at=(), limit_fails=False, cancel_fail_ids=(), orders=None,
                 ordermin="0.01"):
        self.price = price
        self.calls = []
        self.sl_fail_at = set(sl_fail_at)  # rangs (1, 2, ...) des poses de stop-loss qui échouent
        self.limit_fails = limit_fails
        self.cancel_fail_ids = set(cancel_fail_ids)
        self.orders = orders or {}
        self.ordermin = ordermin
        self.sl_seq = 0

    def __call__(self, *args, **_kw):
        self.calls.append(args)
        if args[0] == "ticker":
            return json.dumps({"ETHUSDC": {"c": [str(self.price), "1"], "a": [str(self.price + 0.5), "1"]}})
        if args[0] == "pairs":
            return json.dumps({"ETHUSDC": {"lot_decimals": 4, "tick_size": "0.01", "ordermin": self.ordermin}})
        if args[:2] == ("order", "cancel"):
            if args[2] in self.cancel_fail_ids:
                raise RuntimeError("cancel failed")
            return "{}"
        if args[:2] == ("order", "sell") and "stop-loss" in args:
            self.sl_seq += 1
            if self.sl_seq in self.sl_fail_at:
                raise RuntimeError("place failed")
            return json.dumps({"txid": [f"SL_NEW{self.sl_seq}"]})
        if args[:2] == ("order", "sell") and "limit" in args:
            if self.limit_fails:
                raise RuntimeError("post-only rejected")
            return json.dumps({"txid": ["LIM1"]})
        if args[:2] == ("order", "sell"):
            raise AssertionError(f"vente au marché interdite pour un partiel : {args}")
        if args[0] == "query-orders":
            return json.dumps({args[1]: self.orders.get(args[1], {})})
        return "{}"

    def sells(self, kind):
        return [c for c in self.calls if c[:2] == ("order", "sell") and kind in c]

    def index(self, predicate):
        return next(i for i, c in enumerate(self.calls) if predicate(c))


def _tp_tick(history, cli, cfg=CFG, locked=False, pending=None):
    saved = {}
    with patch("core.tp_watcher.is_locked", return_value=locked), \
         patch("core.tp_watcher.acquire_lock"), patch("core.tp_watcher.release_lock"), \
         patch("core.tp_watcher.send_telegram") as tg, \
         patch("core.maker_exit_watcher.send_telegram") as tg2, \
         patch("core.tp_watcher._write_watcher_state"), \
         patch("core.tp_watcher.publish_trade_history_slices"), \
         patch("core.tp_watcher._load_config", return_value=cfg), \
         patch("core.tp_watcher.load_trade_history", return_value=history), \
         patch("core.tp_watcher.save_trade_history"), \
         patch("core.tp_watcher.load_maker_exit_pending_orders", return_value=list(pending or [])), \
         patch("core.tp_watcher.save_maker_exit_pending_orders", side_effect=lambda d: saved.update(p=d)), \
         patch("core.tp_watcher._cli", side_effect=cli), \
         patch("core.maker_exit_watcher._cli", side_effect=cli):
        tp_watcher._tp_watcher_tick()
    return saved.get("p"), tg, tg2


def _exit_tick(pending, history, cli):
    saved = {}
    with patch("core.maker_exit_watcher.is_locked", return_value=False), \
         patch("core.maker_exit_watcher.acquire_lock"), patch("core.maker_exit_watcher.release_lock"), \
         patch("core.maker_exit_watcher.send_telegram") as tg, \
         patch("core.maker_exit_watcher._write_watcher_state"), \
         patch("core.maker_exit_watcher.time.sleep"), \
         patch("core.maker_exit_watcher.publish_trade_history_slices"), \
         patch("core.maker_exit_watcher.load_trade_history", return_value=history), \
         patch("core.maker_exit_watcher.save_trade_history"), \
         patch("core.maker_exit_watcher.load_maker_exit_pending_orders", return_value=pending), \
         patch("core.maker_exit_watcher.save_maker_exit_pending_orders", side_effect=lambda d: saved.update(p=d)), \
         patch("core.maker_exit_watcher._cli", side_effect=cli):
        maker_exit_watcher._maker_exit_watcher_tick(CFG)
    return saved.get("p"), tg


def _pending(**kw):
    p = {"trade_id": "T1", "coin": "ETH", "pair": "ETHUSDC", "txid": "LIM1", "quantity": 0.33,
         "reliquat_qty": 0.67, "partial": True, "stop_price": 1009.0, "close_reason": "partial_tp",
         "initial_limit_price": 1031.5, "current_limit_price": 1031.5, "adjustments": 0,
         "placed_at": datetime.now(timezone.utc).isoformat(), "cycle_id": None}
    p.update(kw)
    return p


class TestTrigger(unittest.TestCase):
    def test_below_trigger_no_partial(self):
        pos = _pos(breakeven_applied=True)
        cli = _Cli(price=1025.0)
        pend, _, _ = _tp_tick([pos], cli)
        self.assertIsNone(pend)
        self.assertNotIn("partial_tp_done", pos)
        self.assertFalse(cli.sells("limit"))

    def test_at_trigger_places_partial(self):
        pos = _pos()
        pend, tg, tg2 = _tp_tick([pos], _Cli(price=1031.0))
        self.assertEqual(len(pend), 1)
        self.assertTrue(pend[0]["partial"])
        self.assertAlmostEqual(pend[0]["quantity"], 0.33)
        self.assertAlmostEqual(pend[0]["reliquat_qty"], 0.67)
        self.assertTrue(pos["partial_tp_done"])

    def test_already_done_is_not_retriggered(self):
        pos = _pos(partial_tp_done=True, breakeven_applied=True, stop_price=1009.0)
        cli = _Cli(price=1050.0)
        pend, _, _ = _tp_tick([pos], cli)
        self.assertIsNone(pend)
        self.assertEqual([c[0] for c in cli.calls], ["ticker"])

    def test_locked_does_nothing(self):
        pos = _pos(breakeven_applied=True, stop_price=1009.0)
        cli = _Cli(price=1050.0)
        # is_locked() vrai dès le début du tick : aucun appel, y compris ticker
        _tp_tick([pos], cli, locked=True)
        self.assertEqual(cli.calls, [])

    def test_position_with_maker_exit_in_progress_is_skipped(self):
        pos = _pos()
        cli = _Cli(price=1050.0)
        _tp_tick([pos], cli, pending=[{"trade_id": "T1", "txid": "X"}])
        self.assertEqual(cli.calls, [])

    def test_disabled(self):
        pos = _pos(breakeven_applied=True, stop_price=1009.0)
        cli = _Cli(price=1050.0)
        _tp_tick([pos], cli, cfg={**CFG, "partial_tp_enabled": False})
        self.assertEqual([c[0] for c in cli.calls], ["ticker"])

    def test_requires_maker_exit(self):
        pos = _pos(breakeven_applied=True, stop_price=1009.0)
        cli = _Cli(price=1050.0)
        _tp_tick([pos], cli, cfg={**CFG, "maker_exit_enabled": False})
        self.assertEqual([c[0] for c in cli.calls], ["ticker"])


class TestMinimums(unittest.TestCase):
    def test_fraction_below_lot_minimum_is_skipped(self):
        pos = _pos(quantity=0.02, breakeven_applied=True, stop_price=1009.0)  # 0,33 x 0,02 = 0,0066 < 0,01
        cli = _Cli(price=1050.0)
        pend, _, _ = _tp_tick([pos], cli)
        self.assertIsNone(pend)
        self.assertTrue(pos["partial_tp_done"])
        self.assertEqual(pos["partial_tp_skipped"], "below_min")
        self.assertFalse(any(c[:2] == ("order", "cancel") for c in cli.calls))  # stop jamais touché
        self.assertEqual(pos["sl_order_txid"], "SL_OLD")

    def test_fraction_below_min_order_usdc_is_skipped(self):
        pos = _pos(quantity=0.02, breakeven_applied=True, stop_price=1009.0)
        cli = _Cli(price=1050.0, ordermin="0.0001")  # lot OK mais 0,0066 x 1050 = 6,9 USDC < 9
        pend, _, _ = _tp_tick([pos], cli)
        self.assertIsNone(pend)
        self.assertEqual(pos["partial_tp_skipped"], "below_min")

    def test_reliquat_below_min_order_usdc_is_skipped(self):
        pos = _pos(quantity=0.0295, breakeven_applied=True, stop_price=1009.0)
        cli = _Cli(price=1050.0, ordermin="0.0001")
        pend, _, _ = _tp_tick([pos], cli, cfg={**CFG, "partial_tp_fraction": 0.7})  # reliquat 0,0089 x 1050 = 9,3 -> OK
        self.assertIsNotNone(pend)
        pos2 = _pos(quantity=0.0270, breakeven_applied=True, stop_price=1009.0)
        pend2, _, _ = _tp_tick([pos2], _Cli(price=1050.0, ordermin="0.0001"), cfg={**CFG, "partial_tp_fraction": 0.7})
        self.assertIsNone(pend2)  # reliquat 0,0081 x 1050 = 8,5 < 9


class TestOrderOfOperations(unittest.TestCase):
    def test_cancel_then_reliquat_stop_then_limit_never_market(self):
        pos = _be_pos()
        cli = _Cli(price=1031.0)
        _tp_tick([pos], cli)
        i_cancel = cli.index(lambda c: c[:3] == ("order", "cancel", "SL_BE"))
        i_stop = cli.index(lambda c: "stop-loss" in c)
        i_limit = cli.index(lambda c: "limit" in c)
        self.assertLess(i_cancel, i_stop)
        self.assertLess(i_stop, i_limit)
        stop_call = cli.sells("stop-loss")[0]
        self.assertEqual(stop_call[3], "0.67")  # stop sur le reliquat
        self.assertAlmostEqual(float(stop_call[stop_call.index("--price") + 1]), 1009.0)  # break-even
        limit_call = cli.sells("limit")[0]
        self.assertEqual(limit_call[3], "0.33")
        self.assertIn("post", limit_call)
        self.assertEqual(pos["sl_order_txid"], "SL_NEW1")
        self.assertTrue(pos["breakeven_applied"])
        self.assertAlmostEqual(pos["initial_stop_price"], 930.0)

    def test_breakeven_not_yet_applied_runs_first_in_same_tick(self):
        pos = _pos()
        cli = _Cli(price=1031.0)
        pend, _, _ = _tp_tick([pos], cli)
        self.assertEqual([s[3] for s in cli.sells("stop-loss")], ["1.0", "0.67"])  # break-even puis reliquat
        self.assertEqual(len(pend), 1)
        self.assertEqual(pos["sl_order_txid"], "SL_NEW2")

    def test_stop_stays_current_when_breakeven_disabled(self):
        pos = _pos()
        cli = _Cli(price=1031.0)
        _tp_tick([pos], cli, cfg={**CFG, "breakeven_enabled": False})
        stop_call = cli.sells("stop-loss")[0]
        self.assertAlmostEqual(float(stop_call[stop_call.index("--price") + 1]), 930.0)

    def test_old_stop_cancel_failure_aborts_without_side_effect(self):
        pos = _be_pos()
        cli = _Cli(price=1031.0, cancel_fail_ids={"SL_BE"})
        pend, _, _ = _tp_tick([pos], cli)
        self.assertIsNone(pend)
        self.assertFalse(cli.sells("stop-loss"))
        self.assertEqual(pos["sl_order_txid"], "SL_BE")
        self.assertNotIn("partial_tp_done", pos)

    def test_new_stop_failure_restores_old_stop_on_full_quantity(self):
        pos = _be_pos()
        cli = _Cli(price=1031.0, sl_fail_at={1})
        pend, _, _ = _tp_tick([pos], cli)
        self.assertIsNone(pend)
        self.assertFalse(cli.sells("limit"))
        restored = cli.sells("stop-loss")[1]
        self.assertEqual(restored[3], "1.0")
        self.assertAlmostEqual(float(restored[restored.index("--price") + 1]), 1009.0)
        self.assertEqual(pos["sl_order_txid"], "SL_NEW2")
        self.assertNotIn("protection_failed", pos)

    def test_both_stops_failing_marks_protection_failed(self):
        pos = _be_pos()
        pend, tg, _ = _tp_tick([pos], _Cli(price=1031.0, sl_fail_at={1, 2}))
        self.assertIsNone(pend)
        self.assertTrue(pos["protection_failed"])
        self.assertIsNone(pos["sl_order_txid"])
        self.assertIn("NON protégée", tg.call_args[0][0])

    def test_limit_post_failure_restores_stop_on_total_quantity(self):
        pos = _be_pos()
        cli = _Cli(price=1031.0, limit_fails=True)
        pend, _, _ = _tp_tick([pos], cli)
        self.assertIsNone(pend)
        stops = cli.sells("stop-loss")
        self.assertEqual([s[3] for s in stops], ["0.67", "1.0"])
        self.assertEqual(pos["sl_order_txid"], "SL_NEW2")
        self.assertEqual(pos["partial_tp_skipped"], "limit_failed")
        self.assertEqual(pos["quantity"], 1.0)

    def test_limit_failure_then_total_stop_failure_falls_back_to_reliquat_stop(self):
        pos = _be_pos()
        cli = _Cli(price=1031.0, limit_fails=True, sl_fail_at={2})
        _tp_tick([pos], cli)
        stops = cli.sells("stop-loss")
        self.assertEqual([s[3] for s in stops], ["0.67", "1.0", "0.67"])
        self.assertEqual(pos["sl_order_txid"], "SL_NEW3")
        self.assertNotIn("protection_failed", pos)

    def test_limit_failure_then_all_stops_failing_marks_protection_failed(self):
        pos = _be_pos()
        _tp_tick([pos], _Cli(price=1031.0, limit_fails=True, sl_fail_at={2, 3}))
        self.assertTrue(pos["protection_failed"])
        self.assertIsNone(pos["sl_order_txid"])


class TestFill(unittest.TestCase):
    FILL = {"status": "closed", "vol_exec": "0.33", "cost": "340.23", "fee": "1.02"}  # 1031,0 x 0,33

    def _run_fill(self, **pos_kw):
        pos = _pos(stop_price=1009.0, breakeven_applied=True, partial_tp_done=True, **pos_kw)
        history = [pos]
        pend, tg = _exit_tick([_pending()], history, _Cli(orders={"LIM1": self.FILL}))
        return history, pos, pend, tg

    def test_child_record(self):
        history, pos, pend, tg = self._run_fill()
        self.assertEqual(pend, [])
        child = history[1]
        self.assertEqual(child["status"], "closed")
        self.assertEqual(child["close_reason"], "partial_tp")
        self.assertEqual(child["parent_trade_id"], "T1")
        self.assertNotEqual(child["trade_id"], "T1")
        self.assertAlmostEqual(child["quantity"], 0.33)
        self.assertAlmostEqual(child["exit_price"], 1031.0)
        self.assertAlmostEqual(child["entry_fee_usdc"], 0.99)  # 3,0 x 0,33
        self.assertAlmostEqual(child["exit_fee_usdc"], 1.02)
        self.assertAlmostEqual(child["fees_usdc"], 2.01)
        self.assertAlmostEqual(child["pnl_gross_usdc"], 10.23)
        self.assertAlmostEqual(child["pnl_usdc"], 8.22)
        self.assertAlmostEqual(child["risk_usdc"], 79.0 * 0.33)
        self.assertEqual(child["exit_maker_or_taker"], "maker")
        self.assertNotIn("sl_order_txid", child)
        self.assertNotIn("maker_fill_seconds", child)
        self.assertIn("💰", tg.call_args[0][0])
        self.assertIn("un tiers", tg.call_args[0][0])
        self.assertIn("ne peut plus perdre", tg.call_args[0][0])

    def test_parent_reduced_in_same_proportion(self):
        history, pos, _, _ = self._run_fill()
        self.assertEqual(pos["status"], "open")
        self.assertAlmostEqual(pos["quantity"], 0.67)
        self.assertAlmostEqual(pos["risk_usdc"], 79.0 * 0.67)
        self.assertAlmostEqual(pos["entry_fee_usdc"], 3.0 * 0.67)
        self.assertTrue(pos["partial_tp_done"])

    def test_totals_conserved(self):
        history, pos, _, _ = self._run_fill()
        self.assertAlmostEqual(history[1]["quantity"] + pos["quantity"], 1.0)
        self.assertAlmostEqual(history[1]["entry_fee_usdc"] + pos["entry_fee_usdc"], 3.0)
        self.assertAlmostEqual(history[1]["risk_usdc"] + pos["risk_usdc"], 79.0)

    def test_initial_stop_price_unchanged_after_reduction(self):
        # sans champ stocké : reconstruction depuis risk_usdc / (entry x qty), invariante au prorata
        pos = _pos(stop_price=1009.0)
        before = initial_stop_price(pos)
        history = [pos]
        _exit_tick([_pending()], history, _Cli(orders={"LIM1": self.FILL}))
        self.assertAlmostEqual(before, 930.0)
        self.assertAlmostEqual(pos["initial_stop_price"], 930.0)
        pos.pop("initial_stop_price")
        self.assertAlmostEqual(initial_stop_price(pos), 930.0)

    def test_parent_final_close_pnl_has_no_double_counted_fee(self):
        history, pos, _, _ = self._run_fill()
        from core.trade_helpers import compute_net_pnl
        net = compute_net_pnl(pos["entry_price"], 1100.0, pos["quantity"], pos["entry_fee_usdc"], 0.5)
        total_fees = net["fees_usdc"] + history[1]["fees_usdc"]
        self.assertAlmostEqual(total_fees, 3.0 + 1.02 + 0.5)

    def test_partial_fill_is_booked_and_remainder_abandoned(self):
        # fin de chasse (délai dépassé) avec 0,10 rempli sur 0,33
        pos = _pos(stop_price=1009.0, breakeven_applied=True, partial_tp_done=True, sl_order_txid="SL_RELIQUAT")
        history = [pos]
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cli = _Cli(orders={"LIM1": {"status": "open", "vol_exec": "0.10", "cost": "103.1", "fee": "0.31"}})
        pend, _ = _exit_tick([_pending(placed_at=old)], history, cli)
        self.assertEqual(pend, [])
        self.assertAlmostEqual(history[1]["quantity"], 0.10)
        self.assertAlmostEqual(pos["quantity"], 0.90)
        stop = cli.sells("stop-loss")[0]
        self.assertEqual(stop[3], "0.9")


class TestChaseFailure(unittest.TestCase):
    def _timed_out(self, cli, **pos_kw):
        pos = _pos(stop_price=1009.0, breakeven_applied=True, partial_tp_done=True, sl_order_txid="SL_RELIQUAT", **pos_kw)
        history = [pos]
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        pend, tg = _exit_tick([_pending(placed_at=old)], history, cli)
        return history, pos, pend, tg

    def test_timeout_abandons_fraction_without_market_sell(self):
        cli = _Cli(orders={"LIM1": {"status": "open", "vol_exec": "0", "cost": "0", "fee": "0"}})
        history, pos, pend, tg = self._timed_out(cli)
        self.assertEqual(pend, [])
        self.assertEqual(len(history), 1)  # aucun enregistrement enfant
        self.assertFalse(cli.sells("market"))
        self.assertEqual(pos["quantity"], 1.0)
        # limite annulée, stop du reliquat annulé, stop reposé sur la quantité totale
        self.assertIn(("order", "cancel", "LIM1", "-o", "json", "--yes"), cli.calls)
        self.assertIn(("order", "cancel", "SL_RELIQUAT", "-o", "json", "--yes"), cli.calls)
        stop = cli.sells("stop-loss")[0]
        self.assertEqual(stop[3], "1.0")
        self.assertAlmostEqual(float(stop[stop.index("--price") + 1]), 1009.0)
        self.assertEqual(pos["sl_order_txid"], "SL_NEW1")
        self.assertTrue(pos["partial_tp_done"])

    def test_total_stop_failure_reposes_reliquat_stop(self):
        cli = _Cli(sl_fail_at={1}, orders={"LIM1": {"status": "open"}})
        _, pos, _, tg = self._timed_out(cli)
        self.assertEqual([s[3] for s in cli.sells("stop-loss")], ["1.0", "0.67"])
        self.assertEqual(pos["sl_order_txid"], "SL_NEW2")
        self.assertNotIn("protection_failed", pos)

    def test_all_stop_failures_mark_protection_failed(self):
        cli = _Cli(sl_fail_at={1, 2}, orders={"LIM1": {"status": "open"}})
        _, pos, _, tg = self._timed_out(cli)
        self.assertTrue(pos["protection_failed"])
        self.assertIsNone(pos["sl_order_txid"])
        self.assertIn("NON protégée", tg.call_args[0][0])

    def test_limit_cancel_failure_keeps_order_tracked(self):
        cli = _Cli(cancel_fail_ids={"LIM1"}, orders={"LIM1": {"status": "open"}})
        history, pos, pend, _ = self._timed_out(cli)
        self.assertEqual(len(pend), 1)  # jamais d'ordre vivant orphelin
        self.assertFalse(cli.sells("stop-loss"))
        self.assertEqual(pos["sl_order_txid"], "SL_RELIQUAT")

    def test_externally_cancelled_limit_reprotects_total(self):
        pos = _pos(stop_price=1009.0, breakeven_applied=True, partial_tp_done=True, sl_order_txid="SL_RELIQUAT")
        cli = _Cli(orders={"LIM1": {"status": "canceled", "vol_exec": "0"}})
        pend, _ = _exit_tick([_pending()], [pos], cli)
        self.assertEqual(pend, [])
        self.assertEqual(cli.sells("stop-loss")[0][3], "1.0")
        self.assertFalse(cli.sells("market"))


class TestPerfAndDashboard(unittest.TestCase):
    def _records(self):
        parent = _pos(status="closed", quantity=0.67, pnl_usdc=-5.0, pnl_gross_usdc=-3.0, fees_usdc=2.0,
                      entry_fee_usdc=2.01, exit_fee_usdc=0.0, exit_price=990.0, risk_usdc=52.93,
                      exit_date="2026-10-04T10:00:00Z", close_reason="sl_hit")
        child = _pos(trade_id="T1-partial", parent_trade_id="T1", status="closed", quantity=0.33,
                     pnl_usdc=8.22, pnl_gross_usdc=10.23, fees_usdc=2.01, entry_fee_usdc=0.99,
                     exit_fee_usdc=1.02, exit_price=1031.0, close_reason="partial_tp",
                     exit_date="2026-10-02T10:00:00Z")
        return parent, child

    def test_fold_counts_one_position_with_summed_pnl(self):
        parent, child = self._records()
        folded = fold_partial_trades([parent, child])
        self.assertEqual(len(folded), 1)
        self.assertAlmostEqual(folded[0]["pnl_usdc"], 3.22)
        self.assertAlmostEqual(folded[0]["fees_usdc"], 4.01)
        self.assertAlmostEqual(folded[0]["quantity"], 1.0)
        self.assertEqual(parent["pnl_usdc"], -5.0)  # l'historique n'est pas modifié

    def test_fold_keeps_child_whose_parent_is_still_open(self):
        _, child = self._records()
        self.assertEqual(len(fold_partial_trades([child])), 1)

    def test_run_perf_counts_one_trade_and_sums_pnl(self):
        parent, child = self._records()
        with patch.object(perf, "_load_history", return_value=[parent, child]), \
             patch.object(perf, "_bloc_cycles", return_value=[]), \
             patch.object(perf, "_bloc_watcher", return_value=[]), \
             patch.object(perf, "_bloc_maker", return_value=[]):
            msg = perf.run_perf()
        self.assertIn("1 trades fermés", msg)
        self.assertIn("+3.22 USDC", msg)  # net global = -5,00 + 8,22
        self.assertIn("1W / 0L", msg)  # le trade replié est gagnant au global

    def test_dashboard_financials_wins_per_position_but_sums_exact(self):
        parent, child = self._records()
        fin = dashboard_state._financials([parent, child])
        self.assertEqual(fin["global"]["wins"], 1)
        self.assertEqual(fin["global"]["losses"], 0)
        self.assertAlmostEqual(fin["global"]["net_usdc"], 3.22)
        self.assertEqual(fin["close_reason_counts"]["partial_tp"], 1)
        rows = dashboard_state._closed_trades([parent, child])
        self.assertIn("T1", [r["parent_trade_id"] for r in rows])


if __name__ == "__main__":
    unittest.main()
