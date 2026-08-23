"""Exécution des ordres (drift check, entrée BUY, fill retry, TP/SL, pose stop-loss) — phase 5.

Lit les ordres préparés par la Phase 4 depuis /tmp/cycle_{CYCLE_ID}_phase5_input.json :
{
  "ordres_prepares": [{coin, quantite, prix_entry, prix_stop, prix_tp,
                       montant_ordre, risk_usdc, stop_distance_pct, score}],
  "config": {...}
}

Pour chaque ordre, dans l'ordre de score décroissant :
1. Re-fetch prix, skip TYPE_C si drift > price_deviation_max_pct
2. Re-fetch solde USDC, skip TYPE_C si insuffisant
3. Si maker_entry_enabled (config, défaut True) : pose un ordre LIMIT post-only au bid (#388) et
   l'enregistre dans state/maker_pending_orders.json — le core/maker_watcher.py prend le relais
   (ajustement via amend, repli au marché, pose du SL au fill). Sinon (ou si la pose échoue après
   3 tentatives) : BUY MARKET puis query du fill (3 tentatives, 1s d'intervalle), skip TYPE_C si
   non rempli.
4. Recalcule TP/SL sur actual_entry ; clôture immédiate au marché si prix post-fill >= actual_tp
5. Récupère lot_decimals/tick_size pour arrondir la quantité et le prix de l'ordre SL
6. Pose l'ordre SELL STOP-LOSS ; protection_failed=True + alerte Telegram si échec

Exécuté par Claude en Phase 5 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase5_execution.py __CYCLE_ID__

Stdout : PHASE5_DONE|executed=N|pending=P|skipped=M
(executed = ordres réellement remplis ce cycle ; pending = ordres LIMIT maker posés, en attente
de remplissage par core/maker_watcher.py — pas encore des achats, cf. #397)
Output : /tmp/cycle_{CYCLE_ID}_phase5_output.json
"""
import sys
import os
import json
import math
import time
import uuid
import datetime
import tempfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import (  # noqa: E402
    tg, binance, _load_config, _save_trade_history_atomic, compute_net_pnl,
    maker_or_taker_from_ordertype, load_maker_pending_orders, save_maker_pending_orders,
)

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

# Chemin fixe volontaire (contrat avec prompts/phases/phase5_execution.txt) : neutralisation
# bandit temporaire, à lever avec le déplacement /tmp -> state/ (#392, #403)
in_path = f"/tmp/cycle_{CYCLE_ID}_phase5_input.json"  # nosec B108
with open(in_path) as f:
    inp = json.load(f)

ordres_prepares = inp.get("ordres_prepares", [])
cfg = inp.get("config") or _load_config()

price_deviation_max_pct = cfg.get("price_deviation_max_pct", 0.02)
reward_risk_ratio = cfg.get("reward_risk_ratio", 2)
maker_entry_enabled = cfg.get("maker_entry_enabled", True)

with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
    history = json.load(f)


def _place_maker_entry_order(pair, quantite, _retries=3):
    """Pose un BUY LIMIT post-only au bid courant (#388). Retry si Kraken rejette (bid a bougé
    entre lecture et envoi). Retourne (txid, limit_price) ou (None, None) si épuisé."""
    for attempt in range(_retries):
        ticker_raw = binance("ticker", pair, "-o", "json")
        bid = float(json.loads(ticker_raw).get(pair, {}).get("b", [0])[0])
        buy_raw = binance("order", "buy", pair, str(quantite), "--type", "limit",
                           "--price", str(bid), "--oflags", "post", "-o", "json", "--yes")
        buy_resp = json.loads(buy_raw) if buy_raw.strip() else {}
        txid = (buy_resp.get("txid") or [None])[0]
        if txid:
            return txid, bid
        if attempt < _retries - 1:
            time.sleep(1)
    return None, None


