"""Tests d'intégration pour phase7_mongo.py — persistance du cycle en MongoDB.

Le script fait `from pymongo import MongoClient` en interne, une fois par exécution : on
patche l'attribut `pymongo.MongoClient` (module réellement importé, jamais de vraie connexion
Atlas) avant d'exécuter le script, pour que ce `from ... import` récupère la version mockée.
`tg()` est mockée par précaution (appelée uniquement en cas d'erreur Mongo).

Helpers partagés : voir tests/fixtures/test_harness.py. Les tests dashboard_state (#431) ci-dessous
ont besoin d'intercepter plusieurs chemins de lecture (trade_history.json, config.json,
maker_watcher_state.json, tp_watcher_state.json, maker_pending_orders.json) — au-delà de ce que
fake_open_factory (un seul chemin) permet — d'où _fake_open_multi, propre à ce fichier (cf.
docstring de test_harness.py : chaque fichier de test reste responsable de sa propre pile de
patches).
"""
import builtins
import contextlib
import io
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE7_MONGO_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase7_mongo.py")

CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")
MAKER_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "maker_watcher_state.json")
TP_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "tp_watcher_state.json")
MAKER_PENDING_ORDERS_PATH = os.path.join(PROJECT_DIR, "state", "maker_pending_orders.json")

_real_open = builtins.open
_MISSING = object()  # sentinel : force un FileNotFoundError déterministe (indépendant du filesystem réel)


def _fake_open_multi(overrides):
    """Comme harness.fake_open_factory, mais pour plusieurs chemins à la fois (dict abspath -> texte
    ou _MISSING). Tout chemin non listé (fichier d'échange /tmp du script, etc.) passe par le vrai open()."""
    def _fake_open(path, mode="r", *args, **kwargs):
        ap = os.path.abspath(str(path))
        if ap in overrides and "r" in mode:
            val = overrides[ap]
            if val is _MISSING:
                raise FileNotFoundError(ap)
            return io.StringIO(val)
        return _real_open(path, mode, *args, **kwargs)
    return _fake_open


def _run_phase7_dashboard(
    history_data,
    doc=None,
    config_data=None,
    maker_watcher_data=_MISSING,
    tp_watcher_data=_MISSING,
    maker_pending_data=_MISSING,
):
    """Exécute phase7_mongo.py avec un état simulé, retourne le document $set passé à
    db.dashboard_state.update_one (ou None si non appelé)."""
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase7_input.json"
    with open(in_path, "w") as f:
        json.dump({"doc": doc if doc is not None else {"status": "completed"}}, f)

    mock_db = MagicMock()
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)

    overrides = {
        harness.TRADE_HISTORY_PATH: json.dumps(history_data),
        CONFIG_PATH: json.dumps(config_data if config_data is not None else {}),
        MAKER_WATCHER_STATE_PATH: json.dumps(maker_watcher_data) if maker_watcher_data is not _MISSING else _MISSING,
        TP_WATCHER_STATE_PATH: json.dumps(tp_watcher_data) if tp_watcher_data is not _MISSING else _MISSING,
        MAKER_PENDING_ORDERS_PATH: json.dumps(maker_pending_data) if maker_pending_data is not _MISSING else _MISSING,
    }

    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"MONGODB_URI": "mongodb://fake"}))
            stack.enter_context(patch("core.trade_helpers.tg"))
            stack.enter_context(patch("pymongo.MongoClient", return_value=mock_client))
            stack.enter_context(patch("builtins.open", side_effect=_fake_open_multi(overrides)))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

            harness.exec_phase_script(PHASE7_MONGO_PATH, cycle_id)
    finally:
        harness.remove_if_exists(in_path)

    if not mock_db.dashboard_state.update_one.called:
        return None
    _filter, kwargs_set = mock_db.dashboard_state.update_one.call_args[0][:2]
    return kwargs_set["$set"]


def _run_phase7_mongo(doc, mongo_uri, mongo_client=None, mongo_client_side_effect=None):
    """Exécute phase7_mongo.py. Retourne (stdout_text, exit_code, mock_tg, mock_mongo_client)."""
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase7_input.json"
    with open(in_path, "w") as f:
        json.dump({"doc": doc}, f)

    stdout_capture = io.StringIO()
    try:
        with contextlib.ExitStack() as stack:
            # Valeur forcée à une clé *présente* (jamais absente) : core.env._load_env() utilise
            # os.environ.setdefault() au premier import de core.trade_helpers dans le process de
            # test, ce qui écraserait un simple `del` avec la vraie valeur de .env.
            stack.enter_context(patch.dict(os.environ, {"MONGODB_URI": mongo_uri or ""}))
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_mongo_client = stack.enter_context(
                patch(
                    "pymongo.MongoClient",
                    return_value=mongo_client, side_effect=mongo_client_side_effect,
                ),
            )
            stack.enter_context(contextlib.redirect_stdout(stdout_capture))

            exit_code = harness.exec_phase_script(PHASE7_MONGO_PATH, cycle_id)

        return stdout_capture.getvalue(), exit_code, mock_tg, mock_mongo_client
    finally:
        harness.remove_if_exists(in_path)


