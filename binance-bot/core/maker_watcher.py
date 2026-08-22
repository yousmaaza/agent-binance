"""Thread daemon : watcher des ordres limite maker d'entrée (#388).

Ajuste chaque ordre LIMIT post-only posé par phase5_execution.py via `order amend` (jamais
annuler/replacer, pour préserver la priorité dans le carnet) jusqu'à exécution ou repli. Patron :
core/tp_watcher.py — lock 2h existant, écriture atomique d'un fichier d'état.

Arbre de décision par tick, pour chaque ordre dans state/maker_pending_orders.json :
1. Rempli (status "closed") -> enregistre la position (maker_or_taker="maker"), pose le SL.
2. Terminé de façon inattendue (canceled/expired hors de notre fait) -> enregistre le
   remplissage partiel éventuel, sinon abandonne (pas de repli marché, cas trop ambigu).
3. Sinon, prix invalidé (price_deviation_max_pct vs scan_price) -> annule ; remplissage partiel
   éventuel enregistré, sinon abandon (skip), PAS de repli marché (thèse du trade morte).
4. Sinon, budget de concession épuisé (maker_max_concession_pct) OU timeout
   (maker_timeout_seconds) -> annule ; remplissage partiel éventuel enregistré, sinon repli
   BUY MARKET (comportement actuel).
5. Sinon, le bid a bougé -> amend au nouveau bid (post-only), concession cumulée = distance au
   prix de pose initial.
6. Sinon : rien à faire jusqu'au tick suivant.
"""
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone

from loguru import logger

from core.env import PROJECT_DIR
from core.lock import acquire_lock, is_locked, release_lock
from core.state_manager import load_trade_history, save_trade_history
from core.telegram import send_telegram
from core.trade_helpers import (
    binance as _cli,
    _load_config,
    load_maker_pending_orders,
    maker_or_taker_from_ordertype,
    save_maker_pending_orders,
)

_MAKER_FILL_LABEL: str = maker_or_taker_from_ordertype("limit", post_only=True)  # "maker" (#388)

_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "maker_watcher_state.json")


def _write_watcher_state(status: str, last_error: str | None, orders_checked: int,
                          fills_delta: int = 0, fallbacks_delta: int = 0) -> None:
    try:
        with open(_WATCHER_STATE_PATH) as f:
            prev = json.load(f)
        total_ticks = prev.get("total_ticks", 0) + 1
        total_fills = prev.get("total_fills", 0) + fills_delta
        total_fallbacks = prev.get("total_fallbacks", 0) + fallbacks_delta
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        total_ticks = 1
        total_fills = fills_delta
        total_fallbacks = fallbacks_delta
    state = {
        "last_tick": datetime.now(timezone.utc).isoformat() + "Z",
        "status": status,
        "last_error": last_error,
        "orders_checked": orders_checked,
        "total_ticks": total_ticks,
        "total_fills": total_fills,
        "total_fallbacks": total_fallbacks,
    }
    tmp = _WATCHER_STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, _WATCHER_STATE_PATH)


def _round_price(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 8)


def _round_qty(qty: float, step: float, lot_dec: int) -> float:
    return round(math.floor(qty / step) * step, lot_dec)


def maker_watcher_loop():
    time.sleep(30)  # laisser le bot démarrer
    while True:
        cfg = _load_config()
        tick_seconds = cfg.get("maker_tick_seconds", 20)
        try:
            _maker_watcher_tick(cfg)
        except Exception as e:
            logger.error(f"[Maker Watcher] Erreur inattendue : {e}")
        time.sleep(tick_seconds)


def _place_stop_loss(pair: str, qty: float, stop_price: float):
    """Arrondit qty/prix au pas de la paire et pose le SL (#379).

    Retourne (sl_txid, protection_failed, err_msg, stop_price_rounded).
    """
    try:
        pairs_raw = _cli("pairs", "--pair", pair, "-o", "json")
        pair_data = json.loads(pairs_raw).get(pair, {})
        lot_dec = int(pair_data.get("lot_decimals", 8))
        step = 10 ** (-lot_dec)
        qty_sl = _round_qty(qty, step, lot_dec)
        tick = float(pair_data.get("tick_size", "0.00000001"))
        stop_price_rounded = _round_price(stop_price, tick)
        sl_raw = _cli("order", "sell", pair, str(qty_sl), "--type", "stop-loss",
                       "--price", str(stop_price_rounded), "-o", "json", "--yes")
        sl_txid = json.loads(sl_raw).get("txid", [None])[0]
        if not sl_txid:
            return None, True, "", stop_price_rounded
        return sl_txid, False, "", stop_price_rounded
    except Exception as e:
        return None, True, f" {e}", stop_price


