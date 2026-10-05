"""Thread daemon : watcher des ventes limite maker de sortie (#390).

Étend le patron de core/maker_watcher.py (#388) aux sorties discrétionnaires VERS LE HAUT
uniquement : TP watcher (tp_watcher.py) et objectif de profit (phase0_profit.py). Les stops, les
protections épuisées et les ventes sur signal retombé n'empruntent jamais ce chemin.

Contrainte de conception (vérifiée en prod, #390) : Kraken immobilise le solde dès la pose d'un
stop-loss (hold_trade == volume du stop ouvert) — impossible de laisser le stop en place pendant
qu'un ordre de vente limite chasse le marché. attempt_maker_exit() annule donc le stop AVANT de
poser la vente LIMIT post-only ; toute défaillance ultérieure (annulation de la limite, vente au
marché de repli) repose immédiatement un nouveau stop — une position ne doit jamais rester à la
fois non protégée et non vendue.

Contrairement à l'entrée, il n'existe pas de cas « abandon » : une sortie manquée doit toujours
finir vendue (au marché si nécessaire). Garde-fou spécifique aux sorties : à chaque tick, si le
prix courant redescend au niveau où était le stop, bascule immédiate au marché sans attendre le
budget de concession ni le délai.

Sortie PARTIELLE (#514) : même mécanisme, mais l'ordre porte `partial: True` et une fraction de la
position seulement (le stop a déjà été reposé sur le reliquat par tp_watcher.py). Ici, la
sortie manquée n'est PAS forcée au marché : la fraction est abandonnée et un stop est reposé sur la
quantité totale (_settle_partial). Un remplissage crée un enregistrement clôturé séparé
(close_reason "partial_tp", parent_trade_id) et réduit l'enregistrement d'origine.

Arbre de décision par tick, pour chaque ordre dans state/maker_exit_pending_orders.json :
1. Rempli (status "closed") -> position clôturée, exit_maker_or_taker="maker", pas de stop reposé.
2. Terminé de façon inattendue (canceled/expired hors de notre fait) -> remplissage partiel
   éventuel enregistré ; sinon reposer le stop immédiatement (jamais d'abandon côté sortie).
3. Sinon, prix redescendu au niveau du stop OU budget de concession épuisé OU délai dépassé ->
   annuler la limite (échec -> reposer le stop) ; remplissage partiel éventuel comptabilisé,
   reliquat vendu au marché (échec -> reposer le stop).
4. Sinon, l'ask a bougé -> amend au nouvel ask (post-only), concession cumulée = distance au prix
   de pose initial.
5. Sinon : rien à faire jusqu'au tick suivant.
"""
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone

from loguru import logger

from core.dashboard_state import publish_trade_history_slices
from core.env import PROJECT_DIR
from core.lock import acquire_lock, is_locked, release_lock
from core.state_manager import load_trade_history, save_trade_history
from core.telegram import send_telegram
from core.trade_helpers import (
    binance as _cli,
    _load_config,
    _save_json_atomic,
    compute_net_pnl,
    initial_stop_price,
    maker_or_taker_from_ordertype,
)

_MAKER_FILL_LABEL: str = maker_or_taker_from_ordertype("limit", post_only=True)  # "maker" (#390)
_QTY_EPSILON = 1e-9

_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "maker_exit_watcher_state.json")
_PENDING_ORDERS_PATH = os.path.join(PROJECT_DIR, "state", "maker_exit_pending_orders.json")


