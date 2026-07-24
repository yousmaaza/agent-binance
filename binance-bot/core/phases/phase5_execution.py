"""Exécution des ordres (drift check, BUY MARKET, fill retry, TP/SL, pose stop-loss) — phase 5.

Lit les ordres préparés par la Phase 4 depuis /tmp/cycle_{CYCLE_ID}_phase5_input.json :
{
  "ordres_prepares": [{coin, quantite, prix_entry, prix_stop, prix_tp,
                       montant_ordre, risk_usdc, stop_distance_pct, score}],
  "config": {...}
}

Pour chaque ordre, dans l'ordre de score décroissant :
1. Re-fetch prix, skip TYPE_C si drift > price_deviation_max_pct
2. Re-fetch solde USDC, skip TYPE_C si insuffisant
3. BUY MARKET puis query du fill (3 tentatives, 1s d'intervalle), skip TYPE_C si non rempli
4. Recalcule TP/SL sur actual_entry ; clôture immédiate au marché si prix post-fill >= actual_tp
5. Récupère lot_decimals pour arrondir la quantité de l'ordre SL
6. Pose l'ordre SELL STOP-LOSS ; protection_failed=True + alerte Telegram si échec

Exécuté par Claude en Phase 5 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase5_execution.py __CYCLE_ID__

Stdout : PHASE5_DONE|executed=N|skipped=M
Output : /tmp/cycle_{CYCLE_ID}_phase5_output.json
"""
import sys
import os
import json
import math
import time
import uuid
import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance, _load_config, _save_trade_history_atomic  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

in_path = f"/tmp/cycle_{CYCLE_ID}_phase5_input.json"
with open(in_path) as f:
    inp = json.load(f)

ordres_prepares = inp.get("ordres_prepares", [])
cfg = inp.get("config") or _load_config()

price_deviation_max_pct = cfg.get("price_deviation_max_pct", 0.02)
reward_risk_ratio = cfg.get("reward_risk_ratio", 2)

with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
    history = json.load(f)

orders_executed = []
orders_skipped_detail = {}

