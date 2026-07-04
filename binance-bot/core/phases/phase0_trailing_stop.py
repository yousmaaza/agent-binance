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

from core.trade_helpers import tg, binance, _save_trade_history_atomic, log_phase0_event  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"


def _round_price(p, tick):
    return round(round(p / tick) * tick, 8)


def _round_qty(q, step):
    return round(math.floor(q / step) * step, 8)


with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
    history = json.load(f)

ts_updates = []
for t in history:
    if t.get("status") != "open" or not t.get("sl_order_txid"):
        continue
    coin = t["coin"]
    entry = float(t["entry_price"])
    cur_stop = float(t["stop_price"])
    trail_dist = entry - cur_stop

    try:
        ticker_raw = binance("ticker", f"{coin}USDC", "-o", "json")
        ticker_data = json.loads(ticker_raw)
        price = float(ticker_data.get(f"{coin}USDC", {}).get("c", [0])[0])
    except Exception as e:
        log_phase0_event(CYCLE_ID, "phase0_trailing_stop", coin, "price_fetch_error", {
            "error": str(e),
        })
        tg(f"⚠️ Trailing stop {coin} : impossible de récupérer le prix ({e})")
        continue

    new_stop = round(price - trail_dist, 8)

    if new_stop <= cur_stop + trail_dist * 0.20:
        log_phase0_event(CYCLE_ID, "phase0_trailing_stop", coin, "ts_update_skip", {
            "reason": "new_stop_too_close",
            "current_price": price,
            "current_stop": cur_stop,
            "new_stop": new_stop,
        })
        continue
    if new_stop >= price * 0.98:
        log_phase0_event(CYCLE_ID, "phase0_trailing_stop", coin, "ts_update_skip", {
            "reason": "new_stop_too_high",
            "current_price": price,
            "new_stop": new_stop,
        })
        continue

    try:
        sl_txid = t["sl_order_txid"]
        binance("order", "cancel", sl_txid, "-o", "json", "--yes")
    except Exception as e:
        log_phase0_event(CYCLE_ID, "phase0_trailing_stop", coin, "sl_cancel_error", {
            "sl_txid": sl_txid,
            "error": str(e),
        })
        tg(f"⚠️ Trailing stop {coin} : échec annulation SL ({e}), skip")
        continue

    try:
        pairs_raw = binance("pairs", "--pair", f"{coin}USDC", "-o", "json")
        pair_data = json.loads(pairs_raw).get(f"{coin}USDC", {})
        lot_dec = int(pair_data.get("lot_decimals", 8))
        tick = float(pair_data.get("tick_size", "0.00000001"))
        lot = 10 ** (-lot_dec)
        qty = _round_qty(float(t["quantity"]), lot)
        new_stop_r = _round_price(new_stop, tick)
    except Exception:
        qty = float(t["quantity"])
        new_stop_r = new_stop

    try:
        sl_raw = binance(
            "order", "sell", f"{coin}USDC", str(qty),
            "--type", "stop-loss", "--price", str(new_stop_r),
            "-o", "json", "--yes",
        )
        sl_resp = json.loads(sl_raw)
        new_sl_txid = sl_resp.get("txid", [None])[0]
    except Exception as e:
        log_phase0_event(CYCLE_ID, "phase0_trailing_stop", coin, "ts_update_failed", {
            "reason": "sl_placement_error",
            "error": str(e),
            "attempted_new_stop": new_stop_r,
        })
        tg(f"⚠️ Trailing stop {coin} : échec placement nouvel SL ({e})")
        continue

    t["stop_price"] = new_stop_r
    t["sl_order_txid"] = new_sl_txid
    _save_trade_history_atomic(history)

    log_phase0_event(CYCLE_ID, "phase0_trailing_stop", coin, "ts_update_success", {
        "old_stop": cur_stop,
        "new_stop": new_stop_r,
        "current_price": price,
        "new_sl_txid": new_sl_txid,
    })

    ts_updates.append(f"{coin}: stop {cur_stop:.4g}→{new_stop_r:.4g}")
    tg(
        f"📈 {coin} trailing stop remonté\n"
        f"Stop : {cur_stop:.4g} → {new_stop_r:.4g}\n"
        f"Prix actuel : {price:.4g}"
    )

if ts_updates:
    tg("🔄 Trailing stops mis à jour ce cycle :\n" + "\n".join(ts_updates))

updated = len(ts_updates)
print(f"PHASE0_TS_DONE|updated={updated}")
with open(f"/tmp/cycle_{CYCLE_ID}_phase0_trailing_stop_output.json", "w") as f:
    json.dump({"updated": updated}, f)