def _register_open_position(pending: dict, entry_txid: str, actual_qty: float, actual_entry: float,
                             entry_fee_usdc: float, maker_or_taker: str, history: list) -> None:
    coin = pending["coin"]
    pair = pending["pair"]
    reward_risk_ratio = pending.get("reward_risk_ratio", 2)
    stop_distance_pct = pending["stop_distance_pct"]
    actual_stop = actual_entry * (1 - stop_distance_pct)
    actual_tp = actual_entry * (1 + stop_distance_pct * reward_risk_ratio)

    sl_txid, protection_failed, sl_err_msg, actual_stop_rounded = _place_stop_loss(pair, actual_qty, actual_stop)
    if protection_failed:
        send_telegram(f"⚠️ {coin} : entrée maker OK mais SL échoué — position NON protégée !{sl_err_msg}")

    trade_id = str(uuid.uuid4())[:8]
    now_iso = datetime.now(timezone.utc).isoformat()
    history.append({
        "trade_id": trade_id,
        "date": now_iso,
        "coin": coin,
        "side": "BUY",
        "signal_score": pending.get("score", 0),
        "entry_price": actual_entry,
        "stop_price": actual_stop_rounded,
        "tp_price": actual_tp,
        "quantity": actual_qty,
        "risk_usdc": pending.get("risk_usdc"),
        "entry_order_id": entry_txid,
        "sl_order_txid": sl_txid,
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
    label = "maker" if maker_or_taker == _MAKER_FILL_LABEL else "repli marché"
    send_telegram(
        f"🧊✅ Entrée {label} {coin}\n{actual_qty} @ {actual_entry:.4g} USDC\n"
        f"🛑 Stop : {actual_stop_rounded:.4g}\n🎯 TP cible : {actual_tp:.4g}\nScore : {pending.get('score', 0)}/10"
    )


def _fallback_market_buy(pending: dict, history: list) -> None:
    """Repli BUY MARKET pour la quantité totale (atteint uniquement si vol_exec==0 au moment
    du repli — comportement identique à l'ancien flux BUY MARKET de phase5_execution.py)."""
    coin = pending["coin"]
    pair = pending["pair"]
    qty = pending["quantity"]
    try:
        buy_raw = _cli("order", "buy", pair, str(qty), "--type", "market", "-o", "json", "--yes")
        entry_txid = json.loads(buy_raw)["txid"][0]
    except Exception as e:
        send_telegram(f"⚠️ {coin} : repli BUY MARKET échoué — {e}")
        return

    fill = {}
    for attempt in range(3):
        try:
            query_raw = _cli("query-orders", entry_txid, "-o", "json")
            fill = json.loads(query_raw).get(entry_txid, {})
        except Exception:
            fill = {}
        if fill.get("status") == "closed":
            break
        if attempt < 2:
            time.sleep(1)

    if fill.get("status") != "closed":
        send_telegram(f"⚠️ {coin} : repli BUY MARKET non rempli (status: {fill.get('status')})")
        return

    actual_qty = float(fill["vol_exec"])
    actual_entry = float(fill["cost"]) / actual_qty
    entry_fee_usdc = float(fill.get("fee", 0) or 0)
    _register_open_position(pending, entry_txid, actual_qty, actual_entry, entry_fee_usdc, "taker", history)


def _cancel_and_resolve(pending: dict, allow_market_fallback: bool, history: list) -> str:
    """Annule l'ordre limite puis résout le remplissage partiel éventuel. Retourne l'issue :
    "filled_partial", "market_fallback" ou "abandoned"."""
    coin = pending["coin"]
    txid = pending["txid"]
    try:
        _cli("order", "cancel", txid, "-o", "json", "--yes")
    except Exception as e:
        logger.warning(f"[Maker Watcher] Cancel {txid} ({coin}) : {e}")
    time.sleep(1)
    return _resolve_after_cancel(pending, allow_market_fallback, history)


def _resolve_after_cancel(pending: dict, allow_market_fallback: bool, history: list) -> str:
    coin = pending["coin"]
    txid = pending["txid"]
    try:
        query_raw = _cli("query-orders", txid, "-o", "json")
        fill = json.loads(query_raw).get(txid, {})
    except Exception as e:
        logger.warning(f"[Maker Watcher] Query post-cancel {txid} ({coin}) : {e}")
        fill = {}

    vol_exec = float(fill.get("vol_exec", 0) or 0)
    if vol_exec > 0:
        cost = float(fill.get("cost", 0) or 0)
        actual_entry = cost / vol_exec if cost else pending.get("current_limit_price", pending["initial_limit_price"])
        entry_fee_usdc = float(fill.get("fee", 0) or 0)
        _register_open_position(pending, txid, vol_exec, actual_entry, entry_fee_usdc, _MAKER_FILL_LABEL, history)
        return "filled_partial"

    if allow_market_fallback:
        _fallback_market_buy(pending, history)
        return "market_fallback"

    send_telegram(f"⏭️ {coin} : signal invalidé pendant la chasse maker — ordre annulé, pas d'achat")
    return "abandoned"


def _handle_closed_order(pending: dict, order_status: dict, history: list) -> tuple[bool, int, int]:
    coin = pending["coin"]
    txid = pending["txid"]
    acquire_lock()
    try:
        vol_exec = float(order_status.get("vol_exec", pending["quantity"]))
        cost = float(order_status.get("cost", 0) or 0)
        actual_entry = cost / vol_exec if vol_exec else pending["current_limit_price"]
        entry_fee_usdc = float(order_status.get("fee", 0) or 0)
        _register_open_position(pending, txid, vol_exec, actual_entry, entry_fee_usdc, _MAKER_FILL_LABEL, history)
        return True, 1, 0
    except Exception as e:
        logger.error(f"[Maker Watcher] Enregistrement fill {coin} : {e}")
        return False, 0, 0
    finally:
        release_lock()


def _handle_externally_canceled(pending: dict, status: str, history: list, tick_state: dict) -> tuple[bool, int, int]:
    coin = pending["coin"]
    acquire_lock()
    try:
        outcome = _resolve_after_cancel(pending, allow_market_fallback=False, history=history)
        if outcome == "filled_partial":
            return True, 1, 0
        return False, 0, 0
    except Exception as e:
        logger.error(f"[Maker Watcher] Résolution {status} {coin} : {e}")
        tick_state["status"] = "error"
        tick_state["last_error"] = f"Résolution {status} {coin} : {e}"
        return False, 0, 0
    finally:
        release_lock()


def _handle_invalidated_price(pending: dict, history: list, tick_state: dict) -> tuple[bool, int, int]:
    coin = pending["coin"]
    acquire_lock()
    try:
        outcome = _cancel_and_resolve(pending, allow_market_fallback=False, history=history)
        if outcome == "filled_partial":
            return True, 1, 0
        return False, 0, 0
    except Exception as e:
        logger.error(f"[Maker Watcher] Invalidation prix {coin} : {e}")
        tick_state["status"] = "error"
        tick_state["last_error"] = f"Invalidation prix {coin} : {e}"
        return False, 0, 0
    finally:
        release_lock()


def _handle_timeout_or_concession(pending: dict, history: list, tick_state: dict) -> tuple[bool, int, int]:
    coin = pending["coin"]
    acquire_lock()
    try:
        outcome = _cancel_and_resolve(pending, allow_market_fallback=True, history=history)
        if outcome in ("filled_partial", "market_fallback"):
            fallbacks = 1 if outcome == "market_fallback" else 0
            return True, 1, fallbacks
        return False, 0, 0
    except Exception as e:
        logger.error(f"[Maker Watcher] Repli marché {coin} : {e}")
        tick_state["status"] = "error"
        tick_state["last_error"] = f"Repli marché {coin} : {e}"
        return False, 0, 0
    finally:
        release_lock()


def _handle_amend_order(pending: dict, current_bid: float) -> None:
    coin = pending["coin"]
    txid = pending["txid"]
    try:
        amend_raw = _cli("order", "amend", "--txid", txid, "--limit-price", str(current_bid),
                          "--post-only", "-o", "json")
        amend_resp = json.loads(amend_raw) if amend_raw.strip() else {}
        if amend_resp.get("error"):
            logger.debug(f"[Maker Watcher] Amend {coin} rejeté ({amend_resp['error']}), réessai au tick suivant")
        else:
            pending["current_limit_price"] = current_bid
    except Exception as e:
        logger.debug(f"[Maker Watcher] Amend {coin} erreur, réessai au tick suivant : {e}")


def _maker_watcher_tick(cfg: dict) -> None:
    if is_locked():
        return

    pending_orders = load_maker_pending_orders(PROJECT_DIR)
    if not pending_orders:
        _write_watcher_state("ok", None, 0)
        return

    price_deviation_max_pct = cfg.get("price_deviation_max_pct", 0.02)
    maker_max_concession_pct = cfg.get("maker_max_concession_pct", 0.003)
    maker_timeout_seconds = cfg.get("maker_timeout_seconds", 3600)

    history = load_trade_history()
    history_changed = False
    remaining_pending = []
    orders_checked = 0
    fills_delta = 0
    fallbacks_delta = 0
    tick_state = {"status": "ok", "last_error": None}

    for pending in pending_orders:
        coin = pending["coin"]
        pair = pending["pair"]
        txid = pending["txid"]
        orders_checked += 1

        if is_locked():
            remaining_pending.append(pending)
            continue

        try:
            query_raw = _cli("query-orders", txid, "-o", "json")
            order_status = json.loads(query_raw).get(txid, {})
        except Exception as e:
            logger.warning(f"[Maker Watcher] query-orders {txid} ({coin}) : {e}")
            tick_state["status"] = "warning"
            tick_state["last_error"] = f"query-orders {coin} : {e}"
            remaining_pending.append(pending)
            continue

        status = order_status.get("status")

        if status == "closed":
            changed, fills, fallbacks = _handle_closed_order(pending, order_status, history)
            history_changed = history_changed or changed
            fills_delta += fills
            fallbacks_delta += fallbacks
            continue

        if status in ("canceled", "expired"):
            changed, fills, fallbacks = _handle_externally_canceled(pending, status, history, tick_state)
            history_changed = history_changed or changed
            fills_delta += fills
            fallbacks_delta += fallbacks
            continue

        # Ordre toujours vivant ("open") -> évaluation des bornes d'arrêt.
        try:
            ticker_raw = _cli("ticker", pair, "-o", "json")
            ticker_data = json.loads(ticker_raw).get(pair, {})
            current_bid = float(ticker_data.get("b", [0])[0])
            current_last = float(ticker_data.get("c", [0])[0])
        except Exception as e:
            logger.warning(f"[Maker Watcher] Ticker {coin} indisponible : {e}")
            tick_state["status"] = "warning"
            tick_state["last_error"] = f"Ticker {coin} indisponible : {e}"
            remaining_pending.append(pending)
            continue

        scan_price = pending["scan_price"]
        price_drift = abs(current_last - scan_price) / scan_price if scan_price else 0.0
        elapsed_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(pending["placed_at"])).total_seconds()
        initial_price = pending["initial_limit_price"]
        concession_pct = max(0.0, (current_bid - initial_price) / initial_price) if initial_price else 0.0

        if price_drift > price_deviation_max_pct:
            changed, fills, fallbacks = _handle_invalidated_price(pending, history, tick_state)
            history_changed = history_changed or changed
            fills_delta += fills
            fallbacks_delta += fallbacks
            continue

        if concession_pct >= maker_max_concession_pct or elapsed_seconds >= maker_timeout_seconds:
            changed, fills, fallbacks = _handle_timeout_or_concession(pending, history, tick_state)
            history_changed = history_changed or changed
            fills_delta += fills
            fallbacks_delta += fallbacks
            continue

        if current_bid and current_bid != pending.get("current_limit_price"):
            _handle_amend_order(pending, current_bid)

        remaining_pending.append(pending)

    # Toujours réécrit (peu coûteux vu le nombre d'ordres en attente, borné par
    # max_open_positions) : couvre à la fois les retraits et les amends de current_limit_price.
    save_maker_pending_orders(remaining_pending, PROJECT_DIR)

    if history_changed:
        save_trade_history(history)

    _write_watcher_state(tick_state["status"], tick_state["last_error"], orders_checked, fills_delta, fallbacks_delta)
