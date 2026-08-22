#!/usr/bin/env python3
"""Backfill des frais Kraken (fee) et du PnL net dans state/trade_history.json (#382).

Source des fills réels : `kraken trades-history -o json`, paginé via --offset. Rapprochement :
- Entrées : tous les fills dont `ordertxid` == `entry_order_id` du trade (somme des fee, gère les
  ordres à exécution partielle).
- Sorties : aucun txid de sortie n'est stocké aujourd'hui -> rapprochement par paire
  ({coin}USDC) + volume exact à 8 décimales (tolérance relative 0.0001), en prenant le fill
  "sell" le plus proche temporellement de exit_date, dans une fenêtre de 48h avant (un SL peut
  se déclencher côté Kraken plusieurs heures avant que le bot ne le détecte au cycle suivant) à
  1h après exit_date.

Chaque fill Kraken consommé (matché) ne sert qu'une seule fois (pas de double comptage). Un côté
(entrée ou sortie) non matché — trade antérieur à la portée de l'API (~03/07/2026) ou fill
introuvable — est estimé au taux du palier Kraken de l'époque, et le trade est marqué
fees_estimated=True. Jamais confondu avec du mesuré.

Usage :
    .venv/bin/python3 scripts/backfill_fees.py [--dry-run] [--force]

--dry-run : n'écrit rien dans trade_history.json, affiche uniquement le résumé.
--force   : recalcule même les trades qui ont déjà un fees_usdc renseigné (par défaut skippés).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import binance, _save_trade_history_atomic, compute_net_pnl  # noqa: E402
from core.timing import parse_dt  # noqa: E402

TRADE_HISTORY_PATH = os.path.join(PROJECT_DIR, "state", "trade_history.json")

# Grille de frais taker Kraken par palier appliqué par côté (entrée ou sortie), utilisée en
# fallback quand aucun fill réel n'a pu être rapproché (#382).
_FEE_TIERS = [
    (datetime(2026, 7, 9, tzinfo=timezone.utc), 0.0040),
    (datetime(2026, 7, 22, tzinfo=timezone.utc), 0.0080),
    (None, 0.0060),
]

EXIT_WINDOW_BEFORE = timedelta(hours=48)
EXIT_WINDOW_AFTER = timedelta(hours=1)
VOLUME_REL_TOLERANCE = 0.0001
TRADES_HISTORY_PAGE_SIZE = 50


def _estimated_fee_rate(dt: datetime) -> float:
    for threshold, rate in _FEE_TIERS:
        if threshold is None or dt < threshold:
            return rate
    return _FEE_TIERS[-1][1]


def _fetch_all_fills() -> list:
    """Pagine `kraken trades-history` par lots jusqu'à épuisement."""
    fills = []
    offset = 0
    while True:
        raw = binance("trades-history", "-o", "json", "--offset", str(offset))
        data = json.loads(raw)
        batch = data.get("trades", {})
        if not batch:
            break
        for txid, trade in batch.items():
            trade = dict(trade)
            trade["_txid"] = txid
            fills.append(trade)
        if len(batch) < TRADES_HISTORY_PAGE_SIZE:
            break
        offset += TRADES_HISTORY_PAGE_SIZE
    return fills


def _match_entry_fee(trade: dict, fills: list, consumed: set):
    """Somme les fee de tous les fills dont ordertxid == entry_order_id (gère les fills partiels)."""
    entry_order_id = trade.get("entry_order_id")
    if not entry_order_id:
        return None
    matches = [f for f in fills if f["_txid"] not in consumed and f.get("ordertxid") == entry_order_id]
    if not matches:
        return None
    for f in matches:
        consumed.add(f["_txid"])
    return sum(float(f.get("fee", 0) or 0) for f in matches)


