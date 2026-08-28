"""Tests pour dashboard/auth.py — authentification par variable d'environnement (#432)."""
import os
import sys
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "dashboard"))

import auth  # noqa: E402
import settings  # noqa: E402


class TestIsConfigured(unittest.TestCase):
    def test_true_when_both_env_vars_set(self):
        settings.DASHBOARD_PASSWORD = "secret"
        settings.DASHBOARD_SECRET_KEY = "key"
        self.assertTrue(auth.is_configured())

    def test_false_when_password_missing(self):
        settings.DASHBOARD_PASSWORD = ""
        settings.DASHBOARD_SECRET_KEY = "key"
        self.assertFalse(auth.is_configured())

    def test_false_when_secret_key_missing(self):
        settings.DASHBOARD_PASSWORD = "secret"
        settings.DASHBOARD_SECRET_KEY = ""
        self.assertFalse(auth.is_configured())


class TestCheckPassword(unittest.TestCase):
    def setUp(self):
        settings.DASHBOARD_PASSWORD = "correct-horse"

    def test_matching_password_returns_true(self):
        self.assertTrue(auth.check_password("correct-horse"))

    def test_wrong_password_returns_false(self):
        self.assertFalse(auth.check_password("wrong"))

    def test_empty_candidate_returns_false(self):
        self.assertFalse(auth.check_password(""))

    def test_none_candidate_does_not_raise(self):
        self.assertFalse(auth.check_password(None))


if __name__ == "__main__":
    unittest.main()
