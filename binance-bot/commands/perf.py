"""Commande /perf — 4 blocs de KPIs : P&L, Cycles, Positions, TP Watcher."""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.env import PROJECT_DIR


def _load_history() -> list:
    try:
        with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
            return json.load(f)
    except Exception:
        return []


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # Handles "+00:00Z" (redundant Z suffix from tp_watcher_state)
        cleaned = raw.rstrip("Z") if raw.endswith("+00:00Z") else raw
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Bloc 1 — P&L réalisé
# ---------------------------------------------------------------------------

def _bloc_pnl(closed: list) -> list[str]:
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    def pnl(t):
        return t.get("pnl_usdc") or 0

    def exit_dt(t):
        return _parse_dt(t.get("exit_date"))

    total_pnl = sum(pnl(t) for t in closed)
    pnl_7d = sum(pnl(t) for t in closed if exit_dt(t) and exit_dt(t) >= cutoff_7d)
    pnl_30d = sum(pnl(t) for t in closed if exit_dt(t) and exit_dt(t) >= cutoff_30d)

    wins = [t for t in closed if pnl(t) > 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    best = max(closed, key=pnl) if closed else None
    worst = min(closed, key=pnl) if closed else None

    coin_pnl: dict[str, float] = {}
    for t in closed:
        c = t.get("coin", "?")
        coin_pnl[c] = coin_pnl.get(c, 0) + pnl(t)
    top_coins = sorted(coin_pnl.items(), key=lambda x: x[1], reverse=True)[:3]

    durations = []
    for t in closed:
        e = _parse_dt(t.get("date"))
        x = exit_dt(t)
        if e and x:
            durations.append((x - e).total_seconds())
    avg_h = (sum(durations) / len(durations) / 3600) if durations else 0
    hold_str = f"{avg_h / 24:.1f}j" if avg_h >= 24 else f"{avg_h:.1f}h"

    def trade_label(t):
        d = exit_dt(t)
        return f"{t.get('coin')} {pnl(t):+.2f} USDC ({d.strftime('%d/%m') if d else '?'})"

    lines = [f"\n📈 <b>Bloc 1 — P&amp;L réalisé ({len(closed)} trades fermés)</b>"]
    lines.append(
        f"Total : <code>{total_pnl:+.2f} USDC</code>"
        f"  |  7j : <code>{pnl_7d:+.2f}</code>"
        f"  |  30j : <code>{pnl_30d:+.2f}</code>"
    )
    lines.append(f"Win rate : <code>{win_rate:.1f}%</code>  ({len(wins)}W / {len(closed) - len(wins)}L)")
    if best:
        lines.append(f"Meilleur : <code>{trade_label(best)}</code>")
    if worst:
        lines.append(f"Pire     : <code>{trade_label(worst)}</code>")
    if top_coins:
        coins_str = "  ".join(f"{c}: {p:+.2f}" for c, p in top_coins)
        lines.append(f"Top coins : <code>{coins_str}</code>")
    lines.append(f"Durée moy. détention : <code>{hold_str}</code>")
    return lines


# ---------------------------------------------------------------------------
# Bloc 2 — Cycles
# ---------------------------------------------------------------------------

def _load_cycles_jsonl() -> list:
    try:
        cycles = []
        with open(f"{PROJECT_DIR}/state/cycle_log.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        cycles.append(json.loads(line))
                    except Exception:
                        pass
        return cycles
    except Exception:
        return []


def _bloc_cycles() -> list[str]:
    lines = ["\n🔄 <b>Bloc 2 — Cycles</b>"]

    mongo_rows = None
    try:
        from storage.mongo import mongo_repo  # noqa: PLC0415
        db = mongo_repo._db()
        if db is not None:
            mongo_rows = list(db.cycles.find({}, {
                "execution": 1, "decisions": 1,
                "duration_s": 1, "error_type": 1,
            }))
    except Exception:
        pass

    if mongo_rows is not None:
        total = len(mongo_rows)
        with_buy = sum(
            1 for c in mongo_rows
            if (c.get("execution") or {}).get("executed", 0) > 0
        )
        skip_counts = {"TYPE_A": 0, "TYPE_B": 0, "TYPE_C": 0, "TYPE_D": 0}
        for c in mongo_rows:
            for d in (c.get("decisions") or []):
                st = d.get("skip_type")
                if st in skip_counts:
                    skip_counts[st] += 1
        durations = [c["duration_s"] for c in mongo_rows if c.get("duration_s") is not None]
        avg_dur = sum(durations) / len(durations) if durations else None
        errors = sum(1 for c in mongo_rows if c.get("error_type") is not None)
        quota = sum(1 for c in mongo_rows if c.get("error_type") == "quota")

        lines.append(
            f"Total : <code>{total}</code>"
            f"  |  Avec BUY : <code>{with_buy}</code>"
            f"  |  Sans trade : <code>{total - with_buy}</code>"
        )
        skip_str = "  ".join(f"{k}: {v}" for k, v in skip_counts.items())
        lines.append(f"Skips : <code>{skip_str}</code>")
        if avg_dur is not None:
            lines.append(f"Durée moy. : <code>{avg_dur:.0f}s</code>")
        lines.append(f"Erreurs : <code>{errors}</code>  |  Quota Claude : <code>{quota}</code>")
        lines.append("(source : Mongo)")
    else:
        cycles = _load_cycles_jsonl()
        total = len(cycles)
        with_buy = sum(1 for c in cycles if c.get("executed", 0) > 0)
        skip_counts = {"TYPE_A": 0, "TYPE_B": 0, "TYPE_C": 0, "TYPE_D": 0}
        for c in cycles:
            st = c.get("skip_type")
            if st in skip_counts:
                skip_counts[st] += 1
        lines.append(
            f"Total : <code>{total}</code>"
            f"  |  Avec BUY : <code>{with_buy}</code>"
            f"  |  Sans trade : <code>{total - with_buy}</code>"
        )
        skip_str = "  ".join(f"{k}: {v}" for k, v in skip_counts.items())
        lines.append(f"Skips : <code>{skip_str}</code>")
        lines.append("(source : cycle_log.jsonl — duration_s/erreurs non disponibles)")

    return lines


# ---------------------------------------------------------------------------
# Bloc 3 — Positions
# ---------------------------------------------------------------------------

def _bloc_positions(history: list) -> list[str]:
    open_trades = [t for t in history if t.get("status") == "open"]
    closed = [t for t in history if t.get("status") == "closed"]

    sl_hits = sum(
        1 for t in closed
        if t.get("close_reason") in ("sl_hit", "stop_hit", "sl")
    )
    tp_watcher_hits = sum(
        1 for t in closed
        if "tp_watcher" in (t.get("close_reason") or "")
    )
    profit_phase0 = sum(
        1 for t in closed
        if t.get("close_reason") == "profit_target_phase0"
    )

    # Consecutive streak from the end of sorted closed trades
    sorted_closed = sorted(
        [t for t in closed if t.get("exit_date")],
        key=lambda t: t.get("exit_date", ""),
    )
    streak = 0
    streak_type: Optional[str] = None
    for t in reversed(sorted_closed):
        win = (t.get("pnl_usdc") or 0) > 0
        cur = "W" if win else "L"
        if streak_type is None:
            streak_type = cur
            streak = 1
        elif streak_type == cur:
            streak += 1
        else:
            break

    streak_str = f"{streak}{streak_type}" if streak_type else "–"

    lines = ["\n📊 <b>Bloc 3 — Positions</b>"]
    lines.append(
        f"Ouvertes : <code>{len(open_trades)}</code>"
        f"  |  Fermées : <code>{len(closed)}</code>"
    )
    lines.append(
        f"Par SL : <code>{sl_hits}</code>"
        f"  |  Par TP Watcher : <code>{tp_watcher_hits}</code>"
        f"  |  Profit Phase 0 : <code>{profit_phase0}</code>"
    )
    lines.append(f"Série en cours : <code>{streak_str}</code>")
    return lines


# ---------------------------------------------------------------------------
# Bloc 4 — TP Watcher
# ---------------------------------------------------------------------------

def _bloc_watcher(closed: list) -> list[str]:
    state_path = f"{PROJECT_DIR}/state/tp_watcher_state.json"
    try:
        with open(state_path) as f:
            state = json.load(f)
    except FileNotFoundError:
        return ["\n🤖 <b>Bloc 4 — TP Watcher</b> : ⚠️ État inconnu"]
    except Exception:
        return ["\n🤖 <b>Bloc 4 — TP Watcher</b> : ⚠️ État inconnu"]

    total_ticks = state.get("total_ticks", "N/A")
    total_sales = state.get("total_sales", "N/A")

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    tp_trades = [t for t in closed if "tp_watcher" in (t.get("close_reason") or "")]

    def in_period(t, cutoff):
        dt = _parse_dt(t.get("exit_date"))
        return dt is not None and dt >= cutoff

    sales_24h = sum(1 for t in tp_trades if in_period(t, cutoff_24h))
    sales_7d = sum(1 for t in tp_trades if in_period(t, cutoff_7d))
    usdc_watcher = sum(t.get("pnl_usdc") or 0 for t in tp_trades)

    lines = ["\n🤖 <b>Bloc 4 — TP Watcher</b>"]
    lines.append(
        f"Ticks total : <code>{total_ticks}</code>"
        f"  |  Ventes total : <code>{total_sales}</code>"
    )
    lines.append(
        f"Ventes TP (24h) : <code>{sales_24h}</code>"
        f"  |  Ventes TP (7j) : <code>{sales_7d}</code>"
    )
    lines.append(f"USDC réalisés via watcher : <code>{usdc_watcher:+.2f}</code>")
    return lines


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def run_perf() -> str:
    history = _load_history()
    if not history:
        return "❌ Pas encore de données de trading."

    closed = [t for t in history if t.get("status") == "closed"]

    lines = ["📈 <b>Performance du bot</b>\n"]

    if closed:
        lines.extend(_bloc_pnl(closed))
    else:
        lines.append("\n📈 <b>Bloc 1 — P&amp;L réalisé</b> : aucun trade fermé")

    lines.extend(_bloc_cycles())
    lines.extend(_bloc_positions(history))
    lines.extend(_bloc_watcher(closed))

    msg = "\n".join(lines)

    # Telegram 4096 chars limit
    if len(msg) > 4000:
        msg = msg[:3970] + "\n\n⚠️ <i>(message tronqué)</i>"

    return msg
