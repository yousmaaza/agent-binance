"""Tests pour commands/maker.py — commande /maker (#389).

Commande en lecture seule : les 3 chemins d'état (maker_watcher_state.json,
maker_pending_orders.json, trade_history.json) sont patchés vers un dossier temporaire, jamais
les vrais fichiers de state/. _load_config est mocké pour ne jamais dépendre du vrai config.json.
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

from commands import maker  # noqa: E402

BASE_CFG = {
    "maker_entry_enabled": True,
    "maker_tick_seconds": 20,
    "maker_max_concession_pct": 0.003,
}


def _iso(seconds_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class MakerCommandTestCase(unittest.TestCase):
    """Base commune : patch les 3 chemins d'état + _load_config vers un dossier temporaire."""

    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        base = tmpdir.name
        self.watcher_state_path = os.path.join(base, "maker_watcher_state.json")
        self.pending_orders_path = os.path.join(base, "maker_pending_orders.json")
        self.history_path = os.path.join(base, "trade_history.json")

        for attr, value in (
            ("_WATCHER_STATE_PATH", self.watcher_state_path),
            ("_PENDING_ORDERS_PATH", self.pending_orders_path),
            ("_HISTORY_PATH", self.history_path),
        ):
            p = patch.object(maker, attr, value)
            p.start()
            self.addCleanup(p.stop)

        self.cfg = dict(BASE_CFG)
        p_cfg = patch.object(maker, "_load_config", return_value=self.cfg)
        p_cfg.start()
        self.addCleanup(p_cfg.stop)

    def _write(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)


class TestHealthBlock(MakerCommandTestCase):
    def test_no_state_file_yet_shows_waiting_for_first_tick(self):
        out = maker.run_maker()
        self.assertIn("En attente du premier tick", out)

    def test_maker_entry_disabled_shows_disabled_switch(self):
        """Piège explicite du ticket : l'interrupteur maker_entry_enabled=false doit être visible."""
        self.cfg["maker_entry_enabled"] = False
        out = maker.run_maker()
        self.assertIn("Désactivé", out)
        self.assertIn("maker_entry_enabled", out)

    def test_healthy_recent_tick_shows_ok(self):
        self._write(self.watcher_state_path, {
            "last_tick": _iso(5), "status": "ok", "last_error": None,
            "orders_checked": 0, "total_ticks": 10, "total_fills": 2, "total_fallbacks": 1,
        })
        out = maker.run_maker()
        self.assertIn("✅ OK", out)

    def test_stale_tick_shows_alert(self):
        self._write(self.watcher_state_path, {
            "last_tick": _iso(600), "status": "ok", "last_error": None,
            "orders_checked": 0, "total_ticks": 10, "total_fills": 0, "total_fallbacks": 0,
        })
        out = maker.run_maker()
        self.assertIn("⚠️", out)

    def test_last_error_shows_error_state(self):
        self._write(self.watcher_state_path, {
            "last_tick": _iso(5), "status": "warning", "last_error": "Ticker ETH indisponible : boom",
            "orders_checked": 1, "total_ticks": 5, "total_fills": 0, "total_fallbacks": 0,
        })
        out = maker.run_maker()
        self.assertIn("🔴 Erreur", out)
        self.assertIn("boom", out)

    def test_cumul_line_shows_total_abandoned(self):
        """Critère #430 : total_abandoned doit apparaître dans le bloc Cumul, à côté de
        remplis/replis marché, sans les fusionner."""
        self._write(self.watcher_state_path, {
            "last_tick": _iso(5), "status": "ok", "last_error": None,
            "orders_checked": 0, "total_ticks": 24583, "total_fills": 5, "total_fallbacks": 0,
            "total_abandoned": 2,
        })
        out = maker.run_maker()
        self.assertIn("5 remplis", out)
        self.assertIn("0 replis marché", out)
        self.assertIn("2 abandonné(s)", out)


