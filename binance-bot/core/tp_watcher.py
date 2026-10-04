"""Thread daemon : surveillance take profit temps réel (toutes les 2 min)."""
import json
import os
import time
from datetime import datetime, timezone

from loguru import logger

from core.dashboard_state import publish_trade_history_slices
from core.env import PROJECT_DIR
from core.lock import acquire_lock, is_locked, release_lock
from core.maker_exit_watcher import (
    _place_stop_loss,
    attempt_maker_exit,
    load_maker_exit_pending_orders,
    save_maker_exit_pending_orders,
)
from core.state_manager import load_trade_history, save_trade_history
from core.telegram import send_telegram
from core.trade_helpers import binance as _cli, _load_config, compute_net_pnl, initial_stop_price

_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "tp_watcher_state.json")


def _write_watcher_state(status: str, last_error: str | None, positions_checked: int, sales_delta: int = 0) -> None:
    try:
        with open(_WATCHER_STATE_PATH) as f:
            prev = json.load(f)
        total_ticks = prev.get("total_ticks", 0) + 1
        total_sales = prev.get("total_sales", 0) + sales_delta
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        total_ticks = 1
        total_sales = sales_delta
    state = {
        "last_tick": datetime.now(timezone.utc).isoformat() + "Z",
        "status": status,
        "last_error": last_error,
        "positions_checked": positions_checked,
        "total_ticks": total_ticks,
        "total_sales": total_sales,
    }
    tmp = _WATCHER_STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, _WATCHER_STATE_PATH)


def _place_sl_safe(pair: str, qty: float, price: float):
    """_place_stop_loss() ne capte pas le RuntimeError de binance() : ici toute erreur = échec de pose."""
    try:
        return _place_stop_loss(pair, qty, price)
    except Exception as e:
        return None, True, f" {e}", price


def _apply_breakeven(pos: dict, current_price: float, cfg: dict) -> bool:
    """Remonte le stop au break-even dès que le trade est en gain (#513). Retourne True si
    trade_history doit être sauvegardé. À appeler hors lock : prend le lock le temps de
    l'annulation/replacement. Jamais de position laissée sans stop : si le nouveau stop échoue,
    on repose l'ancien, et à défaut protection_failed=True laisse le rattrapage Phase 0 agir."""
    if not cfg.get("breakeven_enabled", True) or pos.get("breakeven_applied"):
        return False
    old_txid = pos.get("sl_order_txid")
    entry = float(pos.get("entry_price", 0) or 0)
    if not old_txid or pos.get("protection_failed") or entry <= 0:
        return False
    include_fees = cfg.get("breakeven_include_fees", True)
    level = entry * (1 + (cfg.get("fee_round_trip_pct", 0.009) if include_fees else 0.0))
    trigger = entry * (1 + cfg.get("breakeven_trigger_pct", 0.015))
    old_stop = float(pos.get("stop_price") or 0)
    if current_price < trigger or old_stop >= level or level >= current_price:
        return False
    # Un cycle 4h peut démarrer entre deux positions
    if is_locked():
        return False

    coin = pos["coin"]
    pair = f"{coin}USDC"
    qty = float(pos["quantity"])
    acquire_lock()
    try:
        try:
            _cli("order", "cancel", old_txid, "-o", "json", "--yes")
        except Exception as e:
            logger.warning(f"[TP Watcher] Break-even {coin} : annulation SL {old_txid} impossible, abandon : {e}")
            return False

        pos.setdefault("initial_stop_price", initial_stop_price(pos, cfg.get("fee_round_trip_pct", 0.009)))
        new_txid, failed, err_msg, level_rounded = _place_sl_safe(pair, qty, level)
        if not failed:
            pos.update({"stop_price": level_rounded, "sl_order_txid": new_txid, "breakeven_applied": True})
            send_telegram(
                f"🔒 {coin} : le stop est remonté au prix d'achat"
                f"{' (frais compris)' if include_fees else ''}, "
                f"ce trade ne peut plus perdre{'' if include_fees else ' (hors frais)'}"
            )
            logger.info(f"[TP Watcher] {coin} break-even : stop {old_stop:.4f} -> {level_rounded:.4f}")
            return True

        logger.error(f"[TP Watcher] Break-even {coin} : nouveau stop échoué{err_msg}, repose de l'ancien")
        restored_txid, restore_failed, _, _ = _place_sl_safe(pair, qty, old_stop)
        if not restore_failed:
            pos["sl_order_txid"] = restored_txid
            send_telegram(f"⚠️ {coin} : remontée du stop au prix d'achat échouée, ancien stop reposé")
        else:
            pos["sl_order_txid"] = None
            pos["protection_failed"] = True
            send_telegram(f"🚨 {coin} : position NON protégée — remontée du stop échouée et ancien stop non reposé !{err_msg}")
        return True
    finally:
        release_lock()


def tp_watcher_loop():
    time.sleep(30)  # laisser le bot démarrer
    while True:
        try:
            _tp_watcher_tick()
        except Exception as e:
            logger.exception(f"[TP Watcher] Erreur inattendue : {type(e).__name__}: {e}")
        time.sleep(120)


