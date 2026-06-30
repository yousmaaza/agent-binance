"""Trailing stop logic — extrait de phase0_snapshot.txt.

Exécuté par Claude en Phase 0 après le rattrapage OCO :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase0_trailing_stop.py __CYCLE_ID__

Stdout : PHASE0_TS_DONE|updated=N
"""
import sys
import os
import json
import math

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance, _save_trade_history_atomic  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"


def _round_price(p, tick):
    return round(round(p / tick) * tick, 8)


def _round_qty(q, step):
    return round(math.floor(q / step) * step, 8)


with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
    history = json.load(f)

ts_updates = []
for t in history:
    if t.get("status") != "open" or not t.get("order_list_id"):
        continue
    coin = t["coin"]
    entry = float(t["entry_price"])
    cur_stop = float(t["stop_price"])
    cur_tp = float(t["tp_price"])
    trail_dist = entry - cur_stop

    try:
        ticker = json.loads(
            binance("spot", "ticker-price", "--symbol", f"{coin}USDC", "--profile", "agent-profile")
        )
        price = float(ticker["price"])
    except Exception as e:
        tg(f"⚠️ Trailing stop {coin} : impossible de récupérer le prix ({e})")
        continue

    new_stop = round(price - trail_dist, 8)

    if new_stop <= cur_stop + trail_dist * 0.20:
        continue
    if new_stop >= price * 0.98:
        continue

    new_tp = max(cur_tp, round(price + trail_dist * 3, 8))

    try:
        binance(
            "spot", "delete-order-list",
            "--symbol", f"{coin}USDC",
            "--order-list-id", str(t["order_list_id"]),
            "--profile", "agent-profile",
        )
    except Exception as e:
        tg(f"⚠️ Trailing stop {coin} : échec annulation OCO ({e}), skip")
        continue

    try:
        info_raw = binance("spot", "exchange-info", "--symbol", f"{coin}USDC", "--profile", "agent-profile")
        info = json.loads(info_raw)
        filters = {f["filterType"]: f for f in info.get("filters", [])}
        tick = float(filters.get("PRICE_FILTER", {}).get("tickSize", "0.00000001"))
        lot = float(filters.get("LOT_SIZE", {}).get("stepSize", "0.00000001"))
        qty = _round_qty(float(t["quantity"]), lot)
        new_stop_r = _round_price(new_stop, tick)
        new_tp_r = _round_price(new_tp, tick)
        stop_limit_r = _round_price(new_stop * 1.002, tick)
    except Exception:
        qty = float(t["quantity"])
        new_stop_r, new_tp_r, stop_limit_r = new_stop, new_tp, round(new_stop * 1.002, 8)

    try:
        oco_raw = binance(
            "spot", "order-list-oco",
            "--symbol", f"{coin}USDC",
            "--side", "SELL",
            "--quantity", str(qty),
            "--above-type", "LIMIT_MAKER",
            "--above-price", str(new_tp_r),
            "--below-type", "STOP_LOSS_LIMIT",
            "--below-price", str(new_stop_r),
            "--below-stop-price", str(stop_limit_r),
            "--below-time-in-force", "GTC",
            "--profile", "agent-profile",
        )
        oco = json.loads(oco_raw)
        new_list_id = oco.get("orderListId")
        new_tp_id = next(
            (o["orderId"] for o in oco.get("orderReports", []) if o.get("type") == "LIMIT_MAKER"), None
        )
        new_sl_id = next(
            (o["orderId"] for o in oco.get("orderReports", []) if o.get("type") == "STOP_LOSS_LIMIT"), None
        )
    except Exception as e:
        tg(f"⚠️ Trailing stop {coin} : échec placement nouvel OCO ({e})")
        continue

    t["stop_price"] = new_stop_r
    t["tp_price"] = new_tp_r
    t["order_list_id"] = new_list_id
    t["stop_order_id"] = new_sl_id
    t["tp_order_id"] = new_tp_id
    _save_trade_history_atomic(history)

    ts_updates.append(f"{coin}: stop {cur_stop:.4g}→{new_stop_r:.4g} | TP {cur_tp:.4g}→{new_tp_r:.4g}")
    tg(
        f"📈 {coin} trailing stop remonté\n"
        f"Stop : {cur_stop:.4g} → {new_stop_r:.4g}\n"
        f"TP : {cur_tp:.4g} → {new_tp_r:.4g}\n"
        f"Prix actuel : {price:.4g}"
    )

if ts_updates:
    tg("🔄 Trailing stops mis à jour ce cycle :\n" + "\n".join(ts_updates))

updated = len(ts_updates)
print(f"PHASE0_TS_DONE|updated={updated}")
with open(f"/tmp/cycle_{CYCLE_ID}_phase0_trailing_stop_output.json", "w") as f:
    json.dump({"updated": updated}, f)
