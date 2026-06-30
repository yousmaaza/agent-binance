"""BUY MARKET + OCO + sauvegarde trade_history — phase 5.

Lit le trade à enregistrer depuis /tmp/cycle_{CYCLE_ID}_phase5_input.json :
{
  "trade": {
    "coin": "BTC",
    "signal_score": 7,
    "actual_entry": 60000.0,
    "actual_stop": 57600.0,
    "actual_tp": 64800.0,
    "actual_qty": 0.001,
    "risk_usdc": 1.5,
    "entry_order_id": 123456,
    "stop_order_id": 123457,
    "tp_order_id": 123458,
    "order_list_id": 789,
    "protection_failed": false
  }
}

Exécuté par Claude en Phase 5 après chaque BUY MARKET exécuté :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase5_execution.py __CYCLE_ID__

Stdout : PHASE5_SAVE_DONE|coin=BTC|trade_id=abc12345
"""
import sys
import os
import json
import uuid
import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import _save_trade_history_atomic  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

in_path = f"/tmp/cycle_{CYCLE_ID}_phase5_input.json"
with open(in_path) as f:
    inp = json.load(f)

trade = inp.get("trade", {})

with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
    history = json.load(f)

trade_id = str(uuid.uuid4())[:8]
history.append({
    "trade_id": trade_id,
    "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "coin": trade["coin"],
    "side": "BUY",
    "signal_score": trade.get("signal_score"),
    "entry_price": trade.get("actual_entry"),
    "stop_price": trade.get("actual_stop"),
    "tp_price": trade.get("actual_tp"),
    "quantity": trade.get("actual_qty"),
    "risk_usdc": trade.get("risk_usdc"),
    "entry_order_id": trade.get("entry_order_id"),
    "stop_order_id": trade.get("stop_order_id"),
    "tp_order_id": trade.get("tp_order_id"),
    "order_list_id": trade.get("order_list_id"),
    "protection_failed": trade.get("protection_failed", False),
    "status": "open",
    "exit_price": None,
    "exit_date": None,
    "pnl_usdc": None,
    "pnl_pct": None,
})
_save_trade_history_atomic(history)

print(f"PHASE5_SAVE_DONE|coin={trade['coin']}|trade_id={trade_id}")
