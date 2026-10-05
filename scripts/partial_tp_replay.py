#!/usr/bin/env python3
"""Rejeu du profit partiel (#514) sur les trades clôturés de state/trade_history.json.

Réutilise les données (bougies Kraken publiques) et les conventions de scripts/breakeven_replay.py.
Le break-even retenu (#513 : déclencheur 1,5 %, niveau entry x (1 + frais aller-retour)) est toujours
appliqué ; le partiel vient en plus. Référence de comparaison : « break-even seul ».

Usage :
    .venv/bin/python scripts/partial_tp_replay.py [--since 2026-07-03] [--resolution 240|mixed]

Conventions (défavorables, comme pour le break-even) :
- bougies entièrement comprises entre l'entrée et la sortie réelle ;
- le déclencheur du partiel est détecté sur le plus haut d'une bougie ; la vente maker de la fraction
  est supposée remplie AU prix du déclencheur, frais 0,30 % maker ;
- si la bougie de sortie du break-even contient aussi le déclencheur du partiel, on suppose que le
  stop a été touché d'abord : pas de partiel ;
- le reliquat suit exactement le scénario « break-even seul » (sortie réelle ou sortie break-even
  à 0,60 % taker), au prorata de la quantité restante ;
- partiel ignoré si la fraction ou le reliquat vaut moins de min_order_usdc (config.json) à l'entrée.
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from breakeven_replay import (  # noqa: E402
    FEE_ROUND_TRIP, MAKER_FEE, PROJECT_DIR, TAKER_FEE, fetch_candles, load_trades, parse_ts, pick_interval,
)

BE_TRIGGER = 0.015
BE_LEVEL = FEE_ROUND_TRIP
TRIGGERS = [0.015, 0.020, 0.025, 0.030]
FRACTIONS = [0.33, 0.50]
SKIP_MIN_ORDER = True


def min_order_usdc():
    with open(os.path.join(PROJECT_DIR, "config.json")) as f:
        return float(json.load(f).get("min_order_usdc", 9))


def scenario(t, resolution, now_ts):
    """Retourne (candles, pnl_rest, be_exit_idx) : PnL du trade complet en « break-even seul »."""
    entry, qty = float(t["entry_price"]), float(t["quantity"])
    e_ts, x_ts = parse_ts(t["date"]), parse_ts(t["exit_date"])
    interval = pick_interval(e_ts, resolution, now_ts)
    candles = [c for c in fetch_candles(f"{t['coin']}USDC", interval)
               if c[0] >= e_ts and c[0] + interval * 60 <= x_ts]
    trigger, level = entry * (1 + BE_TRIGGER), entry * (1 + BE_LEVEL)
    armed = None
    for i, (_, o, h, lo) in enumerate(candles):
        if armed is not None:
            if lo <= level or o <= level:
                exit_px = min(level, o)
                pnl = exit_px * qty * (1 - TAKER_FEE) - entry * qty * (1 + MAKER_FEE)
                return candles, pnl, i
        elif h >= trigger:
            armed = i
    return candles, t["pnl_usdc"], None


def with_partial(t, candles, pnl_rest, be_idx, trig, frac, min_order):
    """PnL du trade avec partiel ; retourne (pnl, partiel_pris)."""
    entry, qty = float(t["entry_price"]), float(t["quantity"])
    if SKIP_MIN_ORDER and (frac * qty * entry < min_order or (1 - frac) * qty * entry < min_order):
        return pnl_rest, False
    target = entry * (1 + trig)
    j = next((i for i, c in enumerate(candles) if c[2] >= target), None)
    if j is None or (be_idx is not None and j >= be_idx):
        return pnl_rest, False
    sold = frac * qty
    pnl_part = sold * target * (1 - MAKER_FEE) - sold * entry * (1 + MAKER_FEE)
    return pnl_part + (1 - frac) * pnl_rest, True


def run(trades, resolution):
    now_ts = datetime.now(timezone.utc).timestamp()
    mo = min_order_usdc()
    real = sum(t["pnl_usdc"] for t in trades)
    scen = [scenario(t, resolution, now_ts) for t in trades]
    be_only = sum(s[1] for s in scen)
    print(f"Trades : {len(trades)} | réel : {real:+.2f} | break-even seul : {be_only:+.2f} "
          f"({be_only - real:+.2f} vs réel)")
    print(f"{'déclench.':>9} {'fraction':>8} {'PnL net':>9} {'vs réel':>8} {'vs BE seul':>10} {'partiels':>8} "
          f"{'trades +':>8} {'trades -':>8}")
    rows = []
    for trig in TRIGGERS:
        for frac in FRACTIONS:
            total, n, gain_trades, loss_trades = 0.0, 0, 0, 0
            for t, (candles, pnl_rest, be_idx) in zip(trades, scen):
                pnl, taken = with_partial(t, candles, pnl_rest, be_idx, trig, frac, mo)
                total += pnl
                if taken:
                    n += 1
                    gain_trades += pnl > pnl_rest
                    loss_trades += pnl < pnl_rest
            rows.append((trig, frac, total))
            print(f"{trig * 100:>8.1f}% {frac * 100:>7.0f}% {total:>+9.2f} {total - real:>+8.2f} "
                  f"{total - be_only:>+10.2f} {n:>8} {gain_trades:>8} {loss_trades:>8}")
    # robustesse : delta vs BE seul médian par ligne/colonne
    print("médiane des deltas vs BE seul :", f"{statistics.median(r[2] - be_only for r in rows):+.2f}",
          "| cellules > 0 :", sum(1 for r in rows if r[2] > be_only), "/", len(rows))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-03")
    ap.add_argument("--resolution", default="240", choices=["240", "mixed"])
    args = ap.parse_args()
    trades = load_trades(args.since)
    print(f"== Rejeu profit partiel + break-even depuis {args.since}, résolution {args.resolution} ==")
    run(trades, args.resolution)


if __name__ == "__main__":
    main()
