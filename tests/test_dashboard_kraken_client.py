"""Tests pour dashboard/kraken_client.py — prix courants via l'API publique Kraken (#432).

`urllib.request.urlopen` est patché : aucun appel réseau réel. Le cache TTL du module est
réinitialisé à chaque test (setUp) pour rester indépendant."""
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "dashboard"))

import kraken_client  # noqa: E402
from cache import cache  # noqa: E402


class _FakeResponse:
    """`with urlopen(...) as resp` exige __enter__/__exit__ définis sur la classe (le protocole
    context manager ne regarde pas les attributs d'instance) — d'où cette petite classe plutôt
    qu'un BytesIO bricolé."""
    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_response(payload: dict) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"))


class KrakenClientTestBase(unittest.TestCase):
    def setUp(self):
        cache.clear()


class TestGetPricesSuccess(KrakenClientTestBase):
    def test_parses_last_trade_price_for_each_coin(self):
        payload = {"error": [], "result": {
            "BNBUSDC": {"c": ["512.30", "0.1"]},
            "XDGUSDC": {"c": ["0.24", "100"]},
        }}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            prices = kraken_client.get_prices(["BNB", "XDG"])
        self.assertEqual(prices["BNB"], 512.30)
        self.assertEqual(prices["XDG"], 0.24)

    def test_empty_coin_list_skips_network_call(self):
        with patch("urllib.request.urlopen") as mock_open:
            prices = kraken_client.get_prices([])
        self.assertEqual(prices, {})
        mock_open.assert_not_called()

    def test_second_call_within_ttl_does_not_refetch(self):
        payload = {"error": [], "result": {"BNBUSDC": {"c": ["500", "0.1"]}}}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)) as mock_open:
            kraken_client.get_prices(["BNB"])
            kraken_client.get_prices(["BNB"])
        self.assertEqual(mock_open.call_count, 1)


class TestGetPricesPartialMatch(KrakenClientTestBase):
    def test_falls_back_to_substring_match_when_key_renamed(self):
        # Kraken peut renvoyer une paire renommée (préfixe legacy) pour certains actifs.
        payload = {"error": [], "result": {"XXDGZUSDC": {"c": ["0.25", "10"]}}}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            prices = kraken_client.get_prices(["XDG"])
        self.assertEqual(prices["XDG"], 0.25)

    def test_coin_absent_from_response_yields_none(self):
        payload = {"error": [], "result": {}}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            prices = kraken_client.get_prices(["ZZZ"])
        self.assertIsNone(prices["ZZZ"])


class TestGetPricesUnavailable(KrakenClientTestBase):
    def test_network_error_raises_kraken_unavailable(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
            with self.assertRaises(kraken_client.KrakenUnavailable):
                kraken_client.get_prices(["BNB"])

    def test_kraken_error_payload_raises_kraken_unavailable(self):
        payload = {"error": ["EQuery:Unknown asset pair"], "result": {}}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            with self.assertRaises(kraken_client.KrakenUnavailable):
                kraken_client.get_prices(["BNB"])

    def test_malformed_json_raises_kraken_unavailable(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse(b"not json")):
            with self.assertRaises(kraken_client.KrakenUnavailable):
                kraken_client.get_prices(["BNB"])


if __name__ == "__main__":
    unittest.main()
