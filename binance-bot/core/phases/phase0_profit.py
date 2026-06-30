"""Réalisation de profits (min_profit_pct_take) — extrait de phase0_snapshot.txt.

Exécuté par Claude en Phase 0 après le trailing stop :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase0_profit.py __CYCLE_ID__

Stdout : PHASE0_PROFIT_DONE|closed=N
"""
import sys
import os
import json
import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance, _load_config, _save_trade_history_atomic  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
    history = json.load(f)

profit_summary = []
min_profit = _load_config().get("min_profit_pct_take", 2.0)

for pos in history:
    if pos.get("status") != "open":
        continue
    coin = pos.get("coin")
    entry_price = float(pos.get("entry_price", 0))
    qty = float(pos.get("quantity", 0))
    if not entry_price or not qty:
        continue

    try:
        ticker_raw = binance("spot", "ticker-price", "--symbol", f"{coin}USDC", "--profile", "agent-profile")
        ticker_data = json.loads(ticker_raw)
        current_price = float(ticker_data.get("price", entry_price))
    except Exception:
        continue

    pnl_pct = ((current_price - entry_price) / entry_price) * 100

    if pnl_pct >= min_profit:
        try:
            # Annuler les ordres OCO actifs avant SELL MARKET (sinon Binance refuse le MARKET)
            binance("spot", "cancel-open-orders", "--symbol", f"{coin}USDC", "--profile", "agent-profile")
        except Exception:
            pass
        try:
            sell_raw = binance(
                "spot", "new-order", "--symbol", f"{coin}USDC",
                "--side", "SELL", "--type", "MARKET", "--quantity", str(qty), "--profile", "agent-profile"
            )
            sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
            if sell_resp.get("orderId"):
                exit_price = float(sell_resp.get("cummulativeQuoteQty", 0)) / float(sell_resp.get("executedQty", qty))
                actual_pnl_usdc = (exit_price - entry_price) * qty
                actual_pnl_pct = (exit_price - entry_price) / entry_price * 100
                pos.update({
                    "status": "closed",
                    "exit_price": exit_price,
                    "pnl_usdc": actual_pnl_usdc,
                    "pnl_pct": actual_pnl_pct,
                    "exit_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "close_reason": "profit_target_phase0",
                })
                profit_summary.append(f"✅ {coin} : {actual_pnl_pct:+.1f}% ({actual_pnl_usdc:+.2f} USDC)")
                tg(f"✅ Phase 0 — {coin} vendu (P&L cible)\n{actual_pnl_pct:+.1f}% | {actual_pnl_usdc:+.2f} USDC")
        except Exception as e:
            # OCO déjà annulé — marquer la position comme non protégée pour phase0_oco_retry
            pos["protection_failed"] = True
            _save_trade_history_atomic(history)
            tg(f"⚠️ Fermeture P&L {coin} échouée (OCO annulé, position non protégée) : {e}")

if profit_summary:
    _save_trade_history_atomic(history)
    tg("📊 Phase 0 — Positions fermées (profit cible) :\n" + "\n".join(profit_summary))

closed = len(profit_summary)
print(f"PHASE0_PROFIT_DONE|closed={closed}")
with open(f"/tmp/cycle_{CYCLE_ID}_phase0_profit_output.json", "w") as f:
    json.dump({"closed": closed}, f)
