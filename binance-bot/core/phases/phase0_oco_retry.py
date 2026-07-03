"""Rattrapage protection_failed + oco_retry_count — extrait de phase0_snapshot.txt.

Exécuté par Claude en Phase 0 après le snapshot :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase0_oco_retry.py __CYCLE_ID__

Stdout : PHASE0_OCO_DONE|retried=N
"""
import sys
import os
import json
import math
import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance, _load_config, _save_trade_history_atomic  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

try:
    with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
        history = json.load(f)
    cfg = _load_config()
    max_oco_retry = cfg.get("max_oco_retry", 3)
    unprotected = [t for t in history if t.get("status") == "open" and t.get("protection_failed") is True]

    for t in unprotected:
        coin = t["coin"]
        qty = t["quantity"]
        entry = t["entry_price"]
        tp_calc = t["tp_price"]
        stop_calc = t["stop_price"]

        # Idempotence : vérifier qu'aucun OCO actif n'existe déjà
        open_orders_raw = binance("open-orders", "-o", "json")
        open_orders = json.loads(open_orders_raw).get("open", {})
        has_oco = False  # Kraken n'a pas d'OCO natif — logique revue en T3
        if has_oco:
            for item in history:
                if item.get("trade_id") == t.get("trade_id"):
                    item["protection_failed"] = False
            tg(f"ℹ️ {coin} : OCO déjà actif, protection_failed corrigé")
            continue

        ticker_raw = binance("ticker", f"{coin}USDC", "-o", "json")
        ticker_data = json.loads(ticker_raw)
        prix_actuel = float(ticker_data.get(f"{coin}USDC", {}).get("c", [0])[0])

        if prix_actuel > tp_calc:
            sell_raw = binance(
                "spot", "new-order", "--symbol", f"{coin}USDC",
                "--side", "SELL", "--type", "MARKET", "--quantity", str(qty), "--profile", "agent-profile"
            )
            sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
            if sell_resp.get("orderId"):
                fill_exit = float(sell_resp.get("cummulativeQuoteQty", 0)) / float(sell_resp.get("executedQty", qty))
                pnl_usdc = (fill_exit - entry) * qty
                pnl_pct = (fill_exit - entry) / entry * 100
                for item in history:
                    if item.get("trade_id") == t.get("trade_id"):
                        item.update({
                            "status": "closed", "exit_price": fill_exit,
                            "pnl_usdc": pnl_usdc, "pnl_pct": pnl_pct,
                            "exit_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "protection_failed": False, "close_reason": "market_above_tp",
                        })
                tg(f"✅ {coin} fermé à market (prix {prix_actuel:.4g} > TP {tp_calc:.4g}) : {pnl_usdc:+.2f} USDC ({pnl_pct:+.1f}%)")
            else:
                tg(f"⚠️ {coin} : fermeture market échouée — {sell_raw[:200]}")
        else:
            oco_retry_count = t.get("oco_retry_count", 0)

            if oco_retry_count >= max_oco_retry:
                sell_raw = binance(
                    "spot", "new-order", "--symbol", f"{coin}USDC",
                    "--side", "SELL", "--type", "MARKET", "--quantity", str(qty), "--profile", "agent-profile"
                )
                sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
                if sell_resp.get("orderId"):
                    fill_exit = float(sell_resp.get("cummulativeQuoteQty", 0)) / float(sell_resp.get("executedQty", qty))
                    pnl_usdc = (fill_exit - entry) * qty
                    pnl_pct = (fill_exit - entry) / entry * 100
                    for item in history:
                        if item.get("trade_id") == t.get("trade_id"):
                            item.update({
                                "status": "closed", "exit_price": fill_exit,
                                "pnl_usdc": pnl_usdc, "pnl_pct": pnl_pct,
                                "exit_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "protection_failed": False, "close_reason": "protection_exhausted",
                                "oco_retry_count": 0,
                            })
                    tg(f"🚨 {coin} : OCO rattrapage échoué {max_oco_retry} fois. Fermeture SELL MARKET forcée.\n{pnl_usdc:+.2f} USDC ({pnl_pct:+.1f}%)")
                else:
                    tg(f"⚠️ {coin} : fermeture SELL MARKET (fallback protection_exhausted) échouée — {sell_raw[:200]}")
            else:
                for item in history:
                    if item.get("trade_id") == t.get("trade_id"):
                        item["oco_retry_count"] = oco_retry_count + 1
                _save_trade_history_atomic(history)

                pairs_raw = binance("pairs", "--pair", f"{coin}USDC", "-o", "json")
                pair_data = json.loads(pairs_raw).get(f"{coin}USDC", {})
                lot_dec = int(pair_data.get("lot_decimals", 8))
                step = 10 ** (-lot_dec)
                qty_adj = round(math.floor(qty / step) * step, lot_dec)

                tp_oco = max(tp_calc, prix_actuel * 1.001)
                oco_raw = binance(
                    "spot", "order-list-oco",
                    "--symbol", f"{coin}USDC",
                    "--side", "SELL",
                    "--quantity", str(qty_adj),
                    "--above-type", "LIMIT_MAKER",
                    "--above-price", str(round(tp_oco, 8)),
                    "--below-type", "STOP_LOSS_LIMIT",
                    "--below-price", str(round(stop_calc, 8)),
                    "--below-stop-price", str(round(stop_calc * 1.002, 8)),
                    "--below-time-in-force", "GTC",
                    "--profile", "agent-profile",
                )
                oco_resp = json.loads(oco_raw) if oco_raw.strip() else {}
                if oco_resp.get("orderListId"):
                    reports = {r["type"]: r for r in oco_resp.get("orderReports", [])}
                    tp_id = reports.get("LIMIT_MAKER", {}).get("orderId")
                    sl_id = reports.get("STOP_LOSS_LIMIT", {}).get("orderId")
                    for item in history:
                        if item.get("trade_id") == t.get("trade_id"):
                            item.update({
                                "protection_failed": False, "tp_order_id": tp_id,
                                "stop_order_id": sl_id, "order_list_id": oco_resp["orderListId"],
                                "tp_price": tp_oco, "stop_price": stop_calc, "oco_retry_count": 0,
                            })
                    tg(f"🛡️ {coin} : OCO de rattrapage placé (tentative {oco_retry_count + 1}) — TP {tp_oco:.4g} / SL {stop_calc:.4g}")
                else:
                    tg(f"⚠️ {coin} : OCO rattrapage échoué (tentative {oco_retry_count + 1}/{max_oco_retry})")

    _save_trade_history_atomic(history)
    retried = len(unprotected)
    print(f"PHASE0_OCO_DONE|retried={retried}")
    with open(f"/tmp/cycle_{CYCLE_ID}_phase0_oco_retry_output.json", "w") as f:
        json.dump({"retried": retried}, f)

except Exception as e:
    tg(f"⚠️ Erreur routine rattrapage protection_failed : {e}")
    print(f"PHASE0_OCO_ERROR|{e}")
    sys.exit(1)