def _match_exit_fee(trade: dict, fills: list, consumed: set):
    """Fill "sell" le plus proche temporellement, même paire, même volume (tolérance 0.0001)."""
    coin = trade.get("coin")
    pair = f"{coin}USDC" if coin else None
    qty = trade.get("quantity")
    exit_dt = parse_dt(trade.get("exit_date"))
    if not pair or qty is None or exit_dt is None:
        return None
    qty = float(qty)
    if qty == 0:
        return None
    window_start = exit_dt - EXIT_WINDOW_BEFORE
    window_end = exit_dt + EXIT_WINDOW_AFTER

    best = None
    best_delta = None
    for fill in fills:
        if fill["_txid"] in consumed:
            continue
        if fill.get("pair") != pair or fill.get("type") != "sell":
            continue
        fill_vol = float(fill.get("vol", 0) or 0)
        if fill_vol == 0 or abs(fill_vol - qty) / qty > VOLUME_REL_TOLERANCE:
            continue
        fill_dt = datetime.fromtimestamp(float(fill["time"]), tz=timezone.utc)
        if not (window_start <= fill_dt <= window_end):
            continue
        delta = abs((fill_dt - exit_dt).total_seconds())
        if best is None or delta < best_delta:
            best, best_delta = fill, delta

    if best is None:
        return None
    consumed.add(best["_txid"])
    return float(best.get("fee", 0) or 0)


def backfill(history: list, fills: list, force: bool) -> tuple:
    consumed = set()
    stats = {
        "trades_updated": 0, "trades_skipped_already_done": 0, "trades_skipped_not_closed": 0,
        "entries_measured": 0, "entries_estimated": 0,
        "exits_measured": 0, "exits_estimated": 0,
    }

    for trade in history:
        if trade.get("status") != "closed":
            stats["trades_skipped_not_closed"] += 1
            continue
        if trade.get("fees_usdc") is not None and not force:
            stats["trades_skipped_already_done"] += 1
            continue

        estimated = False

        entry_fee = _match_entry_fee(trade, fills, consumed)
        if entry_fee is not None:
            stats["entries_measured"] += 1
        else:
            entry_dt = parse_dt(trade.get("date"))
            rate = _estimated_fee_rate(entry_dt) if entry_dt else _FEE_TIERS[0][1]
            entry_price = float(trade.get("entry_price", 0) or 0)
            qty = float(trade.get("quantity", 0) or 0)
            entry_fee = entry_price * qty * rate
            estimated = True
            stats["entries_estimated"] += 1

        exit_fee = _match_exit_fee(trade, fills, consumed)
        if exit_fee is not None:
            stats["exits_measured"] += 1
        else:
            exit_dt = parse_dt(trade.get("exit_date"))
            rate = _estimated_fee_rate(exit_dt) if exit_dt else _FEE_TIERS[0][1]
            exit_price = float(trade.get("exit_price", 0) or 0)
            qty = float(trade.get("quantity", 0) or 0)
            exit_fee = exit_price * qty * rate
            estimated = True
            stats["exits_estimated"] += 1

        entry_price = float(trade.get("entry_price", 0) or 0)
        exit_price = float(trade.get("exit_price", 0) or 0)
        qty = float(trade.get("quantity", 0) or 0)
        net = compute_net_pnl(entry_price, exit_price, qty, entry_fee, exit_fee)

        trade["entry_fee_usdc"] = entry_fee
        trade["exit_fee_usdc"] = exit_fee
        trade["fees_usdc"] = net["fees_usdc"]
        trade["pnl_gross_usdc"] = net["pnl_gross_usdc"]
        trade["pnl_usdc"] = net["pnl_usdc"]
        trade["fees_estimated"] = estimated
        stats["trades_updated"] += 1

    return history, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="N'écrit rien, affiche le résumé uniquement")
    parser.add_argument("--force", action="store_true", help="Recalcule même les trades déjà backfillés")
    args = parser.parse_args()

    with open(TRADE_HISTORY_PATH) as f:
        history = json.load(f)

    fills = _fetch_all_fills()
    print(f"{len(fills)} fills récupérés depuis kraken trades-history")

    history, stats = backfill(history, fills, args.force)

    print("--- Résumé backfill frais (#382) ---")
    for k, v in stats.items():
        print(f"{k}: {v}")

    if args.dry_run:
        print("--dry-run : aucune écriture effectuée.")
        return

    if stats["trades_updated"] == 0:
        print("Aucun trade à mettre à jour.")
        return

    backup_path = f"{TRADE_HISTORY_PATH}.bak.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    with open(TRADE_HISTORY_PATH) as f:
        backup_content = f.read()
    with open(backup_path, "w") as f:
        f.write(backup_content)
    print(f"Backup créé : {backup_path}")

    _save_trade_history_atomic(history)
    print("state/trade_history.json mis à jour (écriture atomique).")


if __name__ == "__main__":
    main()
