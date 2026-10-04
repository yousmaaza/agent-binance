#!/usr/bin/env python3
"""Rejeu du break-even (#513) sur les trades clôturés de state/trade_history.json.

Pour chaque trade, on rejoue le chemin de prix sur bougies Kraken publiques (`kraken ohlc`) et on
regarde ce qui se serait passé si, dès que le prix touche entry x (1 + déclencheur), le stop avait
été remonté au niveau break-even (entry, ou entry x (1 + fee_round_trip_pct)).

Usage :
    .venv/bin/python scripts/breakeven_replay.py [--since 2026-07-03] [--resolution 240|mixed]

Conventions (volontairement conservatrices pour le break-even) :
- bougies utilisées : celles qui démarrent après l'entrée et se terminent avant la sortie réelle ;
- le déclencheur est détecté sur le plus haut (high) d'une bougie, le stop break-even n'est actif
  qu'à partir de la bougie SUIVANTE (latence tp_watcher 2 min + annulation/replacement) ;
- stop touché si low <= niveau ; si la bougie ouvre sous le niveau, sortie à l'ouverture (gap) ;
- frais réels : 0,30 % maker à l'entrée, 0,60 % taker à la sortie sur stop (sortie stop = market) ;
- si le break-even n'intervient pas avant la sortie réelle, le PnL réel est conservé.
Résolution : 240 = bougies 4h partout ; mixed = 15 min (<= 7 j), 1h (<= 30 j), sinon 4h.
"""
import argparse
import json
import os
import re
import statistics
import subprocess
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KRAKEN = os.path.expanduser("~/.cargo/bin/kraken")
MAKER_FEE = 0.003
TAKER_FEE = 0.006
FEE_ROUND_TRIP = 0.009
TRIGGERS = [0.010, 0.015, 0.020, 0.025]
LEVELS = [("entry", 0.0), ("entry+frais", FEE_ROUND_TRIP)]

_candle_cache = {}


def parse_ts(s):
    s = re.sub(r"\+00:00Z$", "+00:00", s)
    s = s.replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def fetch_candles(pair, interval):
    key = (pair, interval)
    if key not in _candle_cache:
        raw = subprocess.run([KRAKEN, "ohlc", pair, "--interval", str(interval), "-o", "json"],
                             capture_output=True, text=True, check=True).stdout
        data = json.loads(raw)
        rows = next(v for k, v in data.items() if k != "last")
        # [t, open, high, low, close, vwap, volume, count] ; la dernière bougie est en cours
        _candle_cache[key] = [(r[0], float(r[1]), float(r[2]), float(r[3])) for r in rows[:-1]]
    return _candle_cache[key]


def pick_interval(entry_ts, resolution, now_ts):
    if resolution != "mixed":
        return int(resolution)
    age_days = (now_ts - entry_ts) / 86400
    if age_days <= 7:
        return 15
    if age_days <= 30:
        return 60
    return 240


def load_trades(since):
    with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
        history = json.load(f)
    since_ts = parse_ts(since + "T00:00:00+00:00")
    out = []
    for t in history:
        if t.get("status") != "closed" or not t.get("exit_price") or not t.get("exit_date"):
            continue
        if t.get("pnl_usdc") is None or parse_ts(t["date"]) < since_ts:
            continue
        out.append(t)
    return out


def replay_trade(t, trigger_pct, level_pct, resolution, now_ts):
    """Retourne dict(path, triggered, be_exit, pnl_be) pour un trade."""
    entry = float(t["entry_price"])
    qty = float(t["quantity"])
    e_ts, x_ts = parse_ts(t["date"]), parse_ts(t["exit_date"])
    interval = pick_interval(e_ts, resolution, now_ts)
    candles = [c for c in fetch_candles(f"{t['coin']}USDC", interval)
               if c[0] >= e_ts and c[0] + interval * 60 <= x_ts]
    trigger = entry * (1 + trigger_pct)
    level = entry * (1 + level_pct)
    mfe = max((c[2] for c in candles), default=entry) / entry - 1
    triggered_at = None
    for i, (_, o, h, lo) in enumerate(candles):
        if triggered_at is not None:
            if lo <= level or o <= level:
                exit_px = min(level, o)
                entry_cost = entry * qty * (1 + MAKER_FEE)
                pnl = exit_px * qty * (1 - TAKER_FEE) - entry_cost
                return {"triggered": True, "be_exit": True, "pnl_be": pnl, "mfe": mfe, "interval": interval}
        elif h >= trigger:
            triggered_at = i
    return {"triggered": triggered_at is not None, "be_exit": False, "pnl_be": None, "mfe": mfe,
            "interval": interval}


def run(trades, resolution):
    now_ts = datetime.now(timezone.utc).timestamp()
    real_pnl = sum(t["pnl_usdc"] for t in trades)
    real_stops = sum(1 for t in trades if t.get("close_reason") in ("sl_hit", "stop_hit", "sl"))
    real_losers = sum(1 for t in trades if t["pnl_usdc"] < 0)
    print(f"Trades : {len(trades)} | PnL réel net : {real_pnl:+.2f} USDC | stops réels : {real_stops} "
          f"| perdants : {real_losers}")
    mfes = [replay_trade(t, 9, 0, resolution, now_ts)["mfe"] for t in trades]
    print(f"MFE médiane sur la détention : {statistics.median(mfes) * 100:+.2f} % "
          f"(bougies fermées, résolution {resolution})")
    header = f"{'déclencheur':>11} {'niveau':>12} {'PnL net':>9} {'delta':>8} {'déclenchés':>10} " \
             f"{'sortis BE':>9} {'gagn->perd réel':>15} {'gagn->perd BE':>13} {'sauvés':>6} {'coupés':>6}"
    print(header)
    rows = []
    for lname, lpct in LEVELS:
        for trig in TRIGGERS:
            total = 0.0
            n_trig = n_be = ww_real = ww_be = saved = cut = 0
            for t in trades:
                r = replay_trade(t, trig, lpct, resolution, now_ts)
                pnl = t["pnl_usdc"]
                if r["triggered"]:
                    n_trig += 1
                    if pnl < 0:
                        ww_real += 1
                if r["be_exit"]:
                    n_be += 1
                    if r["pnl_be"] < 0:
                        ww_be += 1
                    if r["pnl_be"] > pnl:
                        saved += 1
                    elif r["pnl_be"] < pnl:
                        cut += 1
                    pnl = r["pnl_be"]
                elif r["triggered"] and pnl < 0:
                    ww_be += 1
                total += pnl
            rows.append((trig, lname, total))
            print(f"{trig * 100:>10.1f}% {lname:>12} {total:>+9.2f} {total - real_pnl:>+8.2f} {n_trig:>10} "
                  f"{n_be:>9} {ww_real:>15} {ww_be:>13} {saved:>6} {cut:>6}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-03")
    ap.add_argument("--resolution", default="240", choices=["240", "mixed"])
    args = ap.parse_args()
    trades = load_trades(args.since)
    print(f"== Rejeu break-even depuis {args.since}, résolution {args.resolution} ==")
    run(trades, args.resolution)


if __name__ == "__main__":
    main()
