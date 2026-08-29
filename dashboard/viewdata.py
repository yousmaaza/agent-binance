"""Mise en forme des documents Mongo bruts en structures prêtes pour les templates (#432).

Séparé des routes Flask pour rester testable sans client HTTP : chaque fonction prend des
dicts déjà lus (dashboard_state, cycles) et retourne des dicts/valeurs simples."""
from datetime import datetime, timezone

from timeutil import parse_iso, to_local

NARROW_NBSP = "\u202f"  # séparateur de milliers français, comme &#8239; dans la maquette

PERIOD_LABELS = {"0_7d": "0-7 jours", "8_30d": "8-30 jours", "30d_plus": "Au-delà de 30 jours"}


def format_price(value) -> str:
    """Prix lisible : Kraken renvoie la flottante brute (706.4407567166553, 0.0976048000007315),
    illisible dans une colonne (#442). Deux décimales au-dessus de 1, six en dessous, zéros
    de queue retirés — on ne connaît pas le tick_size de la paire côté dashboard."""
    if value is None:
        return "n/d"
    v = float(value)
    if abs(v) >= 1:
        return f"{v:,.2f}".replace(",", NARROW_NBSP)
    trimmed = f"{v:.6f}".rstrip("0").rstrip(".")
    return trimmed or "0"


def resolve_timezone(dashboard_state: dict, default_tz: str) -> str:
    return (dashboard_state.get("config") or {}).get("display_timezone") or default_tz


def freshness(dashboard_state: dict, stale_threshold_minutes: int, now: datetime | None = None) -> dict:
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


def equity_curve_geometry(curve: list, width: int = 640, height: int = 150, pad: int = 8) -> dict:
    """Courbe + aire remplie + ligne du zéro (#442) : la maquette dessine les trois, et le
    polygone d'aire ne se construit pas depuis la seule polyline côté gabarit."""
    polyline = equity_curve_points(curve, width=width, height=height, pad=pad)
    if not polyline:
        return {}

    values = [p.get("cumulative_pnl_usdc", 0) for p in curve]
    vmin, vmax = min(values), max(values)
    vrange = (vmax - vmin) or 1.0
    zero_y = height - pad - (0 - vmin) / vrange * (height - 2 * pad)
    zero_y = min(max(zero_y, pad), height - pad)

    pairs = polyline.split(" ")
    first_x = pairs[0].split(",")[0]
    last_x = pairs[-1].split(",")[0]
    polygon = f"{first_x},{zero_y:.1f} {polyline} {last_x},{zero_y:.1f}"

    return {
        "polyline": polyline,
        "polygon": polygon,
        "zero_y": round(zero_y, 1),
        "final_value": values[-1],
        "width": width,
        "height": height,
        "pad": pad,
    }


def position_age(opened_at, now: datetime | None = None) -> str | None:
    """Âge de la position, comme dans la maquette (« 6 j »). None si la date d'ouverture manque."""
    dt = parse_iso(opened_at) if isinstance(opened_at, str) else opened_at
    if not dt:
        return None
    delta = (now or datetime.now(timezone.utc)) - dt
    hours = delta.total_seconds() / 3600
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.0f} j"


def build_position_row(pos: dict, price: float | None, now: datetime | None = None) -> dict:
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
        "age_label": position_age(pos.get("opened_at"), now),
        **_track_geometry(entry, stop, tp, price),
    }


def _track_geometry(entry, stop, tp, price) -> dict:
    """Position du prix et du point d'entrée sur la piste stop → cible, en % (#442).
    Rien à afficher tant que la piste n'a pas de largeur (stop == cible) ou que le prix manque."""
    span = (tp - stop) if (tp is not None and stop is not None) else None
    if not span:
        return {"track_now_pct": None, "track_entry_pct": None}

    def clamp(v):
        return min(100.0, max(0.0, v))

    return {
        "track_now_pct": clamp((price - stop) / span * 100) if price is not None else None,
        "track_entry_pct": clamp((entry - stop) / span * 100) if entry is not None else None,
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


CADENCE_VIEWBOX_WIDTH = 900
CADENCE_VIEWBOX_HEIGHT = 64
CADENCE_SCORE_THRESHOLD = 6  # seuil de déclenchement d'un achat, tracé en pointillés


def build_cadence_band(cycles: list) -> list:
    """Un trait par cycle (ordre chronologique), hauteur = score/10, coloré seulement si action.
    Porte aussi sa géométrie SVG (#442) : le gabarit ne peut pas la calculer proprement."""
    ordered = list(reversed(cycles))  # cycles arrivent triés desc (le plus récent d'abord)
    n = len(ordered) or 1
    step = CADENCE_VIEWBOX_WIDTH / n
    bar_w = max(1.0, step * 0.89)

    band = []
    for i, c in enumerate(ordered):
        row = build_cycle_row(c, tz_name="UTC")
        height_pct = max(4, round((row["top_score"] or 0) / 10 * 100))
        h = CADENCE_VIEWBOX_HEIGHT * height_pct / 100
        band.append({
            "cycle_id": row["cycle_id"],
            "height_pct": height_pct,
            "has_action": row["has_action"],
            "status": row["status"],
            "top_score": row["top_score"],
            "x": round(i * step, 2),
            "width": round(bar_w, 2),
            "y": round(CADENCE_VIEWBOX_HEIGHT - h, 2),
            "height": round(h, 2),
        })
    return band


def cadence_summary(band: list) -> dict:
    """Décompte pour la légende et le libellé d'accessibilité de la bande de cadence."""
    failed = sum(1 for b in band if b["status"] == "error")
    acted = sum(1 for b in band if b["has_action"] and b["status"] != "error")
    return {
        "total": len(band),
        "acted": acted,
        "failed": failed,
        "idle": len(band) - acted - failed,
        "threshold": CADENCE_SCORE_THRESHOLD,
        "threshold_y": round(CADENCE_VIEWBOX_HEIGHT * (1 - CADENCE_SCORE_THRESHOLD / 10), 1),
        "viewbox_width": CADENCE_VIEWBOX_WIDTH,
        "viewbox_height": CADENCE_VIEWBOX_HEIGHT,
    }