class TestPendingOrdersBlock(MakerCommandTestCase):
    def test_no_pending_file_shows_no_orders(self):
        """Piège explicite du ticket : maker_pending_orders.json absent tant qu'aucun ordre posé."""
        out = maker.run_maker()
        self.assertIn("Aucun ordre en attente", out)

    def test_empty_pending_list_shows_no_orders(self):
        self._write(self.pending_orders_path, [])
        out = maker.run_maker()
        self.assertIn("Aucun ordre en attente", out)

    def test_pending_order_shows_concession_ratio_and_adjustments(self):
        self._write(self.pending_orders_path, [{
            "coin": "ETH", "quantity": 0.1,
            "initial_limit_price": 2000.0, "current_limit_price": 2001.0,
            "adjustments": 3, "placed_at": _iso(120),
        }])
        out = maker.run_maker()
        self.assertIn("ETH", out)
        self.assertIn("0.05%", out)  # (2001-2000)/2000 = 0.05%
        self.assertIn("0.30%", out)  # budget par défaut
        self.assertIn("3 ajustement", out)

    def test_concession_above_80_percent_of_budget_triggers_alert(self):
        # budget 0.30% -> 80% = 0.24% ; concession ici = 0.30% (>= 80% du budget)
        self._write(self.pending_orders_path, [{
            "coin": "SOL", "quantity": 5,
            "initial_limit_price": 100.0, "current_limit_price": 100.3,
            "adjustments": 1, "placed_at": _iso(60),
        }])
        out = maker.run_maker()
        self.assertIn("⚠️", out)

    def test_below_80_percent_of_budget_has_no_alert(self):
        self._write(self.pending_orders_path, [{
            "coin": "SOL", "quantity": 5,
            "initial_limit_price": 100.0, "current_limit_price": 100.05,
            "adjustments": 0, "placed_at": _iso(10),
        }])
        out = maker.run_maker()
        pending_section = out.split("Ordres en cours")[1].split("Efficacité")[0]
        self.assertNotIn("⚠️", pending_section)

    def test_many_pending_orders_are_truncated(self):
        orders = [{
            "coin": f"C{i}", "quantity": 1.0,
            "initial_limit_price": 1.0, "current_limit_price": 1.0,
            "adjustments": 0, "placed_at": _iso(1),
        } for i in range(12)]
        self._write(self.pending_orders_path, orders)
        out = maker.run_maker()
        self.assertIn("autre(s) ordre(s) non affiché", out)