class TestMongoSkippedWhenUriMissing(unittest.TestCase):
    """MONGODB_URI absent/vide -> aucune connexion tentée, sortie 'skipped'."""

    def test_skips_without_mongodb_uri(self):
        stdout, exit_code, mock_tg, mock_mongo_client = _run_phase7_mongo(
            {"executed": 1}, mongo_uri=None, mongo_client=MagicMock(),
        )

        self.assertIn("PHASE7_MONGO_DONE|status=skipped", stdout)
        self.assertEqual(exit_code, 0)
        mock_mongo_client.assert_not_called()
        mock_tg.assert_not_called()


class TestMongoWriteSucceeds(unittest.TestCase):
    """MongoClient mocké, écriture réussie -> status=ok, upsert appelé avec le bon document."""

    def test_writes_doc_via_upsert_when_uri_set(self):
        mock_db = MagicMock()
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)

        stdout, exit_code, mock_tg, mock_mongo_client = _run_phase7_mongo(
            {"executed": 2}, mongo_uri="mongodb://fake", mongo_client=mock_client,
        )

        self.assertIn("PHASE7_MONGO_DONE|status=ok", stdout)
        self.assertIsNone(exit_code)
        mock_mongo_client.assert_called_once()
        mock_db.cycles.update_one.assert_called_once_with(
            {"_id": ANY}, {"$set": {"executed": 2}}, upsert=True,
        )
        mock_client.close.assert_called_once()
        mock_tg.assert_not_called()


class TestMongoWriteFails(unittest.TestCase):
    """Exception levée par MongoClient -> notification tg(), status=error, exit code 1."""

    def test_notifies_and_exits_nonzero_on_mongo_error(self):
        stdout, exit_code, mock_tg, _mock_mongo_client = _run_phase7_mongo(
            {"executed": 1}, mongo_uri="mongodb://fake",
            mongo_client_side_effect=ConnectionError("boom"),
        )

        self.assertIn("PHASE7_MONGO_DONE|status=error", stdout)
        self.assertEqual(exit_code, 1)
        mock_tg.assert_called_once()
        self.assertIn("Mongo write failed", mock_tg.call_args[0][0])


# ---------------------------------------------------------------------------
# dashboard_state (#431) — instantané dérivé pour un dashboard externe.
# ---------------------------------------------------------------------------

class TestDashboardStateUpsert(unittest.TestCase):
    """Upsert sur un document unique (_id="current"), horodaté, avec l'issue du cycle."""

    def test_upserts_single_document_with_cycle_metadata(self):
        set_doc = _run_phase7_dashboard([], doc={"status": "completed"})

        self.assertIsNotNone(set_doc)
        self.assertEqual(set_doc["_id"], "current")
        self.assertEqual(set_doc["cycle_status"], "completed")
        self.assertIn("cycle_id", set_doc)
        self.assertIn("updated_at", set_doc)
        # updated_at doit être un ISO 8601 UTC parsable et récent (règle CLAUDE.md #6 : interne en UTC).
        updated = datetime.fromisoformat(set_doc["updated_at"])
        self.assertLess(abs((datetime.now(timezone.utc) - updated).total_seconds()), 30)