for order in sorted(ordres_prepares, key=lambda o: o.get("score", 0), reverse=True):
    coin = order["coin"]
    quantite = order["quantite"]
    prix_entry = order["prix_entry"]
    montant_ordre = order["montant_ordre"]
    stop_distance_pct = order["stop_distance_pct"]
    risk_usdc = order.get("risk_usdc")
    score = order.get("score", 0)

    try:
        # 1. Re-fetch prix, check drift
        ticker_raw = binance("ticker", f"{coin}USDC", "-o", "json")
        prix_refetch = float(json.loads(ticker_raw).get(f"{coin}USDC", {}).get("c", [0])[0])
        drift = abs(prix_refetch - prix_entry) / prix_entry
        if drift > price_deviation_max_pct:
            skip_detail_str = f"Drift prix > {price_deviation_max_pct * 100:.1f}% ({drift * 100:.1f}%)"
            orders_skipped_detail[coin] = {"skip_type": "TYPE_C", "skip_detail": skip_detail_str}
            continue

        # 2. Re-fetch solde USDC
        balance_raw = binance("balance", "-o", "json")
        usdc_free = float(json.loads(balance_raw).get("USDC", 0))
        if usdc_free < montant_ordre:
            skip_detail_str = f"Solde USDC insuffisant ({usdc_free:.2f} < {montant_ordre:.2f})"
            orders_skipped_detail[coin] = {"skip_type": "TYPE_C", "skip_detail": skip_detail_str}
            continue

        # 3. BUY MARKET + query du fill (3 tentatives, 1s entre chaque)
        buy_raw = binance("order", "buy", f"{coin}USDC", str(quantite), "--type", "market", "-o", "json", "--yes")
        entry_txid = json.loads(buy_raw)["txid"][0]

        fill = {}
        for attempt in range(3):
            query_raw = binance("query-orders", entry_txid, "-o", "json")
            fill = json.loads(query_raw).get(entry_txid, {})
            if fill.get("status") == "closed":
                break
            if attempt < 2:
                time.sleep(1)

        if fill.get("status") != "closed":
            skip_detail_str = f"BUY MARKET non rempli (status: {fill.get('status')})"
            orders_skipped_detail[coin] = {"skip_type": "TYPE_C", "skip_detail": skip_detail_str}
            continue

        actual_entry = float(fill["cost"]) / float(fill["vol_exec"])
        actual_qty = float(fill["vol_exec"])
        entry_order_id = entry_txid

        # 4. Re-fetch prix post-fill, recalcule TP/SL
        ticker_raw2 = binance("ticker", f"{coin}USDC", "-o", "json")
        prix_post_fill = float(json.loads(ticker_raw2).get(f"{coin}USDC", {}).get("c", [0])[0])

        actual_stop = actual_entry * (1 - stop_distance_pct)
        actual_tp = actual_entry * (1 + stop_distance_pct * reward_risk_ratio)

        if prix_post_fill >= actual_tp:
            sell_raw = binance("order", "sell", f"{coin}USDC", str(actual_qty), "--type", "market", "-o", "json", "--yes")
            sell_txid = json.loads(sell_raw)["txid"][0]

            exit_fill = {}
            for attempt in range(3):
                query_raw = binance("query-orders", sell_txid, "-o", "json")
                exit_fill = json.loads(query_raw).get(sell_txid, {})
                if exit_fill.get("status") == "closed":
                    break
                if attempt < 2:
                    time.sleep(1)

            avg_exit = float(exit_fill["cost"]) / float(exit_fill["vol_exec"])
            pnl_usdc = (avg_exit - actual_entry) * actual_qty
            pnl_pct = (avg_exit - actual_entry) / actual_entry * 100

            trade_id = str(uuid.uuid4())[:8]
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            history.append({
                "trade_id": trade_id,
                "date": now_iso,
                "coin": coin,
                "side": "BUY",
                "signal_score": score,
                "entry_price": actual_entry,
                "stop_price": actual_stop,
                "tp_price": actual_tp,
                "quantity": actual_qty,
                "risk_usdc": risk_usdc,
                "entry_order_id": entry_order_id,
                "sl_order_txid": None,
                "protection_failed": False,
                "status": "closed",
                "exit_price": avg_exit,
                "exit_date": now_iso,
                "pnl_usdc": pnl_usdc,
                "pnl_pct": pnl_pct,
                "close_reason": "market_above_tp_at_fill",
            })
            _save_trade_history_atomic(history)

            tg(f"⚡ {coin} : TP dépassé au fill, fermé à market → {pnl_usdc:+.2f} USDC")
            orders_executed.append({
                "coin": coin, "actual_entry": actual_entry, "actual_qty": actual_qty,
                "entry_order_id": entry_order_id, "closed_at_fill": True,
            })
            continue

        # 5. Filtres marché (lot_decimals) pour l'ordre SL
        pairs_raw = binance("pairs", "--pair", f"{coin}USDC", "-o", "json")
        pair_data = json.loads(pairs_raw).get(f"{coin}USDC", {})
        lot_dec = int(pair_data.get("lot_decimals", 8))
        step = 10 ** (-lot_dec)
        actual_qty_sl = round(math.floor(actual_qty / step) * step, lot_dec)

        # 6. Placer l'ordre SELL STOP-LOSS
        protection_failed = False
        sl_order_txid = None
        sl_err_msg = ""
        try:
            sl_raw = binance("order", "sell", f"{coin}USDC", str(actual_qty_sl), "--type", "stop-loss", "--price", str(actual_stop), "-o", "json", "--yes")
            sl_order_txid = json.loads(sl_raw).get("txid", [None])[0]
            if not sl_order_txid:
                protection_failed = True
        except Exception as sl_err:
            protection_failed = True
            sl_err_msg = f" {sl_err}"

        if protection_failed:
            tg(f"⚠️ {coin} : BUY OK mais SL échoué — position NON protégée !{sl_err_msg}")

        trade_id = str(uuid.uuid4())[:8]
        history.append({
            "trade_id": trade_id,
            "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "coin": coin,
            "side": "BUY",
            "signal_score": score,
            "entry_price": actual_entry,
            "stop_price": actual_stop,
            "tp_price": actual_tp,
            "quantity": actual_qty,
            "risk_usdc": risk_usdc,
            "entry_order_id": entry_order_id,
            "sl_order_txid": sl_order_txid,
            "protection_failed": protection_failed,
            "status": "open",
            "exit_price": None,
            "exit_date": None,
            "pnl_usdc": None,
            "pnl_pct": None,
        })
        _save_trade_history_atomic(history)

        tg(
            f"⚡ BUY MARKET {coin}\n{actual_qty} @ {actual_entry:.4g} USDC\n"
            f"🛑 Stop : {actual_stop:.4g}\n🎯 TP cible : {actual_tp:.4g}\nScore : {score}/10"
        )
        orders_executed.append({
            "coin": coin, "actual_entry": actual_entry, "actual_stop": actual_stop,
            "actual_tp": actual_tp, "actual_qty": actual_qty, "entry_order_id": entry_order_id,
            "sl_order_txid": sl_order_txid, "protection_failed": protection_failed,
            "closed_at_fill": False,
        })

    except Exception as e:
        skip_detail_str = f"Erreur exécution : {e}"
        orders_skipped_detail[coin] = {"skip_type": "TYPE_C", "skip_detail": skip_detail_str}
        tg(f"⚠️ {coin} : erreur pendant l'exécution — {e}")

executed = len(orders_executed)
skipped = len(orders_skipped_detail)

tg(f"📊 Phase 5 résumé\nExécutés : {executed}\nSkippés : {skipped}\nDétails : {orders_skipped_detail}")

out = {
    "executed": executed,
    "skipped": skipped,
    "orders_executed": orders_executed,
    "orders_skipped_detail": orders_skipped_detail,
}
with open(f"/tmp/cycle_{CYCLE_ID}_phase5_output.json", "w") as f:
    json.dump(out, f)

print(f"PHASE5_DONE|executed={executed}|skipped={skipped}")
