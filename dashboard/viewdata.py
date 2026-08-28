"""Mise en forme des documents Mongo bruts en structures prêtes pour les templates (#432).

Séparé des routes Flask pour rester testable sans client HTTP : chaque fonction prend des
dicts déjà lus (dashboard_state, cycles) et retourne des dicts/valeurs simples."""
from datetime import datetime, timezone
from typing import Optional

from timeutil import parse_iso, to_local

PERIOD_LABELS = {"0_7d": "0-7 jours", "8_30d": "8-30 jours", "30d_plus": "Au-delà de 30 jours"}


def resolve_timezone(dashboard_state: dict, default_tz: str) -> str:
    return (dashboard_state.get("config") or {}).get("display_timezone") or default_tz


def freshness(dashboard_state: dict, stale_threshold_minutes: int, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    updated_at = parse_iso(dashboard_state.get("updated_at"))
    age_min = (now - updated_at).total_seconds() / 60 if updated_at else None
    return {
        "updated_at": updated_at,
        "age_minutes": age_min,
        "is_stale": age_min is None or age_min > stale_threshold_minutes,
        "cycle_status": dashboard_state.get("cycle_status"),
        "cycle_id": dashboard_state.get("cycle_id"),
    }


def equity_curve_points(curve: list, width: int = 300, height: int = 80, pad: int = 4) -> str:
    if not curve:
        return ""
    values = [p.get("cumulative_pnl_usdc", 0) for p in curve]
    n = len(values)
    vmin, vmax = min(values), max(values)
    vrange = (vmax - vmin) or 1.0
    x_step = (width - 2 * pad) / (n - 1) if n > 1 else 0
    points = []
    for i, v in enumerate(values):
        x = pad + i * x_step
        y = height - pad - (v - vmin) / vrange * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def build_position_row(pos: dict, price: Optional[float]) -> dict:
    entry = pos.get("entry_price")
    stop = pos.get("stop_price")
    tp = pos.get("tp_price")

    dist_stop_pct = (price - stop) / price * 100 if price and stop is not None else None
    dist_tp_pct = (tp - price) / price * 100 if price and tp is not None else None
    pnl_pct = (price - entry) / entry * 100 if price and entry else None

    return {
        **pos,
        "current_price": price,
        "distance_to_stop_pct": dist_stop_pct,
        "distance_to_target_pct": dist_tp_pct,
        "unrealized_pnl_pct": pnl_pct,
    }


def build_positions(open_positions: list, prices: dict) -> list:
    return [build_position_row(p, prices.get(p.get("coin"))) for p in open_positions]


def build_periods_table(by_period: dict) -> list:
    return [
        {"key": key, "label": PERIOD_LABELS.get(key, key), **(by_period.get(key) or {})}
        for key in ("0_7d", "8_30d", "30d_plus")
    ]


def build_maker_summary(watchers: dict) -> dict:
    mw = watchers.get("maker_watcher") or {}
    fills = mw.get("total_fills", 0) or 0
    fallbacks = mw.get("total_fallbacks", 0) or 0
    abandoned = mw.get("total_abandoned", 0) or 0
    total = fills + fallbacks + abandoned
    pending = watchers.get("maker_pending_orders") or []
    capital_immobilise = sum(
        float(o.get("quantity", 0) or 0) * float(o.get("current_limit_price") or o.get("initial_limit_price") or 0)
        for o in pending
    )
    return {
        "fills": fills,
        "fallbacks": fallbacks,
        "abandoned": abandoned,
        "total": total,
        "fill_pct": round(fills / total * 100) if total else None,
        "pending_count": len(pending),
        "capital_immobilise": capital_immobilise,
    }


def build_cycle_row(cycle: dict, tz_name: str) -> dict:
    dt = parse_iso(cycle.get("timestamp"))
    execution = cycle.get("execution") or {}
    return {
        "cycle_id": cycle.get("cycle_id"),
        "local_time": to_local(dt, tz_name) if dt else "n/d",
        "status": cycle.get("status"),
        "error_type": cycle.get("error_type"),
        "top_score": cycle.get("top_score", 0),
        "executed": execution.get("executed", cycle.get("executed", 0)),
        "pending": execution.get("pending", cycle.get("pending", 0)),
        "skipped": execution.get("skipped", cycle.get("skipped", 0)),
        "explanation_fr": cycle.get("explanation_fr") or "",
        "decisions": cycle.get("decisions") or [],
        "has_action": (execution.get("executed", cycle.get("executed", 0)) or 0) > 0
        or (execution.get("pending", cycle.get("pending", 0)) or 0) > 0,
    }


def build_cadence_band(cycles: list) -> list:
    """Un trait par cycle (ordre chronologique), hauteur = score/10, coloré seulement si action."""
    ordered = list(reversed(cycles))  # cycles arrivent triés desc (le plus récent d'abord)
    band = []
    for c in ordered:
        row = build_cycle_row(c, tz_name="UTC")
        band.append({
            "cycle_id": row["cycle_id"],
            "height_pct": max(4, round((row["top_score"] or 0) / 10 * 100)),
            "has_action": row["has_action"],
            "status": row["status"],
        })
    return band