class TestDashboardStateOpenPositions(unittest.TestCase):
    """Positions ouvertes : coin, entrée, stop, cible, quantité, date d'ouverture, frais d'entrée."""

    def test_open_positions_are_listed_with_expected_fields(self):
        history = [
            {
                "coin": "BTC", "status": "open", "entry_price": 50000, "stop_price": 48000,
                "tp_price": 55000, "quantity": 0.01, "date": "2026-08-20T10:00:00+00:00",
                "entry_fee_usdc": 0.5, "maker_or_taker": "maker",
            },
            {
                "coin": "ETH", "status": "open", "entry_price": 3000, "stop_price": 2800,
                "tp_price": 3400, "quantity": 0.1, "date": "2026-08-21T09:00:00+00:00",
                "entry_fee_usdc": 0.3, "maker_or_taker": "taker",
            },
            {"coin": "XRP", "status": "closed", "entry_price": 0.5, "quantity": 1000},
        ]
        set_doc = _run_phase7_dashboard(history)

        positions = set_doc["open_positions"]
        self.assertEqual(len(positions), 2)
        btc = next(p for p in positions if p["coin"] == "BTC")
        self.assertEqual(btc["entry_price"], 50000)
        self.assertEqual(btc["stop_price"], 48000)
        self.assertEqual(btc["tp_price"], 55000)
        self.assertEqual(btc["quantity"], 0.01)
        self.assertEqual(btc["opened_at"], "2026-08-20T10:00:00+00:00")
        self.assertEqual(btc["entry_fee_usdc"], 0.5)
        self.assertEqual(btc["maker_or_taker"], "maker")
        self.assertNotIn("XRP", [p["coin"] for p in positions])


class TestDashboardStateNoOpenPositions(unittest.TestCase):
    """Aucune position ouverte -> liste vide, pas d'erreur."""

    def test_empty_history_yields_empty_open_positions(self):
        set_doc = _run_phase7_dashboard([])
        self.assertEqual(set_doc["open_positions"], [])

    def test_only_closed_and_cancelled_trades_yield_empty_open_positions(self):
        history = [
            {"coin": "BTC", "status": "closed", "pnl_usdc": 1.0, "fees_usdc": 0.1, "exit_date": "2026-08-01T00:00:00+00:00"},
            {"coin": "ETH", "status": "cancelled"},
        ]
        set_doc = _run_phase7_dashboard(history)
        self.assertEqual(set_doc["open_positions"], [])


class TestDashboardStateFinancials(unittest.TestCase):
    """Agrégats brut/frais/net (global + par tranche), PnL par coin, close_reason, equity curve."""

    def _dates(self):
        now = datetime.now(timezone.utc)
        return {
            "within_7d": now - timedelta(days=2),
            "within_30d": now - timedelta(days=15),
            "beyond_30d": now - timedelta(days=45),
        }

    def test_global_and_period_aggregates(self):
        d = self._dates()
        history = [
            {"coin": "BTC", "status": "closed", "pnl_usdc": 10.0, "fees_usdc": 1.0,
             "close_reason": "tp_watcher", "exit_date": d["within_7d"].isoformat()},
            {"coin": "ETH", "status": "closed", "pnl_usdc": -5.0, "fees_usdc": 0.5,
             "close_reason": "sl_hit", "exit_date": d["within_7d"].isoformat()},
            {"coin": "BTC", "status": "closed", "pnl_usdc": 20.0, "fees_usdc": 2.0,
             "close_reason": "tp_watcher", "exit_date": d["within_30d"].isoformat()},
            {"coin": "SOL", "status": "closed", "pnl_usdc": -8.0, "fees_usdc": 1.0,
             "close_reason": "signal_sell_score3", "exit_date": d["beyond_30d"].isoformat()},
        ]
        set_doc = _run_phase7_dashboard(history)
        fin = set_doc["financials"]

        glob = fin["global"]
        self.assertEqual(glob["net_usdc"], 17.0)
        self.assertEqual(glob["fees_usdc"], 4.5)
        self.assertEqual(glob["gross_usdc"], 21.5)
        self.assertEqual(glob["count"], 4)
        self.assertEqual(glob["wins"], 2)
        self.assertEqual(glob["losses"], 2)
        self.assertEqual(glob["trades_without_fees"], 0)

        by_period = fin["by_period"]
        self.assertEqual(by_period["0_7d"]["net_usdc"], 5.0)
        self.assertEqual(by_period["0_7d"]["count"], 2)
        self.assertEqual(by_period["8_30d"]["net_usdc"], 20.0)
        self.assertEqual(by_period["8_30d"]["count"], 1)
        self.assertEqual(by_period["30d_plus"]["net_usdc"], -8.0)
        self.assertEqual(by_period["30d_plus"]["count"], 1)

        self.assertEqual(fin["pnl_by_coin"], {"BTC": 30.0, "ETH": -5.0, "SOL": -8.0})
        self.assertEqual(
            fin["close_reason_counts"],
            {"tp_watcher": 2, "sl_hit": 1, "signal_sell_score3": 1},
        )

    def test_equity_curve_reduced_to_one_point_per_day(self):
        d = self._dates()
        history = [
            {"coin": "SOL", "status": "closed", "pnl_usdc": -8.0, "fees_usdc": 1.0,
             "exit_date": d["beyond_30d"].isoformat()},
            {"coin": "BTC", "status": "closed", "pnl_usdc": 20.0, "fees_usdc": 2.0,
             "exit_date": d["within_30d"].isoformat()},
            {"coin": "BTC", "status": "closed", "pnl_usdc": 10.0, "fees_usdc": 1.0,
             "exit_date": d["within_7d"].isoformat()},
            {"coin": "ETH", "status": "closed", "pnl_usdc": -5.0, "fees_usdc": 0.5,
             "exit_date": d["within_7d"].isoformat()},
        ]
        set_doc = _run_phase7_dashboard(history)
        curve = set_doc["financials"]["equity_curve"]

        # 4 trades sur 3 jours distincts -> 3 points (un par jour, dernier cumul du jour).
        self.assertEqual(len(curve), 3)
        self.assertEqual(curve[0]["date"], d["beyond_30d"].strftime("%Y-%m-%d"))
        self.assertEqual(curve[0]["cumulative_pnl_usdc"], -8.0)
        self.assertEqual(curve[1]["date"], d["within_30d"].strftime("%Y-%m-%d"))
        self.assertEqual(curve[1]["cumulative_pnl_usdc"], 12.0)
        self.assertEqual(curve[2]["date"], d["within_7d"].strftime("%Y-%m-%d"))
        self.assertEqual(curve[2]["cumulative_pnl_usdc"], 17.0)


