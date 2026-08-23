"""Tests de démonstration du harness (fake_kraken.py + import direct de phase3_scoring.py).

phase3_scoring.py est un script top-level (pas de fonctions extraites) : chaque test
ré-exécute le module via importlib avec un cycle_id distinct, écrit son propre input JSON
dans le dossier temp système et lit l'output JSON généré. tg() (notification Telegram) est
systématiquement mockée via unittest.mock.patch sur core.trade_helpers.subprocess.run —
jamais de vrai curl.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

PHASE3_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase3_scoring.py")
FAKE_KRAKEN_PATH = os.path.join(PROJECT_DIR, "tests", "fixtures", "fake_kraken.py")

DEFAULT_CONFIG = {
    "min_signal_score": 6,
    "min_signal_score_degraded": 4,
    "max_open_positions": 5,
    "max_correlated_positions": 2,
}


def _run_phase3(analysis_results, top_gainers_symbols=None, breakout_symbols=None,
                 sentiment="Neutral", open_positions=0, config=None):
    """Exécute phase3_scoring.py sur un scénario donné, tg() mockée. Retourne l'output JSON."""
    # /tmp/cycle_{cycle_id}_phase3_*.json est un chemin en dur dans phase3_scoring.py
    # lui-même (pas tempfile.gettempdir() — sur macOS ça pointerait vers /var/folders/...
    # et ne correspondrait plus au chemin que le script ouvre réellement). Le test doit
    # rester synchronisé avec cette convention, il ne la choisit pas.
    cycle_id = f"test_{uuid.uuid4().hex[:12]}"
    in_path = f"/tmp/cycle_{cycle_id}_phase3_input.json"
    out_path = f"/tmp/cycle_{cycle_id}_phase3_output.json"

    input_data = {
        "analysis_results": analysis_results,
        "top_gainers_symbols": top_gainers_symbols or [],
        "breakout_symbols": breakout_symbols or [],
        "sentiment": sentiment,
        "open_positions": open_positions,
        "config": config if config is not None else DEFAULT_CONFIG,
    }
    with open(in_path, "w") as f:
        json.dump(input_data, f)

    old_argv = sys.argv
    sys.argv = ["phase3_scoring.py", cycle_id]
    try:
        with patch("core.trade_helpers.subprocess.run") as mock_run:
            spec = importlib.util.spec_from_file_location(f"phase3_scoring_{cycle_id}", PHASE3_PATH)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

        assert mock_run.called, "tg() n'a pas appelé subprocess.run (curl) — mock non atteint"

        with open(out_path) as f:
            output = json.load(f)
    finally:
        sys.argv = old_argv
        if os.path.exists(in_path):
            os.remove(in_path)
        if os.path.exists(out_path):
            os.remove(out_path)

    return output


class TestScoreFormula(unittest.TestCase):
    """Chaque critère de scoring ajoute bien les points attendus."""

    def test_all_criteria_sum_to_expected_score(self):
        analysis_results = {
            "LOW": {"signal_4h": "NEUTRAL", "volume_24h": 10},
            "MED": {"signal_4h": "NEUTRAL", "volume_24h": 50},
            "TESTCOIN": {
                "signal_4h": "STRONG_BUY",       # +2
                "signal_1d": "BUY",               # +2
                "rsi_4h": 45,                      # +1 (30-65)
                "macd_bullish_4h": True,           # +1
                "volume_24h": 500,                 # +1 (> 2*median)
            },
        }
        out = _run_phase3(
            analysis_results,
            top_gainers_symbols=["TESTCOIN"],   # +1
            breakout_symbols=["TESTCOIN"],       # +1
            sentiment="Bullish",                 # +1
        )
        detail = out["scores_detail"]["TESTCOIN"]
        self.assertEqual(detail["score"], 10)
        self.assertEqual(detail["decision"], "BUY")
        self.assertIn("TESTCOIN", [c["coin"] for c in out["buy_candidates"]])


