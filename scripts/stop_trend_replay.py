#!/usr/bin/env python3
"""Rejeu (#521) : stop de départ ATR 2,5x vs stop fixe -20 %, filtre de tendance de fond (coin ET BTC
au-dessus de l'EMA100 1d) et palier intermédiaire (grille X x Y). Lecture seule.

Usage :
    .venv/bin/python scripts/stop_trend_replay.py --fetch --data /chemin/data   # télécharge les bougies
    .venv/bin/python scripts/stop_trend_replay.py --data /chemin/data            # rejoue (Binance puis Kraken)
    .venv/bin/python scripts/stop_trend_replay.py --data /chemin/data --source kraken

Approximation du bot sur des bougies (pas un clone exact) :
- signal calculé sur la bougie 4h clôturée i, exécution à l'ouverture de i+1 ; entrée maker 0,30 % ;
  sortie sur stop taker 0,60 % + 0,05 % de glissement (ouverture si gap) ; cible / partiel / signal = maker 0,30 % ;
  stop et cible dans la même bougie -> stop d'abord ;
- entrée : EMA20 > EMA50, MACD > signal, RSI 4h dans [30, 65], hausse 24h < 4 % ; max 4 positions ;
- stop ATR 2,5x (plafonné à 12 %) ou fixe ; dimensionnement à 2 % de risque : montant = 2 % x equity /
  (distance de stop + 0,9 %), plafonné à 65 % de l'equity ; ordre minimum 9 USDC ;
- cible = compute_tp_target (RR 1,5 net de frais, plafond +6 %, résistance = plus haut de 30 bougies 4h
  x 0,98, plancher entry x (1 + 2 x frais)) ; partiel 1/3 à +3 % ; break-even à +1,5 % (stop = entry x 1,009,
  actif à la bougie suivante) ; stop suiveur du bot (distance d'origine) ; vente sur signal approximée par
  MACD < signal ET clôture < EMA20 si cours > entrée ; détention max 14 j ;
- filtre de tendance : clôture 1d du coin ET de BTC > EMA100 1d, dernière bougie 1d CLÔTURÉE seulement ;
- palier (X, Y) : si la bougie touche entry x (1 - X) puis qu'une bougie suivante revient au prix d'entrée,
  le stop passe de -20 % à entry x (1 - Y) (effectif à la bougie suivante), avant le break-even.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

COINS = ["BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX"]
H4, D1 = 14400000, 86400000
MAKER, TAKER, SLIP = 0.003, 0.006, 0.0005
MIN_ORDER, CAPITAL, FEE = 9.0, 380.0, 0.009
NAN = float("nan")


# ---------------------------------------------------------------- données
def fetch(data_dir):
    """Binance (USDT) 1d/4h depuis 2021-05 (chauffe des EMA) + OHLC Kraken (USDC, 720 bougies)."""
    os.makedirs(data_dir, exist_ok=True)
    iv_ms = {"1d": D1, "4h": H4}
    for c in COINS:
        for iv in ("1d", "4h"):
            out, t = [], 1619827200000
            while True:
                url = f"https://api.binance.com/api/v3/klines?symbol={c}USDT&interval={iv}&limit=1000&startTime={t}"
                r = json.loads(subprocess.check_output(["curl", "-s", url]))
                if not r:
                    break
                out += [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in r]
                t = r[-1][0] + iv_ms[iv]
                if len(r) < 1000:
                    break
                time.sleep(0.2)
            now = int(time.time() * 1000)
            json.dump([k for k in out if k[0] + iv_ms[iv] <= now], open(f"{data_dir}/binance_{c}_{iv}.json", "w"))
        for iv, m in (("1d", 1440), ("4h", 240)):
            raw = subprocess.run([os.path.expanduser("~/.cargo/bin/kraken"), "ohlc", f"{c}USDC", "--interval", str(m),
                                  "-o", "json"], capture_output=True, text=True, check=False)
            open(f"{data_dir}/kraken_{c}_{iv}.raw.json", "w").write(raw.stdout)
        print("fetched", c, file=sys.stderr)


def load(data_dir, src, coin, iv):
    if src == "binance":
        return json.load(open(f"{data_dir}/binance_{coin}_{iv}.json"))
    raw = json.load(open(f"{data_dir}/kraken_{coin}_{iv}.raw.json"))
    key = [k for k in raw if k != "last"][0]
    step = H4 if iv == "4h" else D1
    now = int(time.time() * 1000)
    out = [[int(r[0]) * 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])] for r in raw[key]]
    return [k for k in out if k[0] + step <= now]


class Series:
    """Bougies alignées sur une grille commune ; un trou devient une bougie plate invalide."""

    def __init__(self, kl, grid):
        m = {k[0]: k for k in kl}
        self.o, self.h, self.l, self.c, self.valid = [], [], [], [], []
        last = NAN
        for t in grid:
            k = m.get(t)
            if k is None:
                self.o.append(last); self.h.append(last); self.l.append(last); self.c.append(last); self.valid.append(False)
            else:
                self.o.append(k[1]); self.h.append(k[2]); self.l.append(k[3]); self.c.append(k[4]); self.valid.append(True)
                last = k[4]


def make_grid(kls, step):
    ts = sorted(set(k[0] for kl in kls for k in kl))
    return list(range(ts[0], ts[-1] + 1, step))


class Market:
    def __init__(self, data_dir, src):
        dk = {c: load(data_dir, src, c, "1d") for c in COINS}
        self.dgrid = make_grid(dk.values(), D1)
        self.D = {c: Series(dk[c], self.dgrid) for c in COINS}
        k4 = {c: load(data_dir, src, c, "4h") for c in COINS}
        self.grid = make_grid(k4.values(), H4)
        self.S = {c: Series(k4[c], self.grid) for c in COINS}
        dpos = {t: j for j, t in enumerate(self.dgrid)}
        # dernière bougie 1d CLÔTURÉE à la clôture de la bougie 4h i (la bougie en cours est exclue)
        self.di = [dpos.get(((t + H4) // D1) * D1 - D1, -1) for t in self.grid]


# ---------------------------------------------------------------- indicateurs
def ema(x, n):
    a, out, e = 2 / (n + 1), [], None
    for v in x:
        if v != v:
            out.append(e if e is not None else NAN)
            continue
        e = v if e is None else e + a * (v - e)
        out.append(e)
    for i in range(min(n, len(out))):
        out[i] = NAN
    return out


def rsi(c, n=14):
    out, ag, al = [NAN] * len(c), None, None
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        g, ls = max(d, 0), max(-d, 0)
        if i <= n:
            ag = (ag or 0) + g / n; al = (al or 0) + ls / n
            if i == n:
                out[i] = 100 - 100 / (1 + ag / al) if al else 100
        else:
            ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + ls) / n
            out[i] = 100 - 100 / (1 + ag / al) if al else 100
    return out


def atr(h, l, c, n=14):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    out, a = [NAN] * len(c), None
    for i, v in enumerate(tr):
        if i < n - 1:
            continue
        a = sum(tr[:n]) / n if i == n - 1 else (a * (n - 1) + v) / n
        out[i] = a
    return out


def macd(c):
    m = [a - b if a == a and b == b else NAN for a, b in zip(ema(c, 12), ema(c, 26))]
    first = next(i for i, v in enumerate(m) if v == v)
    return m, [NAN] * first + ema(m[first:], 9)


def rolling_max(x, n):
    return [max(x[i - n:i]) if i >= n else NAN for i in range(len(x))]


def isnan(x):
    return x != x


# ---------------------------------------------------------------- stratégie
class Bot:
    """fixed=None : stop ATR (atr_k x ATR14 4h, plafonné à `cap`) ; fixed=0.20 : stop fixe -20 %.
    trend : filtre EMA100 1d coin ET BTC. tier=(X, Y) : palier intermédiaire."""
    max_pos = 4

    def __init__(self, mk, fixed=None, cap=0.12, atr_k=2.5, trend=False, tier=None, risk=0.02, trend_n=100):
        self.mk, self.fixed, self.cap, self.k, self.trend, self.tier = mk, fixed, cap, atr_k, trend, tier
        self.risk, self.trend_n = risk, trend_n
        self.ind = {}
        for c in COINS:
            s = mk.S[c]
            m, sg = macd(s.c)
            self.ind[c] = dict(e20=ema(s.c, 20), e50=ema(s.c, 50), m=m, sg=sg, r=rsi(s.c), a=atr(s.h, s.l, s.c),
                               hh=rolling_max(s.h, 30))
        self.de = {c: ema(mk.D[c].c, trend_n) for c in COINS}

    def trend_ok(self, c, d):
        if d < 0:
            return False
        for cc in (c, "BTC"):
            e = self.de[cc][d]
            if isnan(e) or self.mk.D[cc].c[d] <= e:
                return False
        return True

    def entry(self, c, i):
        x, s = self.ind[c], self.mk.S[c]
        if i < 6 or any(isnan(x[k][i]) for k in ("e50", "sg", "r", "a")):
            return None
        ch24 = s.c[i] / s.c[i - 6] - 1
        if not (x["e20"][i] > x["e50"][i] and x["m"][i] > x["sg"][i] and 30 <= x["r"][i] <= 65 and ch24 < 0.04):
            return None
        if self.trend and not self.trend_ok(c, self.mk.di[i]):
            return None
        px = s.c[i]
        sd = self.fixed if self.fixed else min(self.k * x["a"][i] / px, self.cap)
        tp = min((sd + FEE) * 1.5 + FEE, 0.06)
        if not isnan(x["hh"][i]) and x["hh"][i] > px:
            if x["hh"][i] * 0.98 < px * (1 + 2 * FEE):
                tp = 2 * FEE
            else:
                tr = min(tp, x["hh"][i] * 0.98 / px - 1)
                if tr >= 2 * FEE:
                    tp = tr
        return dict(sd=sd, tp=tp, rank=ch24)

    def size(self, equity, info):
        return min(equity * self.risk / (info["sd"] + FEE), equity * 0.65)

    def exit_signal(self, c, i, p):
        x, s = self.ind[c], self.mk.S[c]
        if i - p["i"] >= 14 * 6:
            return True
        return x["m"][i] < x["sg"][i] and s.c[i] < x["e20"][i] and s.c[i] > p["entry"]

    def trail(self, c, i, p):
        px = self.mk.S[c].c[i]
        new = px - p["d"]
        if new > p["stop"] + p["d"] * 0.2 and new < px * 0.98:
            p["stop"] = new


def run(bot, start_t):
    mk, S, grid = bot.mk, bot.mk.S, bot.mk.grid
    i0 = next(i for i, t in enumerate(grid) if t >= start_t)
    i1 = len(grid) - 1
    cash, pos, trades = CAPITAL, {}, []
    eq_t, eq_v = [], []
    pend_exit, pend_entry = set(), []

    def close(c, qty, px, rate, full, t, reason):
        nonlocal cash
        p = pos[c]
        val = qty * px
        fee = val * rate
        cash += val - fee
        p["fees"] += fee
        p["proceeds"] += val - fee
        p["qty"] -= qty
        if full:
            trades.append(dict(pnl=p["proceeds"] - p["cost"], reason=reason, fees=p["fees"], exit_t=t))
            del pos[c]

    for i in range(i0, i1 + 1):
        t = grid[i]
        for c in list(pend_exit):
            if c in pos and S[c].valid[i]:
                close(c, pos[c]["qty"], S[c].o[i], MAKER, True, t, "signal")
        pend_exit = set()
        if pend_entry:
            eq_open = cash + sum(p["qty"] * S[c].o[i] for c, p in pos.items())
            for c, info in pend_entry:
                if c in pos or len(pos) >= bot.max_pos or not S[c].valid[i]:
                    continue
                notional = min(bot.size(eq_open, info), cash)
                if notional < MIN_ORDER:
                    continue
                px = S[c].o[i]
                qty = notional / (px * (1 + MAKER))
                cash -= notional
                pos[c] = dict(qty=qty, qty0=qty, entry=px, cost=notional, fees=qty * px * MAKER, proceeds=0.0, i=i,
                              d=info["sd"] * px, stop=px * (1 - info["sd"]), target=px * (1 + info["tp"]),
                              partial=px * 1.03 if info["tp"] > 0.03 else None, pdone=False, be=False,
                              armed=False, tier_done=False)
        pend_entry = []
        for c in list(pos):
            s, p = S[c], pos[c]
            if not s.valid[i]:
                continue
            o, h, lo = s.o[i], s.h[i], s.l[i]
            if lo <= p["stop"]:
                close(c, p["qty"], min(o, p["stop"]) * (1 - SLIP), TAKER, True, t, "stop")
                continue
            if p["partial"] and not p["pdone"] and h >= p["partial"]:
                close(c, p["qty0"] / 3, max(o, p["partial"]), MAKER, False, t, "partial")
                p["pdone"] = True
            if h >= p["target"]:
                close(c, p["qty"], max(o, p["target"]), MAKER, True, t, "target")
                continue
            if bot.tier and not p["tier_done"]:
                if p["armed"] and h >= p["entry"]:
                    p["stop"] = max(p["stop"], p["entry"] * (1 - bot.tier[1]))
                    p["tier_done"] = True
                if lo <= p["entry"] * (1 - bot.tier[0]):
                    p["armed"] = True
            if not p["be"] and h >= p["entry"] * 1.015:
                p["stop"] = max(p["stop"], p["entry"] * 1.009)
                p["be"] = True
        inv = sum(p["qty"] * S[c].c[i] for c, p in pos.items())
        eq_t.append(t)
        eq_v.append(cash + inv)
        if i == i1:
            break
        for c in list(pos):
            if S[c].valid[i]:
                bot.trail(c, i, pos[c])
                if bot.exit_signal(c, i, pos[c]):
                    pend_exit.add(c)
        cands = []
        for c in S:
            if c not in pos and S[c].valid[i]:
                info = bot.entry(c, i)
                if info:
                    cands.append((info["rank"], c, info))
        cands.sort(key=lambda x: x[0])
        pend_entry = [(c, info) for _, c, info in cands]
    return eq_t, eq_v, trades


def metrics(res, t_from):
    et, ev, trades = res
    idx = [k for k, t in enumerate(et) if t >= t_from]
    a = idx[0]
    start = ev[a - 1] if a > 0 else CAPITAL
    v = [start] + ev[a:]
    pk, dd = -1e18, 0.0
    for x in v:
        pk = max(pk, x)
        dd = min(dd, x / pk - 1)
    n = sum(1 for tr in trades if tr["exit_t"] >= t_from)
    return (v[-1] / start - 1) * 100, dd * 100, n


def ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


WINDOWS = {
    "binance": [("2022->", "2022-01-01"), ("2024->", "2024-01-01"), ("2025->", "2025-01-01"),
                ("12 mois", "2025-10-08"), ("3 mois", "2026-07-08")],
    "kraken": [("120 j (720 bougies)", None), ("3 mois", "2026-07-08")],
}
CONFIGS = ([("reglage actuel (ATR 2,5x, plafond 12 %)", dict()),
            ("stop -20 % seul", dict(fixed=0.20)),
            ("filtre seul (stop ATR)", dict(trend=True)),
            ("stop -20 % + filtre", dict(fixed=0.20, trend=True))]
           + [(f"  + palier X={x} % Y={y} %", dict(fixed=0.20, trend=True, tier=(x / 100, y / 100)))
              for x in (2, 3, 5) for y in (3, 5, 8)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--source", choices=["binance", "kraken", "both"], default="both")
    ap.add_argument("--json", help="écrit les résultats bruts dans ce fichier")
    args = ap.parse_args()
    if args.fetch:
        fetch(args.data)
    raw = {}
    for src in (["binance", "kraken"] if args.source == "both" else [args.source]):
        mk = Market(args.data, src)
        wins = [(w, ts(d) if d else mk.grid[0] + 60 * H4) for w, d in WINDOWS[src]]
        print(f"\n### Source {src} - risque 2 % par trade, capital {CAPITAL:.0f} USDC\n")
        print("| config | " + " | ".join(w for w, _ in wins) + " |")
        print("|---|" + "---|" * len(wins))
        for name, kw in CONFIGS:
            cells, raw[f"{src}|{name}"] = [], {}
            for w, t in wins:
                r, dd, n = metrics(run(Bot(mk, **kw), t), t)
                raw[f"{src}|{name}"][w] = dict(ret=r, mdd=dd, n=n)
                cells.append(f"{r:+.1f} % (DD {dd:.0f} %, n={n})")
            print(f"| {name} | " + " | ".join(cells) + " |")
    if args.json:
        json.dump(raw, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
