"""Thread daemon : surveillance take profit temps réel (toutes les 2 min)."""
import json
import os
import time
from datetime import datetime, timezone

from loguru import logger

from core.env import PROJECT_DIR
from core.lock import acquire_lock, is_locked, release_lock
from core.state_manager import load_trade_history, save_trade_history
from core.telegram import send_telegram
from core.trade_helpers import binance as _cli

_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "tp_watcher_state.json")


def _write_watcher_state(status: str, last_error: str | None, positions_checked: int, total_ticks: int, total_sales: int) -> None:
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


def tp_watcher_loop():
    time.sleep(30)  # laisser le bot démarrer
    while True:
        try:
            _tp_watcher_tick()
        except Exception as e:
            logger.error(f"[TP Watcher] Erreur inattendue : {e}")
        time.sleep(120)


def _tp_watcher_tick():
    if is_locked():
        return

    try:
        with open(_WATCHER_STATE_PATH) as f:
            _prev = json.load(f)
        total_ticks = _prev.get("total_ticks", 0) + 1
        total_sales = _prev.get("total_sales", 0)
    except Exception:
        total_ticks = 1
        total_sales = 0

    history = load_trade_history()
    changed = False
    tick_status = "ok"
    tick_last_error = None
    positions_checked = 0

    for pos in history:
        if pos.get("status") != "open":
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
            continue

        # Re-vérifier le lock avant d'acquérir — un cycle 4h peut démarrer entre deux positions
        if is_locked():
            break

        logger.info(f"[TP Watcher] {coin} TP atteint : {current_price:.4f} >= {float(tp_price):.4f}")
        acquire_lock()
        try:
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
                except Exception as e:
                    logger.debug(f"[TP Watcher] Fill query {sell_txid} indisponible, exit_price = current_price : {e}")

            pnl_usdc = (exit_price - entry_price) * qty
            pnl_pct = (exit_price - entry_price) / entry_price * 100

            pos.update({
                "status": "closed",
                "exit_price": exit_price,
                "pnl_usdc": pnl_usdc,
                "pnl_pct": pnl_pct,
                "close_reason": "tp_watcher",
                "exit_date": datetime.now(timezone.utc).isoformat() + "Z",
            })
            changed = True
            total_sales += 1
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

    _write_watcher_state(tick_status, tick_last_error, positions_checked, total_ticks, total_sales)
