"""Tests pour commands/perf.py — commande /perf enrichie (#396).

Commande en lecture seule : les 4 chemins d'état (trade_history.json, cycle_log.jsonl,
tp_watcher_state.json, maker_watcher_state.json, maker_pending_orders.json) sont patchés vers
un dossier temporaire, jamais les vrais fichiers de state/.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from commands import perf


def _iso(days_ago: float = 0, seconds_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago, seconds=seconds_ago)).isoformat()


def _closed_trade(coin, pnl_usdc, days_ago=1, fees_usdc=None, fees_estimated=False, close_reason=None, **extra):
    t = {
        "coin": coin,
        "status": "closed",
        "date": _iso(days_ago + 1),
        "exit_date": _iso(days_ago),
        "pnl_usdc": pnl_usdc,
        "close_reason": close_reason,
    }
    if fees_usdc is not None:
        t["fees_usdc"] = fees_usdc
        t["fees_estimated"] = fees_estimated
    t.update(extra)
    return t


class PerfCommandTestCase(unittest.TestCase):
    """Base commune : patch les 5 chemins d'état vers un dossier temporaire."""

    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        base = tmpdir.name
        self.history_path = os.path.join(base, "trade_history.json")
        self.cycle_log_path = os.path.join(base, "cycle_log.jsonl")
        self.tp_watcher_path = os.path.join(base, "tp_watcher_state.json")
        self.maker_watcher_path = os.path.join(base, "maker_watcher_state.json")
        self.maker_pending_path = os.path.join(base, "maker_pending_orders.json")

        for attr, value in (
            ("_HISTORY_PATH", self.history_path),
            ("_CYCLE_LOG_PATH", self.cycle_log_path),
            ("_TP_WATCHER_STATE_PATH", self.tp_watcher_path),
            ("_MAKER_WATCHER_STATE_PATH", self.maker_watcher_path),
            ("_MAKER_PENDING_ORDERS_PATH", self.maker_pending_path),
        ):
            p = patch.object(perf, attr, value)
            p.start()
            self.addCleanup(p.stop)

        # storage.mongo n'est jamais configuré en test (pas de MONGODB_URI) -> _bloc_cycles
        # retombe naturellement sur cycle_log.jsonl.

    def _write_history(self, trades):
        with open(self.history_path, "w") as f:
            json.dump(trades, f)


class TestRunPerfNoData(unittest.TestCase):
    def test_missing_history_file_shows_no_data_message(self):
        with tempfile.TemporaryDirectory() as base:
            with patch.object(perf, "_HISTORY_PATH", os.path.join(base, "trade_history.json")):
                out = perf.run_perf()
        self.assertIn("Pas encore de données de trading", out)

    def test_empty_history_list_shows_no_data_message(self):
        with tempfile.TemporaryDirectory() as base:
            hp = os.path.join(base, "trade_history.json")
            with open(hp, "w") as f:
                json.dump([], f)
            with patch.object(perf, "_HISTORY_PATH", hp):
                out = perf.run_perf()
        self.assertIn("Pas encore de données de trading", out)