class TestDashboardStateTradesWithoutFees(unittest.TestCase):
    """Trades sans fees_usdc (garde-fou de cohérence du backfill, ex. SYN/PENDLE, #431) :
    ne doivent ni planter ni fausser les totaux — comptés à part."""

    def test_missing_fees_treated_as_zero_and_counted_separately(self):
        history = [
            {"coin": "SYN", "status": "closed", "pnl_usdc": -1.1650800000000001, "fees_usdc": None,
             "close_reason": None, "exit_date": "2026-08-01T00:00:00+00:00"},
            {"coin": "PENDLE", "status": "closed", "pnl_usdc": -0.2494, "fees_usdc": None,
             "close_reason": None, "exit_date": "2026-08-02T00:00:00+00:00"},
            {"coin": "BTC", "status": "closed", "pnl_usdc": 10.0, "fees_usdc": 1.0,
             "close_reason": "tp_watcher", "exit_date": "2026-08-03T00:00:00+00:00"},
        ]
        set_doc = _run_phase7_dashboard(history)
        glob = set_doc["financials"]["global"]

        self.assertEqual(glob["trades_without_fees"], 2)
        # net toujours exact (somme de pnl_usdc, jamais affecté par les frais manquants).
        self.assertAlmostEqual(glob["net_usdc"], -1.1650800000000001 - 0.2494 + 10.0)
        # frais connus uniquement (BTC) ; brut = net + frais connus (aucun frais fabriqué pour SYN/PENDLE).
        self.assertEqual(glob["fees_usdc"], 1.0)
        self.assertEqual(set_doc["financials"]["close_reason_counts"]["unknown"], 2)


class TestDashboardStateWatchersAndConfig(unittest.TestCase):
    """État des surveillants (contenu brut des fichiers) + sous-ensemble de config.json."""

    def test_watcher_state_and_pending_orders_passed_through(self):
        maker_watcher = {"total_ticks": 5, "total_fills": 2, "total_fallbacks": 1, "total_abandoned": 0}
        tp_watcher = {"total_ticks": 9}
        pending = [{"coin": "XRP", "quantity": 10, "initial_limit_price": 0.5}]

        set_doc = _run_phase7_dashboard(
            [], maker_watcher_data=maker_watcher, tp_watcher_data=tp_watcher, maker_pending_data=pending,
        )

        self.assertEqual(set_doc["watchers"]["maker_watcher"], maker_watcher)
        self.assertEqual(set_doc["watchers"]["tp_watcher"], tp_watcher)
        self.assertEqual(set_doc["watchers"]["maker_pending_orders"], pending)

    def test_watcher_state_absent_defaults_gracefully(self):
        set_doc = _run_phase7_dashboard([])  # maker/tp watcher + pending non fournis -> _MISSING

        self.assertEqual(set_doc["watchers"]["maker_watcher"], {})
        self.assertEqual(set_doc["watchers"]["tp_watcher"], {})
        self.assertEqual(set_doc["watchers"]["maker_pending_orders"], [])

    def test_only_whitelisted_config_keys_are_exposed(self):
        config_data = {
            "min_signal_score": 6, "min_signal_score_degraded": 4,
            "rsi_zone_min": 30, "rsi_zone_max": 65, "max_open_positions": 4,
            "reward_risk_ratio": 1.5, "fee_round_trip_pct": 0.009, "max_tp_pct": 0.06,
            "max_spread_pct": 0.0008, "risk_per_trade_pct": 0.02, "daily_loss_limit_pct": 0.05,
            "min_profit_pct_take": 5.0, "display_timezone": "Europe/Paris",
            "telegram_token_should_not_leak": "secret", "usdc_blacklist": ["FOO"],
        }
        set_doc = _run_phase7_dashboard([], config_data=config_data)

        self.assertEqual(
            set(set_doc["config"].keys()),
            {
                "min_signal_score", "min_signal_score_degraded", "rsi_zone_min", "rsi_zone_max",
                "max_open_positions", "reward_risk_ratio", "fee_round_trip_pct", "max_tp_pct",
                "max_spread_pct", "risk_per_trade_pct", "daily_loss_limit_pct", "min_profit_pct_take",
                "display_timezone",
            },
        )
        self.assertEqual(set_doc["config"]["min_signal_score"], 6)
        self.assertEqual(set_doc["config"]["rsi_zone_max"], 65)
        self.assertEqual(set_doc["config"]["display_timezone"], "Europe/Paris")



