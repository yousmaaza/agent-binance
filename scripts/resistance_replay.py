#!/usr/bin/env python3
"""Mesure (#516) : pivot R2 hebdomadaire vs plus haut des N bougies 4h clôturées, aux entrées de
state/trade_history.json. Lecture seule : seuls des `kraken ohlc` publics sont appelés.

Usage :
    .venv/bin/python scripts/resistance_replay.py [--since 2026-07-03] [--verify-eth]

Le R2 hebdo historique n'est pas récupérable via TradingView : il est recalculé depuis les bougies 4h
Kraken (semaine précédente, lundi 00:00 UTC) : P=(H+L+C)/3, R2=P+(H-L). Kraken ne renvoie que 720
bougies 4h (~120 jours).
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.env import KRAKEN_CLI_PATH  # noqa: E402
from core.trade_helpers import initial_stop_price  # noqa: E402

CANDLE = 4 * 3600
_cache: dict = {}


def candles(coin):
    if coin not in _cache:
        pair = f"{coin}USDC"
        r = subprocess.run([KRAKEN_CLI_PATH, "ohlc", pair, "--interval", "240", "-o", "json"],
                           capture_output=True, text=True, check=False)
        try:
            _cache[coin] = [[float(x) for x in c[:5]] for c in json.loads(r.stdout)[pair]]
        except (ValueError, KeyError):
            _cache[coin] = None
    return _cache[coin]


def weekly_r2(cs, ts):
    d = datetime.fromtimestamp(ts, timezone.utc)
    monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week = [c for c in cs if (monday - timedelta(days=7)).timestamp() <= c[0] < monday.timestamp()]
    if len(week) < 40:
        return None
    hi, lo, close = max(c[2] for c in week), min(c[3] for c in week), week[-1][4]
    return (hi + lo + close) / 3 + (hi - lo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-03")
    ap.add_argument("--verify-eth", action="store_true")
    args = ap.parse_args()
    cfg = json.load(open(os.path.join(PROJECT_DIR, "config.json")))
    fee, rr, mx = cfg["fee_round_trip_pct"], cfg["reward_risk_ratio"], cfg["max_tp_pct"]
    lookback = cfg.get("resistance_lookback_4h", 30)

    if args.verify_eth:
        for day in ("2026-09-28", "2026-10-05"):
            ts = datetime.fromisoformat(day + "T12:00:00+00:00").timestamp()
            print(day, weekly_r2(candles("ETH"), ts))
        return

    rows = []
    for t in json.load(open(os.path.join(PROJECT_DIR, "state", "trade_history.json"))):
        if t.get("side") != "BUY" or t["date"] < args.since:
            continue
        cs = candles(t["coin"])
        if not cs:
            continue
        ts = datetime.fromisoformat(t["date"]).timestamp()
        entry = float(t["entry_price"])
        sd = (entry - initial_stop_price(t, fee)) / entry
        closed = [c for c in cs if c[0] + CANDLE <= ts][-lookback:]
        r2 = weekly_r2(cs, ts)
        if len(closed) < lookback or r2 is None:
            continue
        rows.append({"entry": entry, "mec": entry * (1 + (sd + fee) * rr + fee),
                     "r2": r2, "r4": max(c[2] for c in closed)})

    n = len(rows)
    print(f"trades mesurés : {n}")
    for key in ("r2", "r4"):
        dist = [(r[key] / r["entry"] - 1) * 100 for r in rows if r[key] > r["entry"]]
        floor_ko = sum(1 for r in rows if r[key] * 0.98 < r["entry"] * (1 + 2 * fee))
        bite = sum(1 for r in rows if r[key] > r["entry"] and r[key] * 0.98 >= r["entry"] * (1 + 2 * fee)
                   and r[key] * 0.98 < min(r["mec"], r["entry"] * (1 + mx)))
        print(f"{key}: au-dessus de l'entrée {len(dist)}/{n}, distance médiane {statistics.median(dist):.2f} %, "
              f"mord {bite}/{n}, sous le plancher {floor_ko}/{n}")


if __name__ == "__main__":
    main()