def _tp_watcher_tick():
    if is_locked():
        return

    cfg = _load_config()
    maker_exit_enabled = cfg.get("maker_exit_enabled", True)
    exit_pending = load_maker_exit_pending_orders() if maker_exit_enabled else []
    exit_pending_ids = {p["trade_id"] for p in exit_pending}

    history = load_trade_history()
    changed = False
    tick_status = "ok"
    tick_last_error = None
    positions_checked = 0
    sales_delta = 0

    for pos in history:
        if pos.get("status") != "open":
            continue
        # Sortie maker déjà en cours de chasse (#390) -> ne pas redéclencher tant qu'elle n'est
        # pas résolue par core/maker_exit_watcher.py.
        if pos.get("trade_id") in exit_pending_ids:
            continue
        coin = pos.get("coin")
        tp_price = pos.get("tp_price")
        qty = float(pos.get("quantity", 0))
        if not tp_price or not coin or not qty:
            continue

        positions_checked += 1

        try:
            ticker_raw = _cli("ticker", f"{coin}USDC", "-o", "json")
            ticker_data = json.loads(ticker_raw)
            current_price = float(ticker_data.get(f"{coin}USDC", {}).get("c", [0])[0])
        except Exception as e:
            logger.warning(f"[TP Watcher] Ticker {coin} indisponible : {e}")
            tick_status = "warning"
            tick_last_error = f"Ticker {coin} indisponible : {e}"
            continue

        if current_price < float(tp_price):
            try:
                if _apply_breakeven(pos, current_price, cfg):
                    changed = True
                    save_trade_history(history)  # l'ancien txid est annulé : ne pas attendre la fin du tick
            except Exception as e:
                logger.error(f"[TP Watcher] Erreur break-even {coin} : {e}")
                tick_status = "error"
                tick_last_error = f"Erreur break-even {coin} : {e}"
            continue

        # Re-vérifier le lock avant d'acquérir — un cycle 4h peut démarrer entre deux positions
        if is_locked():
            break

        logger.info(f"[TP Watcher] {coin} TP atteint : {current_price:.4f} >= {float(tp_price):.4f}")
        acquire_lock()
        try:
            if maker_exit_enabled:
                new_pending = attempt_maker_exit(pos, "tp_watcher", cfg, cycle_id=None)
                changed = True
                if new_pending:
                    exit_pending.append(new_pending)
                    save_maker_exit_pending_orders(exit_pending)
                continue

            entry_price = float(pos.get("entry_price", 0))
            sl_txid = pos.get("sl_order_txid")

            if sl_txid:
                try:
                    _cli("order", "cancel", sl_txid, "-o", "json", "--yes")
                except Exception as e:
                    logger.warning(f"[TP Watcher] Cancel SL {sl_txid} : {e}")

            sell_raw = _cli("order", "sell", f"{coin}USDC", str(qty), "--type", "market", "-o", "json", "--yes")
            sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
            sell_txid = (sell_resp.get("txid") or [None])[0]

            exit_price = current_price
            exit_fee_usdc = 0.0
            if sell_txid:
                time.sleep(1)
                try:
                    fill_raw = _cli("query-orders", sell_txid, "-o", "json")
                    fill_data = json.loads(fill_raw) if fill_raw.strip() else {}
                    fill = fill_data.get(sell_txid, {})
                    vol_exec = float(fill.get("vol_exec", qty))
                    cost = float(fill.get("cost", current_price * qty))
                    if vol_exec > 0:
                        exit_price = cost / vol_exec
                    exit_fee_usdc = float(fill.get("fee", 0) or 0)
                except Exception as e:
                    logger.debug(f"[TP Watcher] Fill query {sell_txid} indisponible, exit_price = current_price : {e}")

            entry_fee_usdc = float(pos.get("entry_fee_usdc", 0) or 0)
            net = compute_net_pnl(entry_price, exit_price, qty, entry_fee_usdc, exit_fee_usdc)
            pnl_usdc = net["pnl_usdc"]
            pnl_pct = net["pnl_pct"]

            pos.update({
                "status": "closed",
                "exit_price": exit_price,
                "entry_fee_usdc": entry_fee_usdc,
                "exit_fee_usdc": exit_fee_usdc,
                "fees_usdc": net["fees_usdc"],
                "pnl_gross_usdc": net["pnl_gross_usdc"],
                "pnl_usdc": pnl_usdc,
                "pnl_gross_pct": net["pnl_gross_pct"],
                "pnl_pct": pnl_pct,
                "close_reason": "tp_watcher",
                "cycle_id": None,
                "exit_date": datetime.now(timezone.utc).isoformat() + "Z",
            })
            changed = True
            sales_delta += 1
            send_telegram(
                f"TP atteint — {coin} vendu à {exit_price:.4f} USDC\n"
                f"{pnl_pct:+.1f}% | {pnl_usdc:+.2f} USDC"
            )
            logger.info(f"[TP Watcher] {coin} vendu : exit={exit_price:.4f}, PnL={pnl_pct:+.1f}%")
        except Exception as e:
            logger.error(f"[TP Watcher] Erreur vente {coin} : {e}")
            send_telegram(f"TP Watcher — erreur vente {coin} : {e}")
            tick_status = "error"
            tick_last_error = f"Erreur vente {coin} : {e}"
        finally:
            release_lock()

    if changed:
        save_trade_history(history)
        publish_trade_history_slices(history, "TP Watcher")  # #500 : sans attendre la Phase 7

    _write_watcher_state(tick_status, tick_last_error, positions_checked, sales_delta)