class TestBlocResultat(PerfCommandTestCase):
    def test_brut_frais_net_decomposition(self):
        self._write_history([
            _closed_trade("BTC", pnl_usdc=8.0, fees_usdc=2.0, days_ago=1),
            _closed_trade("ETH", pnl_usdc=-3.0, fees_usdc=1.0, days_ago=1),
        ])
        out = perf.run_perf()
        # net = 8 - 3 = 5 ; frais = 2 + 1 = 3 ; brut = 5 + 3 = 8
        self.assertIn("Brut <code>+8.00</code>", out)
        self.assertIn("frais <code>-3.00</code>", out)
        self.assertIn("net <code>+5.00 USDC</code>", out)
        self.assertIn("(38% du brut)", out)

    def test_trades_without_fees_usdc_do_not_crash_or_skew_totals(self):
        """SYN/PENDLE : écartés par le garde-fou de cohérence du backfill, aucun fees_usdc."""
        self._write_history([
            _closed_trade("SYN", pnl_usdc=-1.17),  # pas de fees_usdc
            _closed_trade("PENDLE", pnl_usdc=-0.25),  # pas de fees_usdc
            _closed_trade("BTC", pnl_usdc=5.0, fees_usdc=1.0),
        ])
        out = perf.run_perf()
        # net total = -1.17 -0.25 + 5.0 = 3.58 ; frais connus = 1.0 ; brut = 4.58
        self.assertIn("net <code>+3.58 USDC</code>", out)
        self.assertIn("frais <code>-1.00</code>", out)

    def test_win_rate_labelled_gagnants_not_win_rate(self):
        self._write_history([_closed_trade("BTC", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        self.assertIn("Gagnants :", out)
        self.assertNotIn("Win rate", out)

    def test_zero_brut_shows_nd_percentage_instead_of_crashing(self):
        self._write_history([
            _closed_trade("BTC", pnl_usdc=-2.0, fees_usdc=2.0),
        ])
        out = perf.run_perf()
        self.assertIn("n/d du brut", out)


class TestBlocPeriodes(PerfCommandTestCase):
    def test_periods_are_non_overlapping(self):
        self._write_history([
            _closed_trade("A", pnl_usdc=10.0, fees_usdc=1.0, days_ago=2),   # 0-7j
            _closed_trade("B", pnl_usdc=-5.0, fees_usdc=1.0, days_ago=15),  # 8-30j
            _closed_trade("C", pnl_usdc=3.0, fees_usdc=1.0, days_ago=45),   # au-delà
        ])
        out = perf.run_perf()
        self.assertIn("0-7 j (1)", out)
        self.assertIn("8-30 j (1)", out)
        self.assertIn("au-delà (1)", out)

    def test_empty_period_shows_zero_trades_not_omitted(self):
        self._write_history([
            _closed_trade("A", pnl_usdc=10.0, fees_usdc=1.0, days_ago=2),
        ])
        out = perf.run_perf()
        self.assertIn("8-30 j : <code>0 trade</code>", out)
        self.assertIn("au-delà : <code>0 trade</code>", out)

    def test_trade_without_exit_date_excluded_from_periods_without_crash(self):
        trades = [_closed_trade("A", pnl_usdc=10.0, fees_usdc=1.0, days_ago=2)]
        trades[0]["exit_date"] = None
        self._write_history(trades)
        out = perf.run_perf()  # ne doit pas lever
        self.assertIn("0-7 j : <code>0 trade</code>", out)


class TestBlocFrais(PerfCommandTestCase):
    def test_measured_vs_estimated_vs_missing_breakdown(self):
        self._write_history([
            _closed_trade("A", pnl_usdc=1.0, fees_usdc=1.0, fees_estimated=False),
            _closed_trade("B", pnl_usdc=1.0, fees_usdc=1.0, fees_estimated=True),
            _closed_trade("SYN", pnl_usdc=-1.0),  # pas de fees_usdc du tout
        ])
        out = perf.run_perf()
        self.assertIn("Mesurés : <code>1</code>", out)
        self.assertIn("Estimés : <code>1</code>", out)
        self.assertIn("Non calculés : <code>1</code>", out)

    def test_average_fee_excludes_trades_without_fees_usdc(self):
        self._write_history([
            _closed_trade("A", pnl_usdc=1.0, fees_usdc=2.0),
            _closed_trade("B", pnl_usdc=1.0, fees_usdc=4.0),
            _closed_trade("SYN", pnl_usdc=-1.0),
        ])
        out = perf.run_perf()
        # moyenne sur 2 trades avec frais connus = (2+4)/2 = 3.00, pas /3
        self.assertIn("moy./trade : <code>3.00</code>", out)


class TestBlocPositions(PerfCommandTestCase):
    def test_cancelled_positions_are_counted(self):
        self._write_history([
            {"coin": "A", "status": "open"},
            {"coin": "B", "status": "cancelled"},
            {"coin": "C", "status": "cancelled"},
            _closed_trade("D", pnl_usdc=1.0, fees_usdc=0.1),
        ])
        out = perf.run_perf()
        self.assertIn("Annulées : <code>2</code>", out)

    def test_no_cancelled_shows_zero(self):
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        self.assertIn("Annulées : <code>0</code>", out)

    def test_tp_watcher_count_matches_between_positions_and_watcher_blocks(self):
        """Piège explicite du ticket (#396) : les deux blocs ne doivent jamais afficher deux
        chiffres différents pour le même fait."""
        self._write_history([
            _closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1, close_reason="tp_watcher"),
            _closed_trade("B", pnl_usdc=1.0, fees_usdc=0.1, close_reason="tp_watcher_cycle"),
            _closed_trade("C", pnl_usdc=1.0, fees_usdc=0.1, close_reason="sl_hit"),
        ])
        out = perf.run_perf()
        self.assertIn("Par TP Watcher : <code>2</code>", out)
        self.assertIn("Ventes (historique) : <code>2</code>", out)


class TestBlocWatcher(PerfCommandTestCase):
    def test_missing_state_file_does_not_crash_and_still_shows_history_sales(self):
        self._write_history([
            _closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1, close_reason="tp_watcher"),
        ])
        out = perf.run_perf()
        self.assertIn("fichier d'état absent", out)
        self.assertIn("Ventes (historique) : <code>1</code>", out)

    def test_state_total_sales_is_never_displayed_as_contradictory_figure(self):
        """Le compteur total_sales de tp_watcher_state.json ne doit plus apparaître : il peut
        sous-estimer après un redémarrage et contredire le Bloc Positions."""
        with open(self.tp_watcher_path, "w") as f:
            json.dump({"total_ticks": 500, "total_sales": 9}, f)
        self._write_history([
            _closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1, close_reason="tp_watcher"),
            _closed_trade("B", pnl_usdc=1.0, fees_usdc=0.1, close_reason="tp_watcher"),
        ])
        out = perf.run_perf()
        self.assertIn("Ventes (historique) : <code>2</code>", out)
        self.assertNotIn("Ventes total", out)
        self.assertIn("Ticks total : <code>500</code>", out)


