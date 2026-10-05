#!/usr/bin/env python3
"""Mesure (#516) : pivot R2 hebdomadaire vs plus haut des N bougies 4h clôturées, aux entrées de
state/trade_history.json. Lecture seule : seuls des `kraken ohlc` publics sont appelés.

Usage :
    .venv/bin/python scripts/resistance_replay.py [--since 2026-07-03] [--verify-eth]

Imprime aussi la grille N = 30/60/90/180 (sous-ensemble commun inclus) et l'atteinte de la cible.

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
from core.trade_helpers import compute_tp_target, initial_stop_price  # noqa: E402

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

    grid = [30, 60, 90, 180]
    rows = []
    for t in json.load(open(os.path.join(PROJECT_DIR, "state", "trade_history.json"))):
        if t.get("side") != "BUY" or t["date"] < args.since:
            continue
        cs = candles(t["coin"])
        if not cs:
            continue
        ts = datetime.fromisoformat(t["date"]).timestamp()
        exit_ts = datetime.fromisoformat(t["exit_date"].replace("+00:00Z", "+00:00")).timestamp() if t.get("exit_date") else float("inf")
        entry = float(t["entry_price"])
        stop = initial_stop_price(t, fee)
        sd = (entry - stop) / entry
        before = [c for c in cs if c[0] + CANDLE <= ts]
        path = [c for c in cs if ts <= c[0] and c[0] < exit_ts]  # bougies démarrant après l'entrée
        rows.append({"entry": entry, "stop": stop, "sd": sd, "path": path, "before": before,
                     "r2": weekly_r2(cs, ts), "hold_h": (min(exit_ts, cs[-1][0] + CANDLE) - ts) / 3600})

    def target(r, n):
        e = r["entry"]
        res = max(c[2] for c in r["before"][-n:])
        return res, compute_tp_target(e, r["sd"], rr, fee, mx, res)

    def outcome(r, tp):
        for c in r["path"]:
            if c[3] <= r["stop"]:
                return "stop"
            if c[2] >= tp:
                return "hit"
        return "none"

    def report(label, subset, ns):
        print(f"\n{label} : {len(subset)} trades, durée de détention médiane "
              f"{statistics.median(r['hold_h'] for r in subset):.0f} h")
        base = {id(r): outcome(r, target(r, lookback)[1]) for r in subset}
        for n in ns:
            vals = [target(r, n) for r in subset]
            above = [(res / r["entry"] - 1) * 100 for r, (res, _) in zip(subset, vals) if res > r["entry"]]
            fl = lambda r: r["entry"] * (1 + 2 * fee)  # noqa: E731
            bite = sum(1 for r, (res, tp) in zip(subset, vals)
                       if res > r["entry"] and res * 0.98 >= fl(r) and res * 0.98 < min(
                           r["entry"] * (1 + (r["sd"] + fee) * rr + fee), r["entry"] * (1 + mx)))
            ign = sum(1 for r, (res, _) in zip(subset, vals) if res * 0.98 < fl(r))
            tps = [(tp / r["entry"] - 1) * 100 for r, (_, tp) in zip(subset, vals)]
            out = [outcome(r, tp) for r, (_, tp) in zip(subset, vals)]
            print(f"N={n:3d}: au-dessus {len(above)}/{len(subset)} dist méd {statistics.median(above):.2f} % | "
                  f"mord {bite} ignorée {ign} | cible méd {statistics.median(tps):.2f} % moy {statistics.mean(tps):.2f} % | "
                  f"atteinte {out.count('hit')} stop avant {out.count('stop')} ni l'un ni l'autre {out.count('none')}")

    report("Tous les trades (N=180 sur ceux qui ont assez d'historique)", rows, grid[:3])
    common = [r for r in rows if len(r["before"]) >= max(grid)]
    report("Sous-ensemble commun (>= 180 bougies avant l'entrée)", common, grid)
    print(f"\nN=180 exclut {len(rows) - len(common)} trades (historique Kraken insuffisant).")


if __name__ == "__main__":
    main()
