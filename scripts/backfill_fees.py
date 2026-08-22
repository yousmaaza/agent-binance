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

pnl_gross_usdc reprend le pnl_usdc déjà stocké AVANT backfill (l'ancien calcul historique, cf.
#382) — jamais une reconstitution via (exit_price - entry_price) * quantity : sur les trades de
l'ère Binance (avant migration Kraken), entry_price/exit_price/quantity ne sont pas garantis
cohérents entre eux (ex. #382 post-mortem — trade SYN 38515bab, sl_hit à +61% du prix d'entrée,
+44 USDC fictifs injectés lors du premier backfill en prod). pnl_gross_pct reprend de même le
pnl_pct stocké. Garde-fou : si le pnl_usdc stocké diverge de plus de 1% (relatif) de
(exit_price - entry_price) * quantity, le trade n'est PAS modifié — il est seulement signalé dans
le résumé (trades_incoherents), y compris en --dry-run.

Usage :
    .venv/bin/python3 scripts/backfill_fees.py [--dry-run] [--force]

--dry-run : n'écrit rien dans trade_history.json, affiche uniquement le résumé (diagnostics inclus).
--force   : recalcule même les trades qui ont déjà un fees_usdc renseigné (par défaut skippés).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import binance, _save_trade_history_atomic  # noqa: E402
from core.timing import parse_dt  # noqa: E402

TRADE_HISTORY_PATH = os.path.join(PROJECT_DIR, "state", "trade_history.json")

# Écart relatif max toléré entre pnl_usdc stocké et (exit_price - entry_price) * quantity avant
# de considérer un trade incohérent (données legacy Binance non fiables) et de ne pas y toucher.
COHERENCE_REL_TOLERANCE = 0.01

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


def _coherence_diagnostic(trade: dict):
    """Compare le pnl_usdc stocké à (exit_price - entry_price) * quantity.

    Retourne un dict de diagnostic si l'écart relatif dépasse COHERENCE_REL_TOLERANCE (données
    legacy potentiellement incohérentes entre elles, cf. #382 post-mortem), sinon None.
    """
    stored_pnl = trade.get("pnl_usdc")
    if stored_pnl is None:
        # Trade closed sans pnl_usdc stocké — enregistrement douteux, signalé plutôt qu'un crash
        # sur trade["pnl_usdc"] plus bas dans backfill().
        return {
            "trade_id": trade.get("trade_id"),
            "coin": trade.get("coin"),
            "pnl_usdc_stored": None,
            "pnl_recomputed_from_prices": None,
            "rel_diff_pct": None,
        }
    entry_price = float(trade.get("entry_price", 0) or 0)
    exit_price = float(trade.get("exit_price", 0) or 0)
    qty = float(trade.get("quantity", 0) or 0)
    recomputed = (exit_price - entry_price) * qty

    denom = max(abs(stored_pnl), abs(recomputed))
    if denom < 1e-9:
        return None
    rel_diff = abs(recomputed - stored_pnl) / denom
    if rel_diff <= COHERENCE_REL_TOLERANCE:
        return None

    return {
        "trade_id": trade.get("trade_id"),
        "coin": trade.get("coin"),
        "pnl_usdc_stored": stored_pnl,
        "pnl_recomputed_from_prices": recomputed,
        "rel_diff_pct": rel_diff * 100,
    }


def backfill(history: list, fills: list, force: bool) -> tuple:
    consumed = set()
    stats = {
        "trades_updated": 0, "trades_skipped_already_done": 0, "trades_skipped_not_closed": 0,
        "trades_incoherents": 0,
        "entries_measured": 0, "entries_estimated": 0,
        "exits_measured": 0, "exits_estimated": 0,
    }
    incoherent_trades = []

    for trade in history:
        if trade.get("status") != "closed":
            stats["trades_skipped_not_closed"] += 1
            continue
        if trade.get("fees_usdc") is not None and not force:
            stats["trades_skipped_already_done"] += 1
            continue

        diag = _coherence_diagnostic(trade)
        if diag is not None:
            stats["trades_incoherents"] += 1
            incoherent_trades.append(diag)
            continue  # champs internes incohérents (ex. legacy Binance) -> ne pas écraser

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

        # pnl_gross_usdc/pct = l'ancien calcul déjà stocké (#382), jamais une reconstitution via
        # les prix — la cohérence entre entry_price/exit_price/quantity n'est pas garantie sur les
        # trades legacy (cf. _coherence_diagnostic ci-dessus, qui a déjà écarté les cas douteux).
        pnl_gross_usdc = trade["pnl_usdc"]
        pnl_gross_pct = trade.get("pnl_pct")
        if pnl_gross_pct is None:
            entry_price = float(trade.get("entry_price", 0) or 0)
            pnl_gross_pct = (float(trade.get("exit_price", 0) or 0) - entry_price) / entry_price * 100 if entry_price else 0.0

        fees_usdc = entry_fee + exit_fee
        pnl_usdc = pnl_gross_usdc - fees_usdc
        notional = float(trade.get("entry_price", 0) or 0) * float(trade.get("quantity", 0) or 0)
        pnl_pct = (pnl_usdc / notional * 100) if notional else pnl_gross_pct

        trade["entry_fee_usdc"] = entry_fee
        trade["exit_fee_usdc"] = exit_fee
        trade["fees_usdc"] = fees_usdc
        trade["pnl_gross_usdc"] = pnl_gross_usdc
        trade["pnl_usdc"] = pnl_usdc
        trade["pnl_gross_pct"] = pnl_gross_pct
        trade["pnl_pct"] = pnl_pct
        trade["fees_estimated"] = estimated
        stats["trades_updated"] += 1

    return history, stats, incoherent_trades


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="N'écrit rien, affiche le résumé uniquement")
    parser.add_argument("--force", action="store_true", help="Recalcule même les trades déjà backfillés")
    args = parser.parse_args()

    with open(TRADE_HISTORY_PATH) as f:
        history = json.load(f)

    fills = _fetch_all_fills()
    print(f"{len(fills)} fills récupérés depuis kraken trades-history")

    history, stats, incoherent_trades = backfill(history, fills, args.force)

    print("--- Résumé backfill frais (#382) ---")
    for k, v in stats.items():
        print(f"{k}: {v}")

    if incoherent_trades:
        print("--- Trades incohérents (non modifiés — cf. COHERENCE_REL_TOLERANCE) ---")
        for d in incoherent_trades:
            stored = "absent" if d["pnl_usdc_stored"] is None else f"{d['pnl_usdc_stored']:.4f}"
            recomputed = "n/a" if d["pnl_recomputed_from_prices"] is None else f"{d['pnl_recomputed_from_prices']:.4f}"
            ecart = "n/a" if d["rel_diff_pct"] is None else f"{d['rel_diff_pct']:.1f}%"
            print(
                f"trade_id={d['trade_id']} coin={d['coin']} "
                f"pnl_usdc_stored={stored} pnl_recomputed_from_prices={recomputed} ecart_relatif={ecart}"
            )

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