class TestMinSignalScoreThreshold(unittest.TestCase):
    def test_score_below_threshold_is_skipped(self):
        analysis_results = {
            "WEAKCOIN": {"signal_4h": "BUY"},  # score = 2, seuil = 6
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        detail = out["scores_detail"]["WEAKCOIN"]
        self.assertEqual(detail["decision"], "SKIP")
        self.assertEqual(detail["skip_type"], "TYPE_A")
        self.assertNotIn("WEAKCOIN", [c["coin"] for c in out["buy_candidates"]])


class TestDegradedMode(unittest.TestCase):
    def test_degraded_threshold_applies_when_all_4h_buy_rate_limited(self):
        analysis_results = {
            "RLCOIN": {
                "signal_4h": "BUY",             # +2
                "rsi_4h": 45,                     # +1
                "macd_bullish_4h": True,          # +1  => score 4
                "signal_1d_rate_limited": True,
            },
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        detail = out["scores_detail"]["RLCOIN"]
        self.assertEqual(detail["score"], 4)
        self.assertEqual(detail["decision"], "BUY")

    def test_normal_threshold_applies_when_not_all_rate_limited(self):
        analysis_results = {
            "RLCOIN": {
                "signal_4h": "BUY", "rsi_4h": 45, "macd_bullish_4h": True,
                "signal_1d_rate_limited": True,
            },
            "NOTRLCOIN": {
                "signal_4h": "BUY", "rsi_4h": 45, "macd_bullish_4h": True,
                "signal_1d_rate_limited": False,
            },
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        self.assertEqual(out["scores_detail"]["RLCOIN"]["decision"], "SKIP")
        self.assertEqual(out["scores_detail"]["NOTRLCOIN"]["decision"], "SKIP")


class TestDegradedModeRsiGuard(unittest.TestCase):
    """Issue #406 : en mode dégradé, le RSI devient un garde-fou d'éligibilité BUY,
    pas un simple bonus — régression incident TRUMP (score 4, RSI 70.4, stop touché)."""

    def test_degraded_high_rsi_is_skipped_even_above_threshold(self):
        analysis_results = {
            "TRUMP": {
                "signal_4h": "BUY",              # +2
                "macd_bullish_4h": True,          # +1
                "rsi_4h": 70.4,                   # hors zone [30, 65] -> pas de bonus, garde-fou
                "signal_1d_rate_limited": True,
            },
        }
        out = _run_phase3(analysis_results, top_gainers_symbols=["TRUMP"], config=DEFAULT_CONFIG)  # +1
        detail = out["scores_detail"]["TRUMP"]
        self.assertEqual(detail["score"], 4)
        self.assertEqual(detail["decision"], "SKIP")
        self.assertEqual(detail["skip_type"], "TYPE_A")
        self.assertNotIn("TRUMP", [c["coin"] for c in out["buy_candidates"]])
        self.assertIn("mode dégradé", out["skip_coins_detail"]["TRUMP"]["skip_detail"])

    def test_degraded_healthy_rsi_stays_eligible(self):
        analysis_results = {
            "SANECOIN": {
                "signal_4h": "BUY",              # +2
                "macd_bullish_4h": True,          # +1
                "rsi_4h": 45,                     # +1, dans zone [30, 65]
                "signal_1d_rate_limited": True,
            },
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        detail = out["scores_detail"]["SANECOIN"]
        self.assertEqual(detail["score"], 4)
        self.assertEqual(detail["decision"], "BUY")
        self.assertIn("SANECOIN", [c["coin"] for c in out["buy_candidates"]])

    def test_degraded_unknown_rsi_is_skipped(self):
        analysis_results = {
            "NORSICOIN": {
                "signal_4h": "BUY", "macd_bullish_4h": True,
                "rsi_4h": None,
                "signal_1d_rate_limited": True,
            },
        }
        out = _run_phase3(analysis_results, top_gainers_symbols=["NORSICOIN"], config=DEFAULT_CONFIG)  # +1
        detail = out["scores_detail"]["NORSICOIN"]
        self.assertEqual(detail["score"], 4)
        self.assertEqual(detail["decision"], "SKIP")
        self.assertEqual(detail["skip_type"], "TYPE_A")
        self.assertIn("indisponible", out["skip_coins_detail"]["NORSICOIN"]["skip_detail"])

    def test_normal_mode_high_rsi_with_high_score_still_buys(self):
        """Hors mode dégradé, le RSI reste un bonus (issue #380) — pas un garde-fou."""
        analysis_results = {
            "HOTCOIN": {
                "signal_4h": "STRONG_BUY",        # +2
                "signal_1d": "BUY",                # +2
                "macd_bullish_4h": True,           # +1
                "rsi_4h": 70.4,                    # hors zone, pas de bonus, mais pas bloquant
                "signal_1d_rate_limited": False,
            },
        }
        out = _run_phase3(analysis_results, sentiment="Bullish", config=DEFAULT_CONFIG)  # +1
        detail = out["scores_detail"]["HOTCOIN"]
        self.assertEqual(detail["score"], 6)
        self.assertEqual(detail["decision"], "BUY")
        self.assertIn("HOTCOIN", [c["coin"] for c in out["buy_candidates"]])


class TestSignal4hRequired(unittest.TestCase):
    def test_high_score_without_4h_buy_never_gives_buy(self):
        analysis_results = {
            "NOSIGNAL": {
                "signal_4h": "NEUTRAL",
                "signal_1d": "BUY",           # +2
                "rsi_4h": 45,                  # +1
                "macd_bullish_4h": True,       # +1  => score 4, sous seuil de toute façon
            },
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        detail = out["scores_detail"]["NOSIGNAL"]
        self.assertNotEqual(detail["decision"], "BUY")


class TestMaxOpenPositions(unittest.TestCase):
    def test_skip_when_open_positions_at_max(self):
        analysis_results = {
            "NEWCOIN": {"signal_4h": "STRONG_BUY", "signal_1d": "BUY", "rsi_4h": 45, "macd_bullish_4h": True},
        }
        cfg = {**DEFAULT_CONFIG, "max_open_positions": 1}
        out = _run_phase3(analysis_results, open_positions=1, config=cfg)
        detail = out["scores_detail"]["NEWCOIN"]
        self.assertEqual(detail["decision"], "SKIP")
        self.assertEqual(detail["skip_type"], "TYPE_A")
        self.assertIn("NEWCOIN", out["skip_coins_detail"])
        self.assertIn("Positions max", out["skip_coins_detail"]["NEWCOIN"]["skip_detail"])

    def test_candidates_accepted_this_cycle_count_toward_max(self):
        """Régression issue #384 : open_positions=1, max=4, 4 candidats BUY valides
        -> seuls 3 doivent être acceptés dans buy_candidates, pas les 4 (incident cycle
        20260821_040505 : open_positions statique jamais incrémenté par la boucle)."""
        analysis_results = {
            coin: {"signal_4h": "STRONG_BUY", "signal_1d": "BUY", "rsi_4h": 45, "macd_bullish_4h": True}
            for coin in ("COINA", "COINB", "COINC", "COIND")
        }
        cfg = {**DEFAULT_CONFIG, "max_open_positions": 4}
        out = _run_phase3(analysis_results, open_positions=1, config=cfg)
        buy_coins = [c["coin"] for c in out["buy_candidates"]]
        self.assertEqual(len(buy_coins), 3)
        skipped = [c for c in analysis_results if c not in buy_coins]
        self.assertEqual(len(skipped), 1)
        skipped_coin = skipped[0]
        self.assertEqual(out["scores_detail"][skipped_coin]["decision"], "SKIP")
        self.assertEqual(out["scores_detail"][skipped_coin]["skip_type"], "TYPE_A")
        self.assertIn(skipped_coin, out["skip_coins_detail"])


class TestMaxCorrelatedPositions(unittest.TestCase):
    def test_second_correlated_coin_skipped(self):
        analysis_results = {
            "SOL": {"signal_4h": "STRONG_BUY", "signal_1d": "BUY", "rsi_4h": 45, "macd_bullish_4h": True},
            "SUI": {"signal_4h": "STRONG_BUY", "signal_1d": "BUY", "rsi_4h": 45, "macd_bullish_4h": True},
        }
        cfg = {**DEFAULT_CONFIG, "max_open_positions": 10, "max_correlated_positions": 1}
        out = _run_phase3(analysis_results, config=cfg)
        self.assertEqual(out["scores_detail"]["SOL"]["decision"], "BUY")
        self.assertEqual(out["scores_detail"]["SUI"]["decision"], "SKIP")
        self.assertEqual(out["scores_detail"]["SUI"]["skip_type"], "TYPE_A")
        self.assertIn("Corrélation", out["skip_coins_detail"]["SUI"]["skip_detail"])


class TestSellDecision(unittest.TestCase):
    def test_low_score_in_portfolio_gives_sell(self):
        analysis_results = {
            "HELDCOIN": {"signal_4h": "NEUTRAL", "signal_1d": "NEUTRAL", "in_portfolio": True},
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        detail = out["scores_detail"]["HELDCOIN"]
        self.assertLessEqual(detail["score"], 3)
        self.assertEqual(detail["decision"], "SELL")
        self.assertIn("HELDCOIN", [c["coin"] for c in out["sell_candidates"]])


class TestRsiZoneBonus(unittest.TestCase):
    """Bornes par défaut (30-65, cf. issue #380) appliquées via rsi_zone_min/rsi_zone_max."""

    def test_rsi_60_within_default_zone_gets_bonus(self):
        analysis_results = {
            "INZONE": {"signal_4h": "STRONG_BUY", "rsi_4h": 60},
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        detail = out["scores_detail"]["INZONE"]
        self.assertEqual(detail["score"], 3)
        self.assertNotIn("RSI 60 hors zone", detail["reasons"])

    def test_rsi_66_outside_default_zone_no_bonus(self):
        analysis_results = {
            "OUTOFZONE": {"signal_4h": "STRONG_BUY", "rsi_4h": 66},
        }
        out = _run_phase3(analysis_results, config=DEFAULT_CONFIG)
        detail = out["scores_detail"]["OUTOFZONE"]
        self.assertEqual(detail["score"], 2)
        self.assertIn("RSI 66 hors zone", detail["reasons"])


class TestFakeKrakenStub(unittest.TestCase):
    """Prouve que le stub fake_kraken.py fonctionne indépendamment de son usage phase."""

    def test_ticker_subcommand_via_subprocess(self):
        scenario = {"ticker": {"ETHUSDC": {"c": ["1900.0", "0.01"]}}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(scenario, f)
            scenario_path = f.name
        try:
            env = {**os.environ, "FAKE_KRAKEN_SCENARIO": scenario_path}
            result = subprocess.run(  # noqa: PLW1510 — returncode vérifié explicitement ci-dessous, avec message stderr
                [sys.executable, FAKE_KRAKEN_PATH, "ticker", "ETHUSDC", "-o", "json"],
                capture_output=True, text=True, env=env, timeout=10,
            )
            self.assertEqual(result.returncode, 0, msg=f"fake_kraken.py a échoué — stderr: {result.stderr}")
            self.assertEqual(json.loads(result.stdout), scenario["ticker"])
        finally:
            os.remove(scenario_path)


if __name__ == "__main__":
    unittest.main()