orders_executed = []
orders_skipped_detail = {}
maker_pending_orders = load_maker_pending_orders(PROJECT_DIR)

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

        # 3. Entrée maker (#388) : ordre LIMIT post-only au bid, suivi async par maker_watcher.py
        if maker_entry_enabled:
            maker_txid, maker_limit_price = _place_maker_entry_order(f"{coin}USDC", quantite)
            if maker_txid:
                maker_pending_orders.append({
                    "coin": coin,
                    "pair": f"{coin}USDC",
                    "txid": maker_txid,
                    "quantity": quantite,
                    "montant_ordre": montant_ordre,
                    "risk_usdc": risk_usdc,
                    "stop_distance_pct": stop_distance_pct,
                    "reward_risk_ratio": reward_risk_ratio,
                    "score": score,
                    "scan_price": prix_entry,
                    "initial_limit_price": maker_limit_price,
                    "current_limit_price": maker_limit_price,
                    "adjustments": 0,
                    "placed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "cycle_id": CYCLE_ID,
                })
                save_maker_pending_orders(maker_pending_orders, PROJECT_DIR)
                tg(
                    f"🧊 LIMIT post-only {coin}\n{quantite} @ {maker_limit_price:.4g} USDC (bid)\n"
                    f"Suivi par le maker watcher (concession max {cfg.get('maker_max_concession_pct', 0.003) * 100:.2f}%)"
                )
                orders_executed.append({
                    "coin": coin, "entry_order_id": maker_txid, "maker_limit_price": maker_limit_price,
                    "maker_pending": True,
                })
                continue
            # Pose post-only impossible après retries (bid instable) -> repli BUY MARKET immédiat

        # BUY MARKET + query du fill (3 tentatives, 1s entre chaque)
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
        entry_fee_usdc = float(fill.get("fee", 0) or 0)
        # Dérivé depuis descr.ordertype de la réponse Kraken plutôt qu'une constante figée. Ce
        # chemin (maker_entry_enabled=False, ou repli après échec de pose du LIMIT post-only) est
        # toujours un market -> "taker" ; le fill maker (LIMIT post-only) est classé côté
        # core/maker_watcher.py (#388), seul endroit qui connaît le post_only.
        maker_or_taker = maker_or_taker_from_ordertype(fill.get("descr", {}).get("ordertype", "market"))

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
            exit_fee_usdc = float(exit_fill.get("fee", 0) or 0)
            net = compute_net_pnl(actual_entry, avg_exit, actual_qty, entry_fee_usdc, exit_fee_usdc)

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
                "entry_fee_usdc": entry_fee_usdc,
                "exit_fee_usdc": exit_fee_usdc,
                "fees_usdc": net["fees_usdc"],
                "maker_or_taker": maker_or_taker,
                "pnl_gross_usdc": net["pnl_gross_usdc"],
                "pnl_usdc": net["pnl_usdc"],
                "pnl_gross_pct": net["pnl_gross_pct"],
                "pnl_pct": net["pnl_pct"],
                "close_reason": "market_above_tp_at_fill",
            })
            _save_trade_history_atomic(history)

            pnl_usdc = net["pnl_usdc"]
            tg(f"⚡ {coin} : TP dépassé au fill, fermé à market → {pnl_usdc:+.2f} USDC")
            orders_executed.append({
                "coin": coin, "actual_entry": actual_entry, "actual_qty": actual_qty,
                "entry_order_id": entry_order_id, "closed_at_fill": True,
            })
            continue

        # 5. Filtres marché (lot_decimals, tick_size) pour l'ordre SL
        pairs_raw = binance("pairs", "--pair", f"{coin}USDC", "-o", "json")
        pair_data = json.loads(pairs_raw).get(f"{coin}USDC", {})
        lot_dec = int(pair_data.get("lot_decimals", 8))
        step = 10 ** (-lot_dec)
        actual_qty_sl = round(math.floor(actual_qty / step) * step, lot_dec)
        tick = float(pair_data.get("tick_size", "0.00000001"))
        actual_stop = round(round(actual_stop / tick) * tick, 8)

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
            "entry_fee_usdc": entry_fee_usdc,
            "exit_fee_usdc": None,
            "fees_usdc": None,
            "maker_or_taker": maker_or_taker,
            "pnl_gross_usdc": None,
            "pnl_usdc": None,
            "pnl_gross_pct": None,
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

# Un ordre maker_pending (#388) est POSÉ, pas exécuté : aucun achat n'a eu lieu tant que
# maker_watcher.py ne l'a pas rempli (et il peut ne jamais l'être, si le signal s'invalide et
# que l'ordre est abandonné). Le compter dans executed mentirait à tout l'aval (cycle_log.jsonl,
# Mongo, rapports, Telegram) sur ce qui a réellement été acheté ce cycle.
pending_maker = [o for o in orders_executed if o.get("maker_pending")]
filled_orders = [o for o in orders_executed if not o.get("maker_pending")]
executed = len(filled_orders)
pending = len(pending_maker)
skipped = len(orders_skipped_detail)

tg(
    f"📊 Phase 5 résumé\nExécutés : {executed}\nEn attente (maker) : {pending}\n"
    f"Skippés : {skipped}\nDétails : {orders_skipped_detail}"
)

out = {
    "executed": executed,
    "pending": pending,
    "skipped": skipped,
    "orders_executed": orders_executed,
    "orders_skipped_detail": orders_skipped_detail,
}
# Écriture atomique : le contenu final atterrit bien sur le chemin fixe
# /tmp/cycle_{CYCLE_ID}_phase5_output.json attendu par le prompt (phase5_execution.txt) et donc
# par les phases 6-8 — seule l'écriture transite par un fichier temporaire non-prévisible.
# Chemin fixe volontaire (contrat prompt) : neutralisation bandit temporaire, à lever avec le
# déplacement /tmp -> state/ (#392, #403)
out_path = f"/tmp/cycle_{CYCLE_ID}_phase5_output.json"  # nosec B108
fd, tmp_out_path = tempfile.mkstemp(prefix=f"cycle_{CYCLE_ID}_phase5_output_", suffix=".json")
with os.fdopen(fd, "w") as f:
    json.dump(out, f)
os.replace(tmp_out_path, out_path)

print(f"PHASE5_DONE|executed={executed}|pending={pending}|skipped={skipped}")
