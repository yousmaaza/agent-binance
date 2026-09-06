"""Test sur le vrai state/trade_history.json (#469) — exception délibérée à la règle « pas de
fichier state/ » des autres suites de dashboard : cet enregistrement est historique et immuable,
le fichier est versionné dans git, et c'est précisément ce fichier qu'un futur backfill toucherait.
Un test sur fixture ne peut pas jouer ce rôle — seule une lecture du fichier réel le peut."""
import json
import os
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADE_HISTORY_PATH = os.path.join(PROJECT_DIR, "state", "trade_history.json")


class TestSyn38515babStaysMarked(unittest.TestCase):
    """SYN 38515bab : exit_price (0,5543) est faux, pnl_usdc (-1,16508) fait foi (#469).
    Si un futur backfill retire le marqueur ou touche pnl_usdc, ce test doit tomber."""

    def _load_trade(self):
        with open(TRADE_HISTORY_PATH) as f:
            trades = json.load(f)
        return next(t for t in trades if t.get("trade_id") == "38515bab")

    def test_marker_is_still_present(self):
        trade = self._load_trade()
        self.assertEqual(trade.get("data_quality"), "exit_price_unreliable")

    def test_pnl_usdc_is_untouched(self):
        trade = self._load_trade()
        self.assertEqual(trade.get("pnl_usdc"), -1.1650800000000001)

    def test_exit_price_was_not_rewritten(self):
        """Le ticket #469 interdit de remplacer 0,5543 par la valeur dérivée 0,33825 — le prix
        reste faux, mais non réécrit, c'est le marqueur qui porte l'information."""
        trade = self._load_trade()
        self.assertEqual(trade.get("exit_price"), 0.5543)


if __name__ == "__main__":
    unittest.main()
