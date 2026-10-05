#!/usr/bin/env python3
"""Rejeu (#519) : cible actuelle (#516, plafond max_tp_pct quand la résistance est trop proche) vs
cible au plancher entry x (1 + 2 x frais) dans ce cas, sur les trades clôturés de
state/trade_history.json. Lecture seule : seuls des `kraken ohlc` publics sont appelés.

Usage :
    .venv/bin/python scripts/target_floor_replay.py [--since 2026-07-03]

Les deux règles sont recodées ici (tp_old / tp_new) pour que le rejeu reste valable après le merge.
Réutilise les conventions de scripts/breakeven_replay.py et scripts/partial_tp_replay.py :
- bougies 4h Kraken démarrant après l'entrée et finissant avant la sortie réelle ;
- stop initial touché avant la cible dans une même bougie (hypothèse défavorable), sortie taker 0,60 %
  (à l'ouverture si gap) ;
- break-even (#513) : déclencheur 1,5 % sur le high, stop remonté à entry x (1 + 0,009) actif dès la
  bougie suivante, sortie taker 0,60 % ;
- partiel (#514) : 33 % vendus maker à entry x 1,03 si la bougie touche ce niveau avant la cible
  et avant la sortie break-even ; ignoré sous min_order_usdc ;
- cible atteinte : sortie maker 0,30 % au prix de la cible (maker exit) ; entrée maker 0,30 % ;
- si rien ne se déclenche avant la sortie réelle, le PnL réel du trade est conservé (au prorata).
La résistance est le plus haut des N bougies 4h clôturées avant l'entrée (resistance_lookback_4h).
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "binance-bot"))
from breakeven_replay import MAKER_FEE, PROJECT_DIR, TAKER_FEE, fetch_candles, load_trades, parse_ts  # noqa: E402
from core.trade_helpers import (  # noqa: E402
    RESISTANCE_TP_FACTOR, initial_stop_price, resistance_from_candles,
)

INTERVAL = 240
BE_TRIGGER, PARTIAL_FRAC = 0.015, 0.33


def tp_old(entry, sd, rr, fee, mx, resistance):
    """Règle #516 : résistance ignorée sous le plancher, cible = min(mécanique, plafond)."""
    mech = entry * (1 + (sd + fee) * rr + fee)
    capped = min(mech, entry * (1 + mx))
    if resistance is not None and resistance > entry:
        tp_res = min(capped, resistance * RESISTANCE_TP_FACTOR)
        if tp_res >= entry * (1 + 2 * fee):
            return tp_res
    return capped


def tp_new(entry, sd, rr, fee, mx, resistance):
    """Règle #519 : résistance (> entry) trop proche -> cible = plancher au lieu du plafond."""
    tp = tp_old(entry, sd, rr, fee, mx, resistance)
    if resistance is not None and resistance > entry and resistance * RESISTANCE_TP_FACTOR < entry * (1 + 2 * fee):
        return entry * (1 + 2 * fee)
    return tp