def load_maker_exit_pending_orders() -> list:
    """Charge state/maker_exit_pending_orders.json (#390). Retourne [] si absent/corrompu."""
    try:
        with open(_PENDING_ORDERS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_maker_exit_pending_orders(data: list) -> None:
    """Écriture atomique de state/maker_exit_pending_orders.json (#390)."""
    _save_json_atomic(data, _PENDING_ORDERS_PATH)


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


def _place_stop_loss(pair: str, qty: float, stop_price: float):
    """Arrondit qty/prix au pas de la paire et (re)pose le SL (patron #379/#388, adapté #390).

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
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError, KeyError) as e:
        return None, True, f" {e}", stop_price


def place_stop_loss_safe(pair: str, qty: float, price: float):
    """_place_stop_loss() ne capte pas le RuntimeError de binance() : ici toute erreur = échec de pose."""
    try:
        return _place_stop_loss(pair, qty, price)
    except Exception as e:
        return None, True, f" {e}", price


def restore_total_stop(pos: dict, reliquat_qty: float, notify=None) -> None:
    """Après abandon d'une sortie partielle (#514) : le stop couvre le reliquat seul, la fraction
    non vendue est nue. Annule le stop du reliquat et en repose un sur la quantité totale
    (pos["quantity"]) au niveau courant. Échec -> repose le stop du reliquat, à défaut
    protection_failed (rattrapage Phase 0), comme _apply_breakeven (#513). Si l'annulation échoue,
    le stop du reliquat reste en place (rien d'autre à faire côté Kraken : le solde est retenu)."""
    notify = notify or send_telegram
    coin = pos["coin"]
    pair = f"{coin}USDC"
    stop_price = float(pos.get("stop_price") or 0)
    total_qty = float(pos["quantity"])
    old_txid = pos.get("sl_order_txid")
    if old_txid:
        try:
            _cli("order", "cancel", old_txid, "-o", "json", "--yes")
        except Exception as e:
            notify(f"🚨 {coin} : stop sur le reliquat non annulé après abandon du partiel — "
                   f"une partie de la position n'est pas protégée, vérifier à la main ({e})")
            return
    new_txid, failed, err_msg, stop_rounded = place_stop_loss_safe(pair, total_qty, stop_price)
    if not failed:
        pos.update({"sl_order_txid": new_txid, "stop_price": stop_rounded, "protection_failed": False})
        return
    logger.error(f"[Maker Exit Watcher] Partiel {coin} : stop sur la quantité totale échoué{err_msg}, repose du stop du reliquat")
    restored_txid, restore_failed, _, _ = place_stop_loss_safe(pair, reliquat_qty, stop_price)
    if not restore_failed:
        pos["sl_order_txid"] = restored_txid
        notify(f"⚠️ {coin} : stop sur toute la position échoué, stop reposé sur le reliquat seul")
    else:
        pos["sl_order_txid"] = None
        pos["protection_failed"] = True
        notify(f"🚨 {coin} : position NON protégée — stops échoués après abandon du partiel !{err_msg}")


def attempt_partial_maker_exit(pos: dict, fraction_qty: float, reliquat_qty: float, cfg: dict,
                               notify=None) -> dict | None:
    """Pose la vente LIMIT post-only de la fraction (#514). Contrairement à attempt_maker_exit,
    ne touche pas au stop : l'appelant (tp_watcher) l'a déjà reposé sur le reliquat. Retourne
    l'enregistrement pour state/maker_exit_pending_orders.json, ou None si la pose échoue
    (l'appelant restaure alors un stop sur la quantité totale)."""
    notify = notify or send_telegram
    coin = pos["coin"]
    pair = f"{coin}USDC"
    try:
        ticker_raw = _cli("ticker", pair, "-o", "json")
        ask = float(json.loads(ticker_raw).get(pair, {}).get("a", [0])[0])
        sell_raw = _cli("order", "sell", pair, str(fraction_qty), "--type", "limit", "--price", str(ask),
                         "--oflags", "post", "-o", "json", "--yes")
        sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
        txid = (sell_resp.get("txid") or [None])[0]
        if not txid:
            raise RuntimeError("pas de txid")
    except Exception as e:
        logger.warning(f"[Maker Exit Watcher] Partiel {coin} : pose de la limite échouée : {e}")
        return None
    notify(f"🧊 LIMIT SELL post-only {coin} (profit partiel)\n{fraction_qty} @ {ask:.4g} USDC (ask)")
    return {
        "trade_id": pos["trade_id"],
        "coin": coin,
        "pair": pair,
        "txid": txid,
        "quantity": fraction_qty,
        "reliquat_qty": reliquat_qty,
        "partial": True,
        "stop_price": pos.get("stop_price"),
        "close_reason": "partial_tp",
        "initial_limit_price": ask,
        "current_limit_price": ask,
        "adjustments": 0,
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": None,
    }


def attempt_maker_exit(pos: dict, close_reason: str, cfg: dict, notify=None, cycle_id: str | None = None,
                       quantity: float | None = None) -> dict | None:
    """Enchaînement imposé (#390) : annule le stop, pose une vente LIMIT post-only au meilleur
    vendeur (ask courant). Retourne l'enregistrement à ajouter à
    state/maker_exit_pending_orders.json — maker_exit_watcher_loop() prend le relais.

    Si l'annulation du stop ou la pose de la limite échoue, repose le stop immédiatement (jamais
    de position à la fois non protégée et non vendue) et retourne None : le déclencheur (TP
    watcher / Phase 0 / vente sur signal) réessaiera au prochain tick/cycle.

    quantity (défaut : toute la position) laisse l'appelant imposer un volume qu'il a déjà
    plafonné au solde réel et tronqué au pas de la paire — ce que fait la vente sur signal depuis
    l'incident XRP du 18/08 (#472), où la quantité brute de trade_history a produit deux
    EOrder:Insufficient funds. Un pos["sl_order_txid"] déjà purgé (stop annulé par l'appelant)
    évite ici une seconde annulation, que Kraken rejette.
    """
    notify = notify or send_telegram
    coin = pos["coin"]
    pair = f"{coin}USDC"
    qty = float(quantity if quantity is not None else pos.get("quantity", 0))
    sl_txid = pos.get("sl_order_txid")
    stop_price = pos.get("stop_price")

    if sl_txid:
        try:
            _cli("order", "cancel", sl_txid, "-o", "json", "--yes")
        except (subprocess.CalledProcessError, OSError) as e:
            notify(f"⚠️ {coin} : annulation SL échouée avant sortie maker — stop conservé, {e}")
            return None

    try:
        ticker_raw = _cli("ticker", pair, "-o", "json")
        ask = float(json.loads(ticker_raw).get(pair, {}).get("a", [0])[0])
        sell_raw = _cli("order", "sell", pair, str(qty), "--type", "limit", "--price", str(ask),
                         "--oflags", "post", "-o", "json", "--yes")
        sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
        txid = (sell_resp.get("txid") or [None])[0]
        if not txid:
            raise RuntimeError("pas de txid")
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError, RuntimeError) as e:
        new_sl_txid, protection_failed, err_msg, stop_price_rounded = _place_stop_loss(pair, qty, stop_price)
        if protection_failed:
            pos["protection_failed"] = True
            notify(f"🚨 {coin} : pose limite sortie maker échouée ET repose du stop échoué — position NON protégée !{err_msg}")
        else:
            pos["sl_order_txid"] = new_sl_txid
            pos["stop_price"] = stop_price_rounded
            pos["protection_failed"] = False
            notify(f"⚠️ {coin} : pose limite sortie maker échouée ({e}) — stop reposé à {stop_price_rounded:.4g}")
        return None

    notify(
        f"🧊 LIMIT SELL post-only {coin}\n{qty} @ {ask:.4g} USDC (ask)\n"
        f"Suivi par le watcher de sortie (délai max {cfg.get('maker_exit_timeout_seconds', 600)}s)"
    )
    return {
        "trade_id": pos["trade_id"],
        "coin": coin,
        "pair": pair,
        "txid": txid,
        "quantity": qty,
        "stop_price": stop_price,
        "close_reason": close_reason,
        "initial_limit_price": ask,
        "current_limit_price": ask,
        "adjustments": 0,
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
    }


def maker_exit_watcher_loop():
    time.sleep(30)  # laisser le bot démarrer
    while True:
        cfg = _load_config()
        tick_seconds = cfg.get("maker_tick_seconds", 20)
        try:
            _maker_exit_watcher_tick(cfg)
        except Exception as e:
            logger.exception(f"[Maker Exit Watcher] Erreur inattendue : {type(e).__name__}: {e}")
        time.sleep(tick_seconds)


def _find_position(history: list, trade_id: str) -> dict | None:
    return next((p for p in history if p.get("trade_id") == trade_id), None)


def _fraction_label(fraction: float) -> str:
    if abs(fraction - 1 / 3) < 0.02:
        return "un tiers"
    if abs(fraction - 0.5) < 0.02:
        return "la moitié"
    return f"{fraction * 100:.0f} %"


def _finalize_partial(history: list, pending: dict, exit_price: float, exit_fee_usdc: float, qty_sold: float) -> bool:
    """Comptabilité du profit partiel (#514) : enregistrement clôturé séparé pour la part vendue
    (frais d'entrée au prorata), enregistrement d'origine réduit dans la même proportion —
    quantity, risk_usdc (initial_stop_price reste exact : risk/(entry x qty) est invariant) et
    entry_fee_usdc — et marqué partial_tp_done."""
    pos = _find_position(history, pending["trade_id"])
    if pos is None:
        logger.error(f"[Maker Exit Watcher] trade_id {pending['trade_id']} introuvable dans l'historique")
        return False

    entry_price = float(pos.get("entry_price", 0))
    parent_qty = float(pos.get("quantity", 0))
    ratio = qty_sold / parent_qty if parent_qty else 0.0
    entry_fee_total = float(pos.get("entry_fee_usdc", 0) or 0)
    entry_fee_share = entry_fee_total * ratio
    net = compute_net_pnl(entry_price, exit_price, qty_sold, entry_fee_share, exit_fee_usdc)

    child = {k: v for k, v in pos.items()
             if k not in ("sl_order_txid", "protection_failed", "breakeven_applied", "partial_tp_done",
                           "partial_tp_skipped", "oco_retry_count", "maker_fill_seconds")}
    child.update({
        "trade_id": f"{pos['trade_id']}-partial",
        "parent_trade_id": pos["trade_id"],
        "status": "closed",
        "quantity": qty_sold,
        "risk_usdc": float(pos["risk_usdc"]) * ratio if pos.get("risk_usdc") is not None else None,
        "entry_fee_usdc": entry_fee_share,
        "exit_price": exit_price,
        "exit_fee_usdc": exit_fee_usdc,
        "fees_usdc": net["fees_usdc"],
        "pnl_gross_usdc": net["pnl_gross_usdc"],
        "pnl_usdc": net["pnl_usdc"],
        "pnl_gross_pct": net["pnl_gross_pct"],
        "pnl_pct": net["pnl_pct"],
        "close_reason": "partial_tp",
        "cycle_id": None,
        "exit_date": datetime.now(timezone.utc).isoformat() + "Z",
        "exit_maker_or_taker": _MAKER_FILL_LABEL,
    })
    pos.setdefault("initial_stop_price", initial_stop_price(pos))
    pos["quantity"] = round(parent_qty - qty_sold, 8)
    if pos.get("risk_usdc") is not None:
        pos["risk_usdc"] = float(pos["risk_usdc"]) * (1 - ratio)
    pos["entry_fee_usdc"] = entry_fee_total - entry_fee_share
    pos["partial_tp_done"] = True
    history.append(child)

    gain_pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0
    protected = float(pos.get("stop_price") or 0) >= entry_price
    send_telegram(
        f"💰 {pos.get('coin')} : {_fraction_label(ratio)} de la position vendu "
        f"à {gain_pct:+.1f} % ({net['pnl_usdc']:+.2f} USDC), le reste continue"
        f"{' avec un stop qui ne peut plus perdre' if protected else ''}"
    )
    return True


def _settle_partial(pending: dict, history: list, fill: dict) -> None:
    """La limite du partiel n'est plus vivante (annulée par nous ou hors de notre fait) : comptabilise
    ce qui a été rempli, puis abandonne le reste — jamais de vente au marché pour un partiel
    (#514) — et reprotège la quantité totale."""
    pos = _find_position(history, pending["trade_id"])
    if pos is None:
        logger.error(f"[Maker Exit Watcher] trade_id {pending['trade_id']} introuvable dans l'historique")
        return
    qty = float(pending["quantity"])
    vol_exec = min(float(fill.get("vol_exec", 0) or 0), qty)
    if vol_exec > _QTY_EPSILON:
        cost = float(fill.get("cost", 0) or 0)
        exit_price = cost / vol_exec if cost else pending["current_limit_price"]
        _finalize_partial(history, pending, exit_price, float(fill.get("fee", 0) or 0), vol_exec)
    if vol_exec >= qty - _QTY_EPSILON:
        return
    send_telegram(f"ℹ️ {pos.get('coin')} : profit partiel non servi, la position reste entière avec son stop")
    restore_total_stop(pos, float(pending.get("reliquat_qty", 0)))


def _handle_partial_chase_end(pending: dict, history: list) -> tuple[bool, bool]:
    """Fin de chasse d'un partiel. Retourne (history_changed, keep_pending) : si la limite ne peut
    pas être annulée elle reste vivante et suivie, jamais orpheline."""
    acquire_lock()
    try:
        try:
            _cli("order", "cancel", pending["txid"], "-o", "json", "--yes")
        except Exception as e:
            logger.warning(f"[Maker Exit Watcher] Partiel {pending['coin']} : annulation limite échouée, réessai : {e}")
            return False, True
        time.sleep(1)
        try:
            fill = json.loads(_cli("query-orders", pending["txid"], "-o", "json")).get(pending["txid"]) or {}
        except Exception:
            fill = {}
        _settle_partial(pending, history, fill)
        return True, False
    finally:
        release_lock()


def _finalize_position(history: list, pending: dict, exit_price: float, exit_fee_usdc: float,
                        exit_maker_or_taker: str) -> bool:
    if pending.get("partial"):
        return _finalize_partial(history, pending, exit_price, exit_fee_usdc, float(pending["quantity"]))
    pos = _find_position(history, pending["trade_id"])
    if pos is None:
        logger.error(f"[Maker Exit Watcher] trade_id {pending['trade_id']} introuvable dans l'historique")
        return False

    entry_price = float(pos.get("entry_price", 0))
    qty = float(pos.get("quantity", 0))
    entry_fee_usdc = float(pos.get("entry_fee_usdc", 0) or 0)
    net = compute_net_pnl(entry_price, exit_price, qty, entry_fee_usdc, exit_fee_usdc)

    pos.update({
        "status": "closed",
        "exit_price": exit_price,
        "exit_fee_usdc": exit_fee_usdc,
        "fees_usdc": net["fees_usdc"],
        "pnl_gross_usdc": net["pnl_gross_usdc"],
        "pnl_usdc": net["pnl_usdc"],
        "pnl_gross_pct": net["pnl_gross_pct"],
        "pnl_pct": net["pnl_pct"],
        "close_reason": pending["close_reason"],
        "cycle_id": pending.get("cycle_id"),
        "exit_date": datetime.now(timezone.utc).isoformat() + "Z",
        # Classification de la SORTIE (#390) — distincte de "maker_or_taker" qui désigne
        # l'ENTRÉE (consommé par commands/perf.py et phase7_mongo.py) : ne jamais l'écraser.
        "exit_maker_or_taker": exit_maker_or_taker,
    })
    label = "maker" if exit_maker_or_taker == _MAKER_FILL_LABEL else "repli marché"
    send_telegram(
        f"✅ Sortie {label} {pos.get('coin')} à {exit_price:.4g} USDC\n"
        f"{net['pnl_pct']:+.1f}% | {net['pnl_usdc']:+.2f} USDC"
    )
    return True


def _repose_stop_and_alert(pending: dict, history: list, qty: float, reason: str, context: str = "sortie maker") -> None:
    """context nomme, dans les notifications, le mécanisme appelant (par défaut la sortie maker,
    seul appelant jusqu'à #472) — un autre appelant (ex. vente sur signal) passe son propre libellé
    pour ne pas induire l'utilisateur en erreur sur l'origine du problème."""
    coin = pending["coin"]
    pair = pending["pair"]
    stop_price = pending.get("stop_price")
    pos = _find_position(history, pending["trade_id"])

    if not stop_price or pos is None:
        send_telegram(
            f"🚨 {coin} : position NON protégée après échec {context} ({reason}) — "
            "stop introuvable, intervention manuelle requise"
        )
        if pos is not None:
            pos["protection_failed"] = True
        return

    new_sl_txid, protection_failed, err_msg, stop_price_rounded = _place_stop_loss(pair, qty, stop_price)
    if protection_failed:
        pos["protection_failed"] = True
        send_telegram(
            f"🚨 {coin} : position NON protégée après échec {context} ({reason}) — "
            f"repose du stop a aussi échoué !{err_msg}"
        )
    else:
        pos["sl_order_txid"] = new_sl_txid
        pos["stop_price"] = stop_price_rounded
        pos["protection_failed"] = False
        send_telegram(f"🛡️ {coin} : {context} interrompue ({reason}) — stop reposé à {stop_price_rounded:.4g}")


def _handle_filled_order(pending: dict, order_status: dict, history: list) -> tuple[bool, int, int]:
    acquire_lock()
    try:
        vol_exec = float(order_status.get("vol_exec", pending["quantity"]))
        cost = float(order_status.get("cost", 0) or 0)
        exit_price = cost / vol_exec if vol_exec else pending["current_limit_price"]
        exit_fee_usdc = float(order_status.get("fee", 0) or 0)
        ok = _finalize_position(history, pending, exit_price, exit_fee_usdc, _MAKER_FILL_LABEL)
        return ok, (1 if ok else 0), 0
    except (ValueError, TypeError, KeyError) as e:
        logger.error(f"[Maker Exit Watcher] Enregistrement fill {pending.get('coin')} : {e}")
        return False, 0, 0
    finally:
        release_lock()


def _handle_externally_resolved(pending: dict, history: list, tick_state: dict) -> tuple[bool, int, int]:
    coin = pending["coin"]
    txid = pending["txid"]
    acquire_lock()
    try:
        try:
            query_raw = _cli("query-orders", txid, "-o", "json")
            fill = json.loads(query_raw).get(txid) or {}
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError):
            fill = {}

        if pending.get("partial"):
            _settle_partial(pending, history, fill)
            return True, 0, 0

        vol_exec = float(fill.get("vol_exec", 0) or 0)
        remaining_qty = pending["quantity"] - vol_exec

        if remaining_qty <= _QTY_EPSILON:
            cost = float(fill.get("cost", 0) or 0)
            exit_price = cost / vol_exec if vol_exec else pending["current_limit_price"]
            exit_fee_usdc = float(fill.get("fee", 0) or 0)
            ok = _finalize_position(history, pending, exit_price, exit_fee_usdc, _MAKER_FILL_LABEL)
            return ok, (1 if ok else 0), 0

        # Ordre disparu hors de notre fait avec un reliquat non vendu -> jamais d'abandon côté
        # sortie, on protège immédiatement (#390).
        _repose_stop_and_alert(pending, history, remaining_qty, reason=f"ordre résolu hors watcher ({fill.get('status', 'inconnu')})")
        return True, 0, 0
    except (json.JSONDecodeError, subprocess.CalledProcessError, ValueError, OSError) as e:
        logger.error(f"[Maker Exit Watcher] Résolution externe {coin} : {e}")
        tick_state["status"] = "error"
        tick_state["last_error"] = f"Résolution externe {coin} : {e}"
        return False, 0, 0
    finally:
        release_lock()


def _handle_chase_end(pending: dict, history: list, tick_state: dict) -> tuple[bool, int, int]:
    coin = pending["coin"]
    pair = pending["pair"]
    txid = pending["txid"]
    qty = pending["quantity"]
    acquire_lock()
    try:
        try:
            _cli("order", "cancel", txid, "-o", "json", "--yes")
        except (subprocess.CalledProcessError, OSError) as e:
            _repose_stop_and_alert(pending, history, qty, reason=f"annulation de la limite échouée : {e}")
            return True, 0, 0

        time.sleep(1)
        try:
            query_raw = _cli("query-orders", txid, "-o", "json")
            fill = json.loads(query_raw).get(txid) or {}
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError):
            fill = {}

        # À partir d'ici, la limite est annulée : toute erreur inattendue (parsing d'un fill
        # malformé, échec du repli marché ou de sa finalisation) ne doit jamais se solder par un
        # simple log — la position resterait nue et oubliée du suivi (#390). safe_qty affine au
        # fur et à mesure de ce qu'on sait vraiment devoir protéger.
        safe_qty = qty
        try:
            vol_exec = float(fill.get("vol_exec", 0) or 0)
            remaining_qty = qty - vol_exec
            safe_qty = remaining_qty

            if remaining_qty <= _QTY_EPSILON:
                cost = float(fill.get("cost", 0) or 0)
                exit_price = cost / vol_exec if vol_exec else pending["current_limit_price"]
                exit_fee_usdc = float(fill.get("fee", 0) or 0)
                ok = _finalize_position(history, pending, exit_price, exit_fee_usdc, _MAKER_FILL_LABEL)
                return ok, (1 if ok else 0), 0

            # On voulait sortir, on sort : jamais d'abandon côté sortie (#390).
            try:
                sell_raw = _cli("order", "sell", pair, str(remaining_qty), "--type", "market", "-o", "json", "--yes")
                sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
                market_txid = (sell_resp.get("txid") or [None])[0]
                if not market_txid:
                    raise RuntimeError("pas de txid marché")
                time.sleep(1)
                mfill_raw = _cli("query-orders", market_txid, "-o", "json")
                mfill = json.loads(mfill_raw).get(market_txid) or {}
                if mfill.get("status") != "closed":
                    raise RuntimeError(f"non rempli (status: {mfill.get('status')})")
            except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError, RuntimeError) as e:
                _repose_stop_and_alert(pending, history, remaining_qty, reason=f"vente au marché échouée : {e}")
                return True, 0, 0

            market_vol = float(mfill.get("vol_exec", remaining_qty))
            market_cost = float(mfill.get("cost", 0) or 0)
            market_fee = float(mfill.get("fee", 0) or 0)
            total_vol = vol_exec + market_vol
            total_cost = float(fill.get("cost", 0) or 0) + market_cost
            exit_price = total_cost / total_vol if total_vol else pending["current_limit_price"]
            exit_fee_usdc = float(fill.get("fee", 0) or 0) + market_fee
            ok = _finalize_position(history, pending, exit_price, exit_fee_usdc, "taker")
            return ok, 0, (1 if ok else 0)
        except (ValueError, TypeError, KeyError) as e:
            _repose_stop_and_alert(pending, history, safe_qty, reason=f"erreur inattendue après annulation de la limite : {e}")
            return True, 0, 0
    except (json.JSONDecodeError, subprocess.CalledProcessError, ValueError, OSError) as e:
        logger.error(f"[Maker Exit Watcher] Fin de chasse {coin} : {e}")
        tick_state["status"] = "error"
        tick_state["last_error"] = f"Fin de chasse {coin} : {e}"
        return False, 0, 0
    finally:
        release_lock()


