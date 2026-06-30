"""Calcul des scores 0-10 et décisions BUY/HOLD/SKIP — phase 3.

Lit les données d'analyse depuis /tmp/cycle_{CYCLE_ID}_phase3_input.json :
{
  "analysis_results": {coin: {signal_4h, signal_1d, rsi_4h, macd_bullish_4h,
                               volume_24h, signal_1d_rate_limited, in_portfolio}},
  "top_gainers_symbols": [...],
  "breakout_symbols": [...],
  "sentiment": "Bullish|Neutral|Bearish",
  "open_positions": N,
  "budget_disponible": X,
  "config": {...}
}

Exécuté par Claude en Phase 3 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase3_scoring.py __CYCLE_ID__

Stdout : PHASE3_DONE|N_buy=X|skipped=Y|top_score=Z
Output : /tmp/cycle_{CYCLE_ID}_phase3_output.json
"""
import sys
import os
import json

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, _load_config  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

in_path = f"/tmp/cycle_{CYCLE_ID}_phase3_input.json"
with open(in_path) as f:
    inp = json.load(f)

analysis_results = inp.get("analysis_results", {})
top_gainers_symbols = inp.get("top_gainers_symbols", [])
breakout_symbols = inp.get("breakout_symbols", [])
sentiment = inp.get("sentiment", "Neutral")
open_positions = inp.get("open_positions", 0)
cfg = inp.get("config") or _load_config()

min_signal_score = cfg.get("min_signal_score", 6)
max_open_positions = cfg.get("max_open_positions", 5)
max_correlated_positions = cfg.get("max_correlated_positions", 2)

# Mode dégradé : rate limit TradingView 1D
buy_4h = [c for c in analysis_results if analysis_results[c].get("signal_4h") in ("BUY", "STRONG_BUY")]
all_rl = bool(buy_4h) and all(analysis_results[c].get("signal_1d_rate_limited", False) for c in buy_4h)
if all_rl:
    effective_min_score = cfg.get("min_signal_score_degraded", min_signal_score)
    tg(f"⚠️ Mode dégradé 1D (rate limit TradingView) — seuil abaissé à {effective_min_score}/10 (normal : {min_signal_score}/10)")
else:
    effective_min_score = min_signal_score

CORRELATED_GROUP = {"SOL", "SUI", "STX", "ETH"}

buy_candidates = []
sell_candidates = []
skip_coins_detail = {}
top_score = 0

volumes = [analysis_results[c].get("volume_24h", 0) for c in analysis_results]
sorted_vols = sorted(volumes)
median_vol = sorted_vols[len(sorted_vols) // 2] if sorted_vols else 0

for coin, data in analysis_results.items():
    signal_4h = data.get("signal_4h", "NEUTRAL")
    signal_1d = data.get("signal_1d", "NEUTRAL")
    rsi_4h = data.get("rsi_4h")
    macd_bullish = data.get("macd_bullish_4h", False)
    volume_24h = data.get("volume_24h", 0)

    score = 0
    if signal_4h in ("BUY", "STRONG_BUY"):
        score += 2
    if signal_1d in ("BUY", "STRONG_BUY"):
        score += 2
    if rsi_4h is not None and 30 <= rsi_4h <= 55:
        score += 1
    if macd_bullish:
        score += 1
    if coin in top_gainers_symbols:
        score += 1
    if coin in breakout_symbols:
        score += 1
    if sentiment == "Bullish":
        score += 1
    if median_vol > 0 and volume_24h > 2 * median_vol:
        score += 1

    top_score = max(top_score, score)

    if score >= effective_min_score and signal_4h in ("BUY", "STRONG_BUY"):
        if open_positions >= max_open_positions:
            skip_coins_detail[coin] = {
                "skip_type": "TYPE_A",
                "skip_detail": f"Positions max atteintes ({open_positions}/{max_open_positions})",
            }
        elif coin.upper() in CORRELATED_GROUP:
            correlated_count = sum(1 for bc in buy_candidates if bc["coin"].upper() in CORRELATED_GROUP)
            if correlated_count >= max_correlated_positions:
                skip_coins_detail[coin] = {
                    "skip_type": "TYPE_A",
                    "skip_detail": f"Corrélation : déjà {correlated_count} coins du groupe L1-alts",
                }
            else:
                buy_candidates.append({
                    "coin": coin, "score": score,
                    "signal_4h": signal_4h, "signal_1d": signal_1d, "rsi_4h": rsi_4h,
                })
        else:
            buy_candidates.append({
                "coin": coin, "score": score,
                "signal_4h": signal_4h, "signal_1d": signal_1d, "rsi_4h": rsi_4h,
            })
    elif score <= 3 and data.get("in_portfolio"):
        sell_candidates.append({"coin": coin, "score": score})

N_buy = len(buy_candidates)
tg(
    f"🧠 Phase 3 — Stratégie\nTop score : {top_score}/10\n"
    f"{N_buy} BUY candidates : {[c['coin'] for c in buy_candidates]}\n"
    f"Skipped : {len(skip_coins_detail)} coins"
)

out = {
    "buy_candidates": buy_candidates,
    "sell_candidates": sell_candidates,
    "skip_coins_detail": skip_coins_detail,
    "top_score": top_score,
    "N_buy": N_buy,
}
with open(f"/tmp/cycle_{CYCLE_ID}_phase3_output.json", "w") as f:
    json.dump(out, f)

print(f"PHASE3_DONE|N_buy={N_buy}|skipped={len(skip_coins_detail)}|top_score={top_score}")