class TestBlocMaker(PerfCommandTestCase):
    def test_no_pending_orders_shows_zero_capital(self):
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        self.assertIn("En attente : <code>0</code> ordre(s)", out)
        self.assertIn("Capital immobilisé : <code>0.00 USDC</code>", out)

    def test_pending_orders_capital_immobilized_computed(self):
        with open(self.maker_pending_path, "w") as f:
            json.dump([
                {"coin": "ETH", "quantity": 0.1, "initial_limit_price": 2000.0, "current_limit_price": 2001.0},
                {"coin": "SOL", "quantity": 5.0, "initial_limit_price": 100.0, "current_limit_price": 100.0},
            ], f)
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        # 0.1*2001.0 + 5.0*100.0 = 200.1 + 500.0 = 700.10
        self.assertIn("En attente : <code>2</code> ordre(s)", out)
        self.assertIn("Capital immobilisé : <code>700.10 USDC</code>", out)

    def test_missing_maker_watcher_state_shows_no_data_message(self):
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        self.assertIn("pas encore de données (watcher pas encore démarré)", out)

    def test_repartition_maker_fallback_abandoned_shown_on_same_footing(self):
        with open(self.maker_watcher_path, "w") as f:
            json.dump({"total_ticks": 100, "total_fills": 2, "total_fallbacks": 1, "total_abandoned": 1}, f)
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        self.assertIn("Servies en maker : <code>2</code> (50%)", out)
        self.assertIn("Repli marché : <code>1</code> (25%)", out)
        self.assertIn("Abandonnées : <code>1</code> (25%)", out)

    def test_no_classified_trades_shows_pas_encore_de_donnee(self):
        """Piège explicite du ticket : aucun trade classé maker/taker -> message neutre."""
        self._write_history([
            {"coin": "SYN", "status": "closed"},  # legacy pré-#382, pas de maker_or_taker
        ])
        out = perf.run_perf()
        self.assertIn("pas encore de donnée", out)

    def test_maker_or_taker_none_never_counted_as_taker(self):
        self._write_history([
            {"coin": "XRP", "status": "closed", "maker_or_taker": None,
             "date": _iso(1), "pnl_usdc": 1.0, "entry_fee_usdc": 1.0},
            {"coin": "ETH", "status": "closed", "maker_or_taker": "maker",
             "date": _iso(1), "pnl_usdc": 1.0, "entry_fee_usdc": 0.3, "maker_fill_seconds": 30},
        ])
        out = perf.run_perf()
        self.assertIn("Économie vs tout-taker : <code>~0.30 USDC</code>", out)

    def test_missing_maker_fill_seconds_shows_not_available(self):
        self._write_history([
            {"coin": "ETH", "status": "closed", "maker_or_taker": "maker",
             "date": _iso(1), "pnl_usdc": 1.0, "entry_fee_usdc": 0.3},
        ])
        out = perf.run_perf()
        self.assertIn("Délai médian de service : <code>n/d</code>", out)

    def test_open_trades_included_in_maker_classification(self):
        """Un trade maker rempli mais pas encore fermé doit compter dans l'économie/délai."""
        self._write_history([
            {"coin": "ETH", "status": "open", "maker_or_taker": "maker",
             "date": _iso(0), "entry_fee_usdc": 0.5, "maker_fill_seconds": 60},
        ])
        out = perf.run_perf()
        self.assertIn("Économie vs tout-taker : <code>~0.50 USDC</code>", out)

    def test_links_to_maker_command_for_detail(self):
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        self.assertIn("/maker", out)


class TestSkipTypeVulgarization(PerfCommandTestCase):
    def test_type_a_shown_as_score_faible(self):
        with open(self.cycle_log_path, "w") as f:
            f.write(json.dumps({"skip_type": "TYPE_A", "executed": 0}) + "\n")
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        out = perf.run_perf()
        self.assertIn("score faible: 1", out)
        self.assertNotIn("TYPE_A", out)


class TestRunPerfMessageLength(PerfCommandTestCase):
    def test_message_stays_under_telegram_limit(self):
        with open(self.maker_pending_path, "w") as f:
            json.dump([{"coin": f"C{i}", "quantity": 1.0, "initial_limit_price": 1.0,
                        "current_limit_price": 1.0} for i in range(50)], f)
        with open(self.maker_watcher_path, "w") as f:
            json.dump({"total_ticks": 999, "total_fills": 2, "total_fallbacks": 0, "total_abandoned": 0}, f)
        trades = [_closed_trade(f"C{i}", pnl_usdc=1.0, fees_usdc=0.5, days_ago=i % 40)
                  for i in range(120)]
        self._write_history(trades)
        out = perf.run_perf()
        self.assertLessEqual(len(out), 4096)

    def test_run_perf_never_calls_subprocess(self):
        self._write_history([_closed_trade("A", pnl_usdc=1.0, fees_usdc=0.1)])
        with patch("subprocess.run") as mock_run:
            perf.run_perf()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