def _handle_amend_order(pending: dict, current_ask: float) -> None:
    coin = pending["coin"]
    txid = pending["txid"]
    try:
        amend_raw = _cli("order", "amend", "--txid", txid, "--limit-price", str(current_ask),
                          "--post-only", "-o", "json")
        amend_resp = json.loads(amend_raw) if amend_raw.strip() else {}
        if amend_resp.get("error"):
            logger.debug(f"[Maker Exit Watcher] Amend {coin} rejeté ({amend_resp['error']}), réessai au tick suivant")
        else:
            pending["current_limit_price"] = current_ask
            pending["adjustments"] = pending.get("adjustments", 0) + 1
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError) as e:
        logger.debug(f"[Maker Exit Watcher] Amend {coin} erreur, réessai au tick suivant : {e}")


def _maker_exit_watcher_tick(cfg: dict) -> None:
    if is_locked():
        # Distinct de "ok" (#461) : le watcher n'a pas pu s'exécuter, pas "rien à faire".
        _write_watcher_state("locked", None, 0)
        return

    pending_orders = load_maker_exit_pending_orders()
    if not pending_orders:
        _write_watcher_state("ok", None, 0)
        return

    maker_exit_max_concession_pct = cfg.get("maker_exit_max_concession_pct", 0.003)
    maker_exit_timeout_seconds = cfg.get("maker_exit_timeout_seconds", 600)

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
            # Idem (#461) : ordre reporté au tick suivant faute de verrou, pas faute de travail.
            remaining_pending.append(pending)
            tick_state["status"] = "locked"
            continue

        try:
            query_raw = _cli("query-orders", txid, "-o", "json")
            order_status = json.loads(query_raw).get(txid) or {}
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(f"[Maker Exit Watcher] query-orders {txid} ({coin}) : {e}")
            tick_state["status"] = "warning"
            tick_state["last_error"] = f"query-orders {coin} : {e}"
            remaining_pending.append(pending)
            continue

        status = order_status.get("status")

        if status == "closed":
            changed, fills, fallbacks = _handle_filled_order(pending, order_status, history)
            history_changed = history_changed or changed
            fills_delta += fills
            fallbacks_delta += fallbacks
            continue

        if status in ("canceled", "expired"):
            changed, fills, fallbacks = _handle_externally_resolved(pending, history, tick_state)
            history_changed = history_changed or changed
            fills_delta += fills
            fallbacks_delta += fallbacks
            continue

        # Ordre toujours vivant ("open") -> évaluation des bornes d'arrêt.
        try:
            ticker_raw = _cli("ticker", pair, "-o", "json")
            ticker_data = json.loads(ticker_raw).get(pair, {})
            current_ask = float(ticker_data.get("a", [0])[0])
            current_last = float(ticker_data.get("c", [0])[0])
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, OSError, IndexError) as e:
            logger.warning(f"[Maker Exit Watcher] Ticker {coin} indisponible : {e}")
            tick_state["status"] = "warning"
            tick_state["last_error"] = f"Ticker {coin} indisponible : {e}"
            remaining_pending.append(pending)
            continue

        elapsed_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(pending["placed_at"])).total_seconds()
        initial_price = pending["initial_limit_price"]
        # Concession = distance vers le bas depuis le prix de pose (symétrique de l'entrée, qui
        # concède vers le haut) : l'ask baisse -> il faut baisser son prix pour rester compétitif.
        concession_pct = max(0.0, (initial_price - current_ask) / initial_price) if initial_price else 0.0
        stop_price = pending.get("stop_price") or 0.0
        # Garde-fou central (#390) : le cours redescend au niveau où était le stop -> bascule
        # immédiate au marché, sans attendre le budget de concession ni le délai.
        price_redescended = bool(stop_price) and current_last <= stop_price

        if price_redescended or concession_pct >= maker_exit_max_concession_pct or elapsed_seconds >= maker_exit_timeout_seconds:
            if pending.get("partial"):
                changed, keep = _handle_partial_chase_end(pending, history)
                history_changed = history_changed or changed
                if keep:
                    remaining_pending.append(pending)
                continue
            changed, fills, fallbacks = _handle_chase_end(pending, history, tick_state)
            history_changed = history_changed or changed
            fills_delta += fills
            fallbacks_delta += fallbacks
            continue

        if current_ask and current_ask != pending.get("current_limit_price"):
            _handle_amend_order(pending, current_ask)

        remaining_pending.append(pending)

    save_maker_exit_pending_orders(remaining_pending)

    if history_changed:
        save_trade_history(history)
        publish_trade_history_slices(history, "Maker Exit Watcher")  # #500 : sans attendre la Phase 7

    _write_watcher_state(tick_state["status"], tick_state["last_error"], orders_checked,
                          fills_delta, fallbacks_delta)