def simulate(t, candles, tp, stop, cfg):
    """Retourne (pnl, issue, partiel_pris) ; issue in target/stop/be/rest."""
    entry, qty = float(t["entry_price"]), float(t["quantity"])
    fee_rt = cfg["fee_round_trip_pct"]
    be_trigger, be_level = entry * (1 + BE_TRIGGER), entry * (1 + fee_rt)
    pt = entry * (1 + cfg["partial_tp_trigger_pct"])
    frac = cfg["partial_tp_fraction"]
    mo = cfg["min_order_usdc"]
    partial_ok = frac * qty * entry >= mo and (1 - frac) * qty * entry >= mo
    cost = entry * (1 + MAKER_FEE)
    armed, sold = None, 0.0
    pnl_part = 0.0

    def finish(exit_px, fee, issue):
        rest = qty - sold
        return pnl_part + rest * exit_px * (1 - fee) - rest * cost, issue, sold > 0

    for i, (_, o, h, lo) in enumerate(candles):
        stop_now = be_level if armed is not None and i > armed else stop
        if lo <= stop_now or o <= stop_now:
            return finish(min(stop_now, o), TAKER_FEE, "be" if stop_now == be_level else "stop")
        if armed is None and h >= be_trigger:
            armed = i
        if partial_ok and not sold and h >= pt and pt < tp:
            sold = frac * qty
            pnl_part = sold * pt * (1 - MAKER_FEE) - sold * cost
        if h >= tp:
            return finish(tp, MAKER_FEE, "target")
    real_frac = (qty - sold) / qty
    return pnl_part + real_frac * t["pnl_usdc"], "rest", sold > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-03")
    args = ap.parse_args()
    cfg = json.load(open(os.path.join(PROJECT_DIR, "config.json")))
    fee, rr, mx = cfg["fee_round_trip_pct"], cfg["reward_risk_ratio"], cfg["max_tp_pct"]
    lookback = cfg.get("resistance_lookback_4h", 30)
    trades = load_trades(args.since)
    rows, skipped = [], 0
    for t in trades:
        try:
            all_c = fetch_candles(f"{t['coin']}USDC", INTERVAL)
        except Exception:
            skipped += 1
            continue
        e_ts, x_ts = parse_ts(t["date"]), parse_ts(t["exit_date"])
        entry = float(t["entry_price"])
        sd = (entry - initial_stop_price(t, fee)) / entry
        raw = [[c[0], 0, c[2], c[3]] for c in all_c]
        res = resistance_from_candles(raw, lookback, now_ts=e_ts)
        path = [c for c in all_c if c[0] >= e_ts and c[0] + INTERVAL * 60 <= x_ts]
        if len(all_c) == 0 or all_c[0][0] > e_ts - lookback * INTERVAL * 60:
            skipped += 1
            continue
        stop = initial_stop_price(t, fee)
        tp_a = tp_old(entry, sd, rr, fee, mx, res)
        tp_b = tp_new(entry, sd, rr, fee, mx, res)
        rows.append((t, simulate(t, path, tp_a, stop, cfg), simulate(t, path, tp_b, stop, cfg), tp_a, tp_b))

    n_diff = sum(1 for r in rows if abs(r[3] - r[4]) > 1e-9)
    print(f"== Rejeu cible au plancher depuis {args.since} : {len(rows)} trades ({skipped} ignorés, historique "
          f"Kraken insuffisant), cible modifiée sur {n_diff} ==")
    for label, sel in (("tous les trades", rows),
                       ("trades dont la cible change", [r for r in rows if abs(r[3] - r[4]) > 1e-9])):
        print(f"\n[{label}] {len(sel)} trades")
        print(f"{'règle':<22}{'PnL net':>9}{'cibles':>8}{'stops':>7}{'BE':>5}{'partiels':>9}{'rest':>6}"
              f"{'gagnants':>9}{'cible méd %':>12}")
        real = sum(r[0]["pnl_usdc"] for r in sel)
        print(f"{'réel (prod)':<22}{real:>+9.2f}")
        for name, k, ki in (("actuelle (#516)", 1, 3), ("plancher (#519)", 2, 4)):
            res_ = [r[k] for r in sel]
            tot = sum(x[0] for x in res_)
            c = lambda issue: sum(1 for x in res_ if x[1] == issue)  # noqa: E731
            med = statistics.median((r[ki] / float(r[0]["entry_price"]) - 1) * 100 for r in sel) if sel else 0
            print(f"{name:<22}{tot:>+9.2f}{c('target'):>8}{c('stop'):>7}{c('be'):>5}"
                  f"{sum(1 for x in res_ if x[2]):>9}{c('rest'):>6}{sum(1 for x in res_ if x[0] > 0):>9}{med:>12.2f}")
        tot_a, tot_b = sum(r[1][0] for r in sel), sum(r[2][0] for r in sel)
        better = sum(1 for r in sel if r[2][0] > r[1][0] + 1e-9)
        worse = sum(1 for r in sel if r[2][0] < r[1][0] - 1e-9)
        print(f"delta plancher - actuelle : {tot_b - tot_a:+.2f} USDC | trades meilleurs {better} pires {worse}")


if __name__ == "__main__":
    main()