class TestClosedTradesProjection(unittest.TestCase):
    """#455 — la liste des ventes publiée pour l'onglet Ventes du dashboard."""

    def _module(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "binance-bot", "core", "phases", "phase7_mongo.py")
        src_text = open(path).read()
        start = src_text.index("CLOSED_TRADES_LIMIT")
        end = src_text.index("def _build_dashboard_state")
        sys.path.insert(0, os.path.join(root, "binance-bot"))
        from core.timing import parse_dt
        ns = {"parse_dt": parse_dt}
        exec(compile(src_text[start:end], "p7_closed", "exec"), ns)  # noqa: S102
        return ns

    def test_projects_the_fields_the_dashboard_needs(self):
        ns = self._module()
        rows = ns["_closed_trades"]([{
            "coin": "SOL", "date": "2026-08-25T08:00:00+00:00", "exit_date": "2026-08-27T12:00:00+00:00",
            "entry_price": 100.0, "exit_price": 104.0, "tp_price": 104.2, "stop_price": 99.0,
            "quantity": 1.0, "pnl_gross_usdc": 4.0, "fees_usdc": 1.0, "pnl_usdc": 3.0,
            "close_reason": "tp_watcher", "maker_or_taker": "maker", "fees_estimated": True,
            "entry_order_id": "SECRET", "sl_order_txid": "SECRET",
        }])
        row = rows[0]
        for field in ("coin", "entry_date", "exit_date", "hold_hours", "entry_price", "exit_price",
                      "tp_price", "stop_price", "quantity", "pnl_gross_usdc", "fees_usdc",
                      "pnl_usdc", "close_reason", "maker_or_taker", "fees_estimated"):
            self.assertIn(field, row, field)
        # projection etroite : pas d'identifiants d'ordres
        self.assertNotIn("entry_order_id", row)
        self.assertNotIn("sl_order_txid", row)

    def test_hold_hours_computed_from_the_two_dates(self):
        ns = self._module()
        rows = ns["_closed_trades"]([{
            "date": "2026-08-25T08:00:00+00:00", "exit_date": "2026-08-27T12:00:00+00:00"}])
        self.assertAlmostEqual(rows[0]["hold_hours"], 52.0)

    def test_missing_date_does_not_crash(self):
        ns = self._module()
        rows = ns["_closed_trades"]([{"coin": "X", "exit_date": None}])
        self.assertIsNone(rows[0]["hold_hours"])

    def test_most_recent_first_and_bounded(self):
        """Le document Mongo ne doit pas grossir indéfiniment avec l'historique."""
        ns = self._module()
        trades = [{"coin": f"C{i}", "exit_date": f"2026-01-{i % 28 + 1:02d}T00:00:00+00:00"}
                  for i in range(500)]
        rows = ns["_closed_trades"](trades, limit=10)
        self.assertEqual(len(rows), 10)
        dates = [r["exit_date"] for r in rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_fees_estimated_is_always_a_boolean(self):
        """Masquer qu'un frais est estimé donnerait au net une précision qu'il n'a pas."""
        ns = self._module()
        rows = ns["_closed_trades"]([{"coin": "A"}, {"coin": "B", "fees_estimated": True}])
        self.assertEqual({r["fees_estimated"] for r in rows}, {False, True})



if __name__ == "__main__":
    unittest.main()
