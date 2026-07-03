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

from core.trade_helpers import tg, binance, _load_config, _save_trade_history_atomic, log_phase0_event  # noqa: E402

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

        log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "protection_recovery_start", {
            "oco_retry_count": t.get("oco_retry_count", 0),
            "entry_price": entry,
            "stop_price": stop_calc,
            "tp_price": tp_calc,
        })

        # Idempotence : vérifier si un SL actif existe déjà
        sl_txid = t.get("sl_order_txid")
        if sl_txid:
            qs_raw = binance("query-orders", sl_txid, "-o", "json")
            qs_data = json.loads(qs_raw) if qs_raw.strip() else {}
            sl_status = qs_data.get(sl_txid, {}).get("status", "unknown")
            if sl_status == "open":
                log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "sl_already_active_skip", {
                    "sl_txid": sl_txid,
                    "sl_status": sl_status,
                })
                tg(f"ℹ️ {coin} : SL déjà actif ({sl_txid}), protection_failed corrigé")
                for item in history:
                    if item.get("trade_id") == t.get("trade_id"):
                        item["protection_failed"] = False
                continue

        ticker_raw = binance("ticker", f"{coin}USDC", "-o", "json")
        ticker_data = json.loads(ticker_raw)
        prix_actuel = float(ticker_data.get(f"{coin}USDC", {}).get("c", [0])[0])

        if prix_actuel > tp_calc:
            log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "force_close_above_tp", {
                "current_price": prix_actuel,
                "tp_price": tp_calc,
                "reason": "price_above_tp_protection_failed",
            })
            sell_raw = binance("order", "sell", f"{coin}USDC", str(qty), "--type", "market", "-o", "json", "--yes")
            sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
            sell_txid = sell_resp.get("txid", [None])[0]
            if sell_txid:
                import time; time.sleep(1)
                fill_raw = binance("query-orders", sell_txid, "-o", "json")
                fill = json.loads(fill_raw).get(sell_txid, {})
                fill_exit = float(fill.get("cost", 0)) / float(fill.get("vol_exec", qty)) if fill.get("vol_exec") else prix_actuel
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
                log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "force_close_success", {
                    "exit_price": fill_exit,
                    "pnl_usdc": pnl_usdc,
                    "pnl_pct": pnl_pct,
                })
                tg(f"✅ {coin} fermé à market (prix {prix_actuel:.4g} > TP {tp_calc:.4g}) : {pnl_usdc:+.2f} USDC ({pnl_pct:+.1f}%)")
            else:
                log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "force_close_failed", {
                    "reason": "market_order_failed",
                    "error": sell_raw[:200],
                })
                tg(f"⚠️ {coin} : fermeture market échouée — {sell_raw[:200]}")
        else:
            oco_retry_count = t.get("oco_retry_count", 0)

            if oco_retry_count >= max_oco_retry:
                log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "retry_exhausted_fallback", {
                    "oco_retry_count": oco_retry_count,
                    "max_oco_retry": max_oco_retry,
                    "current_price": prix_actuel,
                    "stop_price": stop_calc,
                })
                sell_raw = binance("order", "sell", f"{coin}USDC", str(qty), "--type", "market", "-o", "json", "--yes")
                sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
                sell_txid = sell_resp.get("txid", [None])[0]
                if sell_txid:
                    import time; time.sleep(1)
                    fill_raw = binance("query-orders", sell_txid, "-o", "json")
                    fill = json.loads(fill_raw).get(sell_txid, {})
                    fill_exit = float(fill.get("cost", 0)) / float(fill.get("vol_exec", qty)) if fill.get("vol_exec") else prix_actuel
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
                    log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "exhausted_fallback_success", {
                        "exit_price": fill_exit,
                        "pnl_usdc": pnl_usdc,
                        "pnl_pct": pnl_pct,
                    })
                    tg(f"🚨 {coin} : SL rattrapage échoué {max_oco_retry} fois. Fermeture SELL MARKET forcée.\n{pnl_usdc:+.2f} USDC ({pnl_pct:+.1f}%)")
                else:
                    log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "exhausted_fallback_failed", {
                        "reason": "market_order_failed",
                        "error": sell_raw[:200],
                    })
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

                sl_raw = binance("order", "sell", f"{coin}USDC", str(qty_adj), "--type", "stop-loss", "--price", str(stop_calc), "-o", "json", "--yes")
                sl_resp = json.loads(sl_raw) if sl_raw.strip() else {}
                new_sl_txid = sl_resp.get("txid", [None])[0]
                if new_sl_txid:
                    for item in history:
                        if item.get("trade_id") == t.get("trade_id"):
                            item.update({
                                "protection_failed": False,
                                "sl_order_txid": new_sl_txid,
                                "stop_price": stop_calc,
                                "oco_retry_count": 0,
                            })
                    log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "sl_retry_success", {
                        "retry_attempt": oco_retry_count + 1,
                        "max_retries": max_oco_retry,
                        "new_sl_txid": new_sl_txid,
                        "stop_price": stop_calc,
                    })
                    tg(f"🛡️ {coin} : SL de rattrapage placé (tentative {oco_retry_count + 1}) — SL {stop_calc:.4g}")
                else:
                    log_phase0_event(CYCLE_ID, "phase0_oco_retry", coin, "sl_retry_failed", {
                        "retry_attempt": oco_retry_count + 1,
                        "max_retries": max_oco_retry,
                        "reason": "sl_placement_failed",
                    })
                    tg(f"⚠️ {coin} : SL rattrapage échoué (tentative {oco_retry_count + 1}/{max_oco_retry})")

    _save_trade_history_atomic(history)
    retried = len(unprotected)
    print(f"PHASE0_OCO_DONE|retried={retried}")
    with open(f"/tmp/cycle_{CYCLE_ID}_phase0_oco_retry_output.json", "w") as f:
        json.dump({"retried": retried}, f)

except Exception as e:
    tg(f"⚠️ Erreur routine rattrapage protection_failed : {e}")
    print(f"PHASE0_OCO_ERROR|{e}")
    sys.exit(1)
