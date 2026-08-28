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

import settings

settings.DASHBOARD_PASSWORD = "test-password"
settings.DASHBOARD_SECRET_KEY = "test-secret-key"

import app as dashboard_app
from cache import cache
from kraken_client import KrakenUnavailable
from mongo_client import DashboardStateMissing, MongoUnavailable

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
        self.assertIn(b"MongoDB injoignable", r.data)
        self.assertNotIn(b"Aucune donn", r.data)

    def test_state_missing_shows_distinct_message(self):
        with patch("app.get_dashboard_state", side_effect=DashboardStateMissing("no doc")):
            self._login()
            r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Aucune donn", r.data)
        self.assertNotIn(b"MongoDB injoignable", r.data)

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
        self.assertIn(b"API Kraken injoignable", r.data)
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


if __name__ == "__main__":
    unittest.main()