class TestEfficiencyBlock(MakerCommandTestCase):
    def test_no_classified_trades_shows_no_data(self):
        self._write(self.history_path, [
            {"coin": "SYN", "status": "closed"},  # legacy pré-#382, pas de maker_or_taker
        ])
        out = maker.run_maker()
        self.assertIn("Pas encore de données", out)

    def test_missing_history_file_shows_no_data(self):
        out = maker.run_maker()
        self.assertIn("Pas encore de données", out)

    def test_none_maker_or_taker_is_never_counted_as_taker(self):
        """Piège explicite du ticket : maker_or_taker=None ne doit ni planter ni compter en taker."""
        self._write(self.history_path, [
            {"coin": "XRP", "maker_or_taker": None, "date": _iso(3600), "entry_fee_usdc": 1.0},
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 30},
        ])
        out = maker.run_maker()
        # Seul le trade "maker" est classé -> 100% maker, pas 50%.
        self.assertIn("100%", out)

    def test_fees_avoided_sums_entry_fee_of_maker_trades_only(self):
        self._write(self.history_path, [
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.30,
             "maker_fill_seconds": 30},
            {"coin": "SOL", "maker_or_taker": "taker", "date": _iso(3600), "entry_fee_usdc": 0.60},
        ])
        out = maker.run_maker()
        self.assertIn("0.30 USDC", out)

    def test_median_fill_delay_computed_from_maker_trades_only(self):
        self._write(self.history_path, [
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 30},
            {"coin": "SOL", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 90},
            {"coin": "XRP", "maker_or_taker": "taker", "date": _iso(3600), "entry_fee_usdc": 0.6},
        ])
        out = maker.run_maker()
        self.assertIn("Délai médian de remplissage : 60s", out)

    def test_median_fill_delay_is_precise_to_the_second_not_truncated_to_minute(self):
        """Critère #430 : échantillon réel 94/105/110/141/405 -> médiane 110s, pas "1min"."""
        seconds_samples = [94, 105, 110, 141, 405]
        self._write(self.history_path, [
            {"coin": f"C{i}", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.1,
             "maker_fill_seconds": s}
            for i, s in enumerate(seconds_samples)
        ])
        out = maker.run_maker()
        self.assertIn("Délai médian de remplissage : 110s", out)
        self.assertNotIn("Délai médian de remplissage : 1min", out)

    def test_missing_maker_fill_seconds_shows_not_available(self):
        """Piège : trades maker antérieurs à ce ticket, sans maker_fill_seconds persisté."""
        self._write(self.history_path, [
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3},
        ])
        out = maker.run_maker()
        self.assertIn("n/d", out)

    def test_trades_without_fees_usdc_do_not_crash_or_skew_totals(self):
        """2 trades legacy (SYN/PENDLE) écartés par le garde-fou du backfill : pas de
        maker_or_taker -> déjà exclus du calcul, aucun crash sur entry_fee_usdc absent."""
        self._write(self.history_path, [
            {"coin": "SYN", "status": "closed"},
            {"coin": "PENDLE", "status": "closed"},
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 30},
        ])
        out = maker.run_maker()
        self.assertIn("0.30 USDC", out)

    def test_abandon_rate_shown_on_same_plane_as_fill_rate(self):
        """Critère #430 : le taux d'abandon apparaît dans le bloc Efficacité, avec effectif,
        sans être confondu avec le taux de remplissage (source distincte : watcher state)."""
        self._write(self.watcher_state_path, {
            "last_tick": _iso(5), "status": "ok", "last_error": None,
            "orders_checked": 0, "total_ticks": 100, "total_fills": 5, "total_fallbacks": 1,
            "total_abandoned": 2,
        })
        self._write(self.history_path, [
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 30},
        ])
        out = maker.run_maker()
        # total_abandoned=2 sur total_fills+total_fallbacks+total_abandoned=8 tentatives -> 25%
        self.assertIn("Taux d'abandon : 25% (2 sur 8 tentative(s))", out)

    def test_abandon_rate_not_available_when_watcher_state_absent(self):
        """État dégradé #430 : fichier maker_watcher_state.json absent -> pas de crash, n/d."""
        self._write(self.history_path, [
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 30},
        ])
        out = maker.run_maker()
        self.assertIn("Taux d'abandon : n/d", out)

    def test_abandon_rate_shown_even_without_classified_trades(self):
        """Le risque principal (abandons) doit rester visible même si aucun trade n'est encore
        classé dans trade_history (ex : tous les ordres tentés ont été abandonnés)."""
        self._write(self.watcher_state_path, {
            "last_tick": _iso(5), "status": "ok", "last_error": None,
            "orders_checked": 0, "total_ticks": 10, "total_fills": 0, "total_fallbacks": 0,
            "total_abandoned": 3,
        })
        out = maker.run_maker()
        self.assertIn("Pas encore de données", out)
        self.assertIn("Taux d'abandon : 100% (3 sur 3 tentative(s))", out)

    def test_trend_7d_shows_insufficient_sample_message_below_threshold(self):
        """Ticket #430 : échantillon 7j trop petit (< 5) -> message honnête, pas de chiffre trompeur."""
        self._write(self.history_path, [
            {"coin": "ETH", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 30},
            {"coin": "SOL", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.3,
             "maker_fill_seconds": 90},
        ])
        out = maker.run_maker()
        self.assertIn("Tendance 7j : échantillon insuffisant (2 trade(s) classé(s))", out)
        self.assertIn("pas de tendance fiable", out)

    def test_trend_7d_computed_when_sample_reaches_threshold(self):
        self._write(self.history_path, [
            {"coin": f"C{i}", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.1,
             "maker_fill_seconds": 60}
            for i in range(5)
        ])
        out = maker.run_maker()
        self.assertIn("Tendance 7j : 100% de remplissage (sur 5 trade(s))", out)

    def test_trend_7d_excludes_trades_older_than_7_days(self):
        recent = [{
            "coin": f"M{i}", "maker_or_taker": "maker", "date": _iso(3600), "entry_fee_usdc": 0.1,
            "maker_fill_seconds": 60,
        } for i in range(4)]
        old = [{
            "coin": "OLD", "maker_or_taker": "taker", "date": _iso(15 * 86400), "entry_fee_usdc": 0.6,
        }]
        self._write(self.history_path, recent + old)
        out = maker.run_maker()
        self.assertIn("Tendance 7j : échantillon insuffisant (4 trade(s) classé(s))", out)


class TestRunMakerRespondsQuickly(unittest.TestCase):
    """Critère d'acceptation : /maker répond en moins de 5s — aucun appel réseau/CLI ici."""

    def test_run_maker_never_calls_subprocess(self):
        with patch("subprocess.run") as mock_run, patch.object(maker, "_load_config", return_value=BASE_CFG):
            maker.run_maker()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
