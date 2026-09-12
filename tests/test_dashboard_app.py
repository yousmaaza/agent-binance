"""Tests pour dashboard/app.py — routes Flask, authentification, et surtout les 4 états
dégradés distincts exigés par le ticket #432 (Mongo injoignable, dashboard_state absent,
donnée périmée, Kraken indisponible).

`settings.DASHBOARD_SECRET_KEY`/`DASHBOARD_PASSWORD` doivent être définis AVANT le premier
`import app` du process : `app.secret_key` est assigné une seule fois, au chargement du module
(mis en cache par Python, comme tous les modules `import`és dans tests/) — d'où l'ordre des
imports ci-dessous, contrairement aux autres fichiers de test dashboard."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "dashboard"))

import settings  # noqa: E402
settings.DASHBOARD_PASSWORD = "test-password"
settings.DASHBOARD_SECRET_KEY = "test-secret-key"

import app as dashboard_app  # noqa: E402
from cache import cache  # noqa: E402
from kraken_client import KrakenUnavailable  # noqa: E402
from mongo_client import DashboardStateMissing, MongoUnavailable  # noqa: E402

SAMPLE_STATE = {
    "_id": "current",
    "updated_at": None,  # défini par setUp() (dépend de "now")
    "cycle_id": "20260828_100500",
    "cycle_status": "completed",
    "open_positions": [
        {"coin": "BNB", "entry_price": 500.0, "stop_price": 480.0, "tp_price": 550.0,
         "quantity": 0.1, "opened_at": "2026-08-27T10:00:00+00:00", "entry_fee_usdc": 0.2,
         "maker_or_taker": "maker"},
    ],
    "financials": {
        "global": {"gross_usdc": 25.0, "fees_usdc": 3.0, "net_usdc": 22.0, "count": 10, "wins": 6, "losses": 4, "trades_without_fees": 0},
        "by_period": {
            "0_7d": {"gross_usdc": 10, "fees_usdc": 1, "net_usdc": 9, "count": 3},
            "8_30d": {"gross_usdc": 10, "fees_usdc": 1, "net_usdc": 9, "count": 4},
            "30d_plus": {"gross_usdc": 5, "fees_usdc": 1, "net_usdc": 4, "count": 3},
        },
        "pnl_by_coin": {"BNB": 22.0},
        "close_reason_counts": {"tp_watcher": 6, "sl_hit": 4},
        "equity_curve": [{"date": "2026-08-20", "cumulative_pnl_usdc": 5.0}, {"date": "2026-08-21", "cumulative_pnl_usdc": 22.0}],
    },
    "watchers": {
        "maker_watcher": {"total_fills": 5, "total_fallbacks": 2, "total_abandoned": 1},
        "maker_pending_orders": [],
    },
    "config": {"min_signal_score": 6, "display_timezone": "Europe/Paris"},
}

SAMPLE_CYCLES = [
    {"cycle_id": "20260828_100500", "timestamp": "2026-08-28T10:00:00+00:00", "status": "completed",
     "top_score": 7, "execution": {"executed": 1, "pending": 0, "skipped": 3},
     "explanation_fr": "On a acheté du BNB car le signal était solide.",
     "decisions": [{"coin": "BNB", "score": 7, "decision": "BUY", "reason": "Signal fort"}]},
]


class DashboardAppTestBase(unittest.TestCase):
    def setUp(self):
        cache.clear()
        settings.DASHBOARD_PASSWORD = "test-password"
        dashboard_app.app.config["TESTING"] = True
        self.client = dashboard_app.app.test_client()

    def _login(self):
        return self.client.post("/login", data={"password": "test-password"})


class TestAuthFlow(DashboardAppTestBase):
    def test_unauthenticated_request_redirects_to_login(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_wrong_password_shows_error_and_does_not_authenticate(self):
        r = self.client.post("/login", data={"password": "nope"})
        self.assertIn(b"incorrect", r.data)
        r2 = self.client.get("/")
        self.assertEqual(r2.status_code, 302)

    def test_correct_password_grants_access(self):
        with patch("app.get_dashboard_state", return_value=dict(SAMPLE_STATE, updated_at=datetime.now(timezone.utc).isoformat())), \
             patch("app.get_recent_cycles", return_value=[]):
            self._login()
            r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_logout_revokes_access(self):
        with patch("app.get_dashboard_state", return_value=dict(SAMPLE_STATE, updated_at=datetime.now(timezone.utc).isoformat())), \
             patch("app.get_recent_cycles", return_value=[]):
            self._login()
            self.client.get("/logout")
            r = self.client.get("/")
        self.assertEqual(r.status_code, 302)


class TestLoginRedirectNext(DashboardAppTestBase):
    def test_absolute_url_next_rejected_redirects_home(self):
        r = self.client.post("/login?next=https://exemple-malveillant.test/x", data={"password": "test-password"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/")

    def test_protocol_relative_next_rejected_redirects_home(self):
        r = self.client.post("/login?next=//exemple.test/x", data={"password": "test-password"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/")

    def test_backslash_variant_next_rejected_redirects_home(self):
        r = self.client.post("/login?next=/\\exemple.test", data={"password": "test-password"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/")

    def test_legitimate_internal_next_accepted(self):
        r = self.client.post("/login?next=/", data={"password": "test-password"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/")


class TestNotConfigured(DashboardAppTestBase):
    def test_returns_503_with_distinct_message_when_password_env_var_missing(self):
        settings.DASHBOARD_PASSWORD = ""
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 503)
        self.assertIn(b"non configur", r.data)


class TestDegradedStates(DashboardAppTestBase):
    def test_mongo_unavailable_shows_distinct_message(self):
        with patch("app.get_dashboard_state", side_effect=MongoUnavailable("SSL handshake failed")):
            self._login()
            r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("MongoDB injoignable".encode(), r.data)
        self.assertNotIn("Aucune donn".encode(), r.data)

    def test_state_missing_shows_distinct_message(self):
        with patch("app.get_dashboard_state", side_effect=DashboardStateMissing("no doc")):
            self._login()
            r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Aucune donn".encode(), r.data)
        self.assertNotIn("MongoDB injoignable".encode(), r.data)

    def test_stale_data_shows_warning_banner(self):
        old_state = dict(SAMPLE_STATE, updated_at=(datetime.now(timezone.utc) - timedelta(hours=8)).isoformat())
        with patch("app.get_dashboard_state", return_value=old_state), \
             patch("app.get_recent_cycles", return_value=[]):
            self._login()
            r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"donn\xc3\xa9e p\xc3\xa9rim\xc3\xa9e", r.data)

    def test_fresh_data_does_not_show_stale_warning(self):
        fresh_state = dict(SAMPLE_STATE, updated_at=datetime.now(timezone.utc).isoformat())
        with patch("app.get_dashboard_state", return_value=fresh_state), \
             patch("app.get_recent_cycles", return_value=[]):
            self._login()
            r = self.client.get("/")
        self.assertNotIn(b"donn\xc3\xa9e p\xc3\xa9rim\xc3\xa9e", r.data)

    def test_kraken_unavailable_shows_warning_but_page_still_renders(self):
        fresh_state = dict(SAMPLE_STATE, updated_at=datetime.now(timezone.utc).isoformat())
        with patch("app.get_dashboard_state", return_value=fresh_state), \
             patch("app.get_recent_cycles", return_value=[]), \
             patch("app.get_prices", side_effect=KrakenUnavailable("timeout")):
            self._login()
            r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("API Kraken injoignable".encode(), r.data)
        self.assertIn(b"BNB", r.data)  # la position reste affich\xc3\xa9e, sans prix courant


class TestHappyPath(DashboardAppTestBase):
    def test_renders_positions_financials_and_cycles_journal(self):
        fresh_state = dict(SAMPLE_STATE, updated_at=datetime.now(timezone.utc).isoformat())
        with patch("app.get_dashboard_state", return_value=fresh_state), \
             patch("app.get_recent_cycles", return_value=SAMPLE_CYCLES), \
             patch("app.get_prices", return_value={"BNB": 510.0}):
            self._login()
            r = self.client.get("/")
        body = r.data.decode("utf-8")
        self.assertEqual(r.status_code, 200)
        self.assertIn("BNB", body)
        self.assertIn("510.0", body)
        self.assertIn("On a acheté du BNB", body)  # explanation_fr injectée dans la modale


class TestSalesTabCycleLink(DashboardAppTestBase):
    """#470, retour de review : quatre rendus distincts pour le cycle d'une vente — lien (cycle
    dans le journal chargé), identifiant en texte simple (cycle réel mais hors de la fenêtre du
    journal, #473), "hors cycle" (cycle_id: None explicite), et un marqueur neutre d'inconnu
    (champ absent, ventes antérieures à cette PR) — jamais confondus, jamais de lien mort."""

    def test_four_cycle_id_cases_are_rendered_distinctly(self):
        closed_trades = [
            {"coin": "SOL", "entry_date": "2026-08-25T08:00:00+00:00", "exit_date": "2026-08-27T12:00:00+00:00",
             "hold_hours": 52.0, "entry_price": 100.0, "exit_price": 104.0, "tp_price": 104.0, "quantity": 1.0,
             "pnl_gross_usdc": 4.0, "fees_usdc": 1.0, "pnl_usdc": 3.0, "close_reason": "profit_target_phase0",
             "maker_or_taker": "maker", "fees_estimated": False,
             "cycle_id": "20260828_100500"},  # dans SAMPLE_CYCLES -> lien
            {"coin": "DOT", "entry_date": "2026-01-01T08:00:00+00:00", "exit_date": "2026-01-02T08:00:00+00:00",
             "hold_hours": 24.0, "entry_price": 5.0, "exit_price": 5.2, "tp_price": 5.3, "quantity": 10.0,
             "pnl_gross_usdc": 2.0, "fees_usdc": 0.1, "pnl_usdc": 1.9, "close_reason": "profit_target_phase0",
             "maker_or_taker": "maker", "fees_estimated": False,
             "cycle_id": "20260101_000500"},  # réel mais hors du journal chargé -> texte, pas de lien
            {"coin": "ADA", "entry_date": "2026-08-20T08:00:00+00:00", "exit_date": "2026-08-21T08:00:00+00:00",
             "hold_hours": 24.0, "entry_price": 0.2, "exit_price": 0.19, "tp_price": 0.22, "quantity": 100.0,
             "pnl_gross_usdc": -1.0, "fees_usdc": 0.5, "pnl_usdc": -1.5, "close_reason": "tp_watcher",
             "maker_or_taker": None, "fees_estimated": True, "cycle_id": None},  # hors cycle explicite
            {"coin": "XRP", "entry_date": "2026-06-01T08:00:00+00:00", "exit_date": "2026-06-02T08:00:00+00:00",
             "hold_hours": 24.0, "entry_price": 0.5, "exit_price": 0.51, "tp_price": 0.55, "quantity": 10.0,
             "pnl_gross_usdc": 0.1, "fees_usdc": 0.02, "pnl_usdc": 0.08, "close_reason": "signal_sell_score3",
             "maker_or_taker": None, "fees_estimated": False},  # vente antérieure : pas de champ du tout
        ]
        state = dict(SAMPLE_STATE, updated_at=datetime.now(timezone.utc).isoformat(), closed_trades=closed_trades)
        with patch("app.get_dashboard_state", return_value=state), \
             patch("app.get_recent_cycles", return_value=SAMPLE_CYCLES), \
             patch("app.get_prices", return_value={"BNB": 510.0}):
            self._login()
            r = self.client.get("/?tab=ventes&periode=tout")
        body = r.data.decode("utf-8")
        self.assertEqual(r.status_code, 200)

        # SOL : cycle dans le journal -> vrai lien.
        self.assertIn('href="/?tab=cycles#cyc-20260828_100500"', body)
        # DOT : cycle réel mais hors du journal chargé -> identifiant visible, jamais de lien mort.
        self.assertIn("20260101_000500", body)
        self.assertNotIn('href="/?tab=cycles#cyc-20260101_000500"', body)
        # ADA : cycle_id: None explicite -> cellule "hors cycle" (exactement une, la colonne
        # Cycle), jamais confondue avec l'absence de champ. Le mot apparaît aussi ailleurs sur la
        # page (note explicative, colonne Déclencheur) : on cible la cellule elle-même.
        self.assertEqual(body.count('<td class="mut">hors cycle</td>'), 1)
        # XRP : signal_sell_score3 prouve une fermeture pendant un cycle, mais le champ n'a jamais
        # été écrit (vente antérieure à cette PR) -> marqueur neutre d'inconnu, pas "hors cycle".
        self.assertIn("vente antérieure à l'enregistrement du cycle", body)


class TestSalesTabExitMode(DashboardAppTestBase):
    """#490 : une vente en apporteur, une en preneur, et une vente antérieure à #488 (champ
    absent) doivent produire trois rendus distincts dans la colonne Mode sortie — jamais
    confondus entre eux, et jamais présentés comme une information connue quand elle ne l'est
    pas."""

    def test_three_exit_modes_are_rendered_distinctly(self):
        closed_trades = [
            {"coin": "SOL", "entry_date": "2026-08-25T08:00:00+00:00", "exit_date": "2026-08-27T12:00:00+00:00",
             "hold_hours": 52.0, "entry_price": 100.0, "exit_price": 104.0, "tp_price": 104.0, "quantity": 1.0,
             "pnl_gross_usdc": 4.0, "fees_usdc": 1.0, "pnl_usdc": 3.0, "close_reason": "tp_watcher",
             "maker_or_taker": "maker", "fees_estimated": False,
             "exit_maker_or_taker": "maker", "exit_fee_usdc": 0.312},
            {"coin": "DOT", "entry_date": "2026-08-25T08:00:00+00:00", "exit_date": "2026-08-27T12:00:00+00:00",
             "hold_hours": 52.0, "entry_price": 5.0, "exit_price": 5.2, "tp_price": 5.3, "quantity": 10.0,
             "pnl_gross_usdc": 2.0, "fees_usdc": 0.31, "pnl_usdc": 1.7, "close_reason": "signal_sell_score1",
             "maker_or_taker": "taker", "fees_estimated": False,
             "exit_maker_or_taker": "taker", "exit_fee_usdc": 0.312},
            {"coin": "ADA", "entry_date": "2026-08-20T08:00:00+00:00", "exit_date": "2026-08-21T08:00:00+00:00",
             "hold_hours": 24.0, "entry_price": 0.2, "exit_price": 0.19, "tp_price": 0.22, "quantity": 100.0,
             "pnl_gross_usdc": -1.0, "fees_usdc": 0.5, "pnl_usdc": -1.5, "close_reason": "sl_hit",
             "maker_or_taker": None, "fees_estimated": True},  # vente antérieure : pas de champ du tout
        ]
        state = dict(SAMPLE_STATE, updated_at=datetime.now(timezone.utc).isoformat(), closed_trades=closed_trades)
        with patch("app.get_dashboard_state", return_value=state), \
             patch("app.get_recent_cycles", return_value=SAMPLE_CYCLES), \
             patch("app.get_prices", return_value={"BNB": 510.0}):
            self._login()
            r = self.client.get("/?tab=ventes&periode=tout")
        body = r.data.decode("utf-8")
        self.assertEqual(r.status_code, 200)

        # Logique naïve à rejeter : les trois libellés doivent tous apparaître, chacun une
        # seule fois dans la colonne Mode sortie — jamais deux confondus sous le même libellé.
        self.assertEqual(body.count('class="pill-m" title="frais de sortie'), 1)
        self.assertEqual(body.count('class="pill-t" title="frais de sortie'), 1)
        self.assertIn("vente antérieure au suivi du mode de sortie", body)
        self.assertEqual(body.count("vente antérieure au suivi du mode de sortie"), 1)

        # Le taux de frais mesuré (bonus de vérification, #490) accompagne les deux ventes
        # classées, jamais la vente inconnue.
        self.assertIn("mesuré 0.30 %", body)
        self.assertIn("mesuré 0.60 %", body)


class TestMakerOrdersCards(DashboardAppTestBase):
    """#493 : le HTML réellement produit pour les cartes d'ordres maker, pas seulement les
    données de la vue — c'est le gabarit qui a trompé l'utilisateur la dernière fois."""

    def _get(self, watchers, config=None):
        state = dict(
            SAMPLE_STATE,
            updated_at=datetime.now(timezone.utc).isoformat(),
            watchers=watchers,
            config=dict(SAMPLE_STATE["config"], **(config or {})),
        )
        with patch("app.get_dashboard_state", return_value=state), \
             patch("app.get_recent_cycles", return_value=SAMPLE_CYCLES), \
             patch("app.get_prices", return_value={"BNB": 510.0}):
            self._login()
            return self.client.get("/")

    def test_multiple_pending_orders_each_get_their_own_card(self):
        now = datetime.now(timezone.utc)
        placed_at = (now - timedelta(minutes=10)).isoformat()
        watchers = {
            "maker_watcher": {"total_fills": 5, "total_fallbacks": 2, "total_abandoned": 1},
            "maker_pending_orders": [
                {"coin": "BTC", "score": 7, "montant_ordre": 50.0, "quantity": 0.001,
                 "initial_limit_price": 60000.0, "current_limit_price": 60060.0,
                 "adjustments": 2, "placed_at": placed_at},
                {"coin": "ETH", "score": 6, "montant_ordre": 30.0, "quantity": 0.01,
                 "initial_limit_price": 3000.0, "current_limit_price": 3000.0,
                 "adjustments": 0, "placed_at": placed_at},
            ],
        }
        r = self._get(watchers, {"maker_max_concession_pct": 0.003, "maker_timeout_seconds": 3600})
        body = r.data.decode("utf-8")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body.count('class="mk-card"'), 2)
        self.assertIn("60 000", body)  # prix de pose BTC, format_price français
        self.assertIn("en chasse", body)

    def test_no_pending_orders_shows_empty_state_without_error(self):
        watchers = {
            "maker_watcher": {"total_fills": 5, "total_fallbacks": 2, "total_abandoned": 1},
            "maker_pending_orders": [],
        }
        r = self._get(watchers)
        body = r.data.decode("utf-8")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('class="mk-card"', body)
        self.assertIn("Aucun ordre d'achat en vol", body)

    def test_order_over_80_percent_budget_shows_soon_canceled_pill(self):
        now = datetime.now(timezone.utc)
        watchers = {
            "maker_watcher": {"total_fills": 5, "total_fallbacks": 2, "total_abandoned": 1},
            "maker_pending_orders": [
                {"coin": "SOL", "score": 8, "montant_ordre": 20.0, "quantity": 0.5,
                 "initial_limit_price": 100.0, "current_limit_price": 100.28,
                 "adjustments": 6, "placed_at": now.isoformat()},
            ],
        }
        r = self._get(watchers, {"maker_max_concession_pct": 0.003, "maker_timeout_seconds": 3600})
        body = r.data.decode("utf-8")
        self.assertEqual(r.status_code, 200)
        self.assertIn("bientôt annulé", body)
        self.assertIn('class="mk-pill mk-pill-warn"', body)


if __name__ == "__main__":
    unittest.main()
