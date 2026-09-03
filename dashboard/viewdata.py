"""Mise en forme des documents Mongo bruts en structures prêtes pour les templates (#432).

Séparé des routes Flask pour rester testable sans client HTTP : chaque fonction prend des
dicts déjà lus (dashboard_state, cycles) et retourne des dicts/valeurs simples."""
from datetime import datetime, timedelta, timezone

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


MONTH_NAMES_FR = ("janv.", "févr.", "mars", "avr.", "mai", "juin",
                  "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def pnl_by_period(curve: list, granularity: str = "day") -> list:
    """PnL net de chaque période, dérivé de la courbe cumulée publiée par la Phase 7 (#450).

    equity_curve porte un point par jour ayant eu au moins un trade clôturé, en cumulé : le PnL
    d'un jour est donc la différence avec le cumul précédent, le premier point partant de zéro.
    La somme des périodes reconstitue exactement financials.global.net_usdc."""
    if not curve:
        return []

    daily, previous = [], 0.0
    for point in curve:
        cumulative = point.get("cumulative_pnl_usdc", 0) or 0
        daily.append((str(point.get("date", "")), cumulative - previous))
        previous = cumulative

    if granularity == "day":
        return [{"key": date, "label": _day_label(date), "value": value} for date, value in daily]

    grouped: dict[str, float] = {}
    for date, value in daily:
        grouped[date[:7]] = grouped.get(date[:7], 0.0) + value
    return [
        {"key": key, "label": _month_label(key), "value": value}
        for key, value in sorted(grouped.items())
    ]


def _day_label(date: str) -> str:
    parts = date.split("-")
    return f"{parts[2]}/{parts[1]}" if len(parts) == 3 else date


def _month_label(key: str) -> str:
    parts = key.split("-")
    if len(parts) != 2:
        return key
    month = int(parts[1])
    return f"{MONTH_NAMES_FR[month - 1]} {parts[0]}" if 1 <= month <= 12 else key


def pnl_bars(periods: list, width: int = 640, height: int = 170, pad: int = 10) -> dict:
    """Géométrie des barres divergentes autour de la ligne de zéro (#450).

    L'échelle est symétrique autour de zéro : sans cela une perte de 24 et un gain de 18
    produiraient des barres de même longueur apparente selon le côté."""
    if not periods:
        return {}

    values = [p["value"] for p in periods]
    extent = max(abs(min(values)), abs(max(values))) or 1.0
    zero_y = height / 2
    usable = zero_y - pad

    n = len(periods)
    step = (width - 2 * pad) / n
    bar_w = max(1.0, step * 0.72)

    bars = []
    for i, period in enumerate(periods):
        value = period["value"]
        bar_h = abs(value) / extent * usable
        bars.append({
            **period,
            "x": round(pad + i * step + (step - bar_w) / 2, 2),
            "width": round(bar_w, 2),
            "y": round(zero_y - bar_h if value >= 0 else zero_y, 2),
            "height": round(max(bar_h, 0.6), 2),  # une période à zéro doit rester visible
            "positive": value >= 0,
        })

    return {
        "bars": bars,
        "zero_y": round(zero_y, 1),
        "width": width,
        "height": height,
        "pad": pad,
        "extent": round(extent, 2),
        "total": round(sum(values), 2),
        "best": max(periods, key=lambda p: p["value"]),
        "worst": min(periods, key=lambda p: p["value"]),
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


def build_weekly_analysis_view(doc: dict | None, fallback_text: str, tz_name: str) -> dict:
    """Bloc « Note de la semaine » (#453) : l'analyse rédigée par Claude si elle existe et a
    passé le contrôle numérique, sinon le repli déterministe — jamais l'un pour l'autre sans
    le dire (le lecteur doit toujours savoir lequel des deux il lit)."""
    if not doc or not doc.get("text"):
        return {"is_fallback": True, "text": fallback_text, "generated_at": None}

    dt = parse_iso(doc.get("generated_at"))
    return {
        "is_fallback": False,
        "text": doc["text"],
        "generated_at": to_local(dt, tz_name) if dt else None,
        "window_days": doc.get("window_days"),
        "window_widened": doc.get("window_widened", False),
    }


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


CADENCE_SCORE_THRESHOLD = 6  # score minimal déclenchant un achat

# Créneaux auto du bot, alignés sur les clôtures TradingView 4h (cf. CLAUDE.md, règle 6).
SLOT_HOURS_UTC = (0, 4, 8, 12, 16, 20)
SLOT_MINUTE_UTC = 5
SLOT_TOLERANCE_S = 3600  # un cycle compte pour son créneau s'il démarre dans l'heure qui suit


def build_cycle_grid(cycles: list, days: int, tz_name: str, now: datetime | None = None) -> dict:
    """Grille des créneaux attendus sur `days` jours, une colonne par jour (#450).

    Part du **calendrier théorique** et non des documents en base : c'est la seule façon de voir
    les cycles qui n'ont jamais démarré, lesquels n'écrivent rien et sont donc invisibles pour
    tout compteur qui parcourt la collection."""
    now = now or datetime.now(timezone.utc)

    slots = []
    first_day = (now - timedelta(days=days - 1)).replace(
        hour=0, minute=SLOT_MINUTE_UTC, second=0, microsecond=0)
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        for hour in SLOT_HOURS_UTC:
            slot = day.replace(hour=hour)
            if slot <= now:
                slots.append(slot)

    matched = _match_cycles_to_slots(cycles, slots)

    columns, counts = [], {"action": 0, "idle": 0, "error": 0, "missing": 0}
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        cells = []
        for hour in SLOT_HOURS_UTC:
            slot = day.replace(hour=hour)
            if slot not in set(slots):
                cells.append(None)  # créneau encore à venir aujourd'hui
                continue
            cell = _grid_cell(slot, matched.get(slot), tz_name)
            counts[cell["state"]] += 1
            cells.append(cell)
        columns.append({
            "date": day.strftime("%Y-%m-%d"),
            "label": day.strftime("%d/%m"),
            "is_month_start": day.day == 1,
            "cells": cells,
        })

    _mark_date_labels(columns)

    ran = len(slots) - counts["missing"]
    return {
        "columns": columns,
        "slot_labels": [_slot_label(first_day.replace(hour=h), tz_name) for h in SLOT_HOURS_UTC],
        "counts": counts,
        "total": len(slots),
        "ran": ran,
        "ran_pct": round(ran / len(slots) * 100) if slots else None,
        "error_pct": round(counts["error"] / ran * 100) if ran else None,
        "days": days,
    }



def _mark_date_labels(columns: list, spacing: int = 7) -> None:
    """Un repère de date tous les 7 jours et à chaque début de mois, mais jamais deux collés :
    31/07 et 01/08 sont voisins et leurs libellés se chevaucheraient (#450)."""
    last = None
    for i, column in enumerate(columns):
        wanted = i == 0 or column["is_month_start"] or i % spacing == 0
        column["show_label"] = bool(wanted and (last is None or i - last >= 3))
        if column["show_label"]:
            last = i


def _match_cycles_to_slots(cycles: list, slots: list) -> dict:
    """Rattache chaque cycle au créneau le plus proche, dans la tolérance. Un cycle lancé à la
    main près d'un créneau le tient : le travail a bien été fait, peu importe le déclencheur."""
    matched: dict = {}
    for cycle in cycles:
        started = parse_iso(cycle.get("timestamp"))
        if started is None:
            continue
        candidates = [s for s in slots if abs((started - s).total_seconds()) <= SLOT_TOLERANCE_S]
        if not candidates:
            continue
        slot = min(candidates, key=lambda s: abs((started - s).total_seconds()))
        previous = matched.get(slot)
        # à créneau égal, garder le cycle le plus proche de l'heure théorique
        if previous is None or abs((started - slot).total_seconds()) < abs(
                (parse_iso(previous["timestamp"]) - slot).total_seconds()):
            matched[slot] = cycle
    return matched


def _grid_cell(slot: datetime, cycle: dict | None, tz_name: str) -> dict:
    local = to_local(slot, tz_name, fmt="%d/%m %H:%M")
    if cycle is None:
        return {"state": "missing", "slot_local": local, "cycle_id": None}

    execution = cycle.get("execution") or {}
    executed = execution.get("executed", cycle.get("executed", 0)) or 0
    pending = execution.get("pending", cycle.get("pending", 0)) or 0
    failed = cycle.get("status") == "error"

    return {
        "state": "error" if failed else ("action" if (executed or pending) else "idle"),
        "slot_local": local,
        "cycle_id": cycle.get("cycle_id"),
        "top_score": cycle.get("top_score") or 0,
        "executed": executed,
        "pending": pending,
        "duration_s": round(cycle.get("duration_s") or cycle.get("duration_seconds") or 0),
        "cost_usd": round(cycle.get("api_cost_usd") or 0, 2),
        "manual": cycle.get("trigger") == "manual",
    }


def _slot_label(slot: datetime, tz_name: str) -> str:
    return to_local(slot, tz_name, fmt="%H:%M")


def build_cadence_band(cycles: list) -> list:
    """Un état par cycle, en ordre chronologique. La bande SVG a été retirée de l'affichage
    (#450) ; ces données servent encore à la tuile « cycles ok » et à la note de la semaine."""
    ordered = list(reversed(cycles))  # cycles arrivent triés desc (le plus récent d'abord)
    band = []
    for c in ordered:
        row = build_cycle_row(c, tz_name="UTC")
        band.append({
            "cycle_id": row["cycle_id"],
            "has_action": row["has_action"],
            "status": row["status"],
            "top_score": row["top_score"],
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
    }


# ---------------------------------------------------------------------------
# Onglet Ventes (#455)
# ---------------------------------------------------------------------------

# Le même événement arrive sous plusieurs noms selon le chemin de code : les compter
# séparément fragmenterait le total des stops et le sous-estimerait.
CLOSE_REASON_LABELS = {
    "sl_hit": "stop touché", "stop_hit": "stop touché", "sl": "stop touché",
    "tp_watcher": "cible atteinte", "tp_watcher_cycle": "cible atteinte",
    "profit_target_phase0": "cible de profit",
    "signal_sell_score1": "signal retombé", "signal_sell_score2": "signal retombé",
    "signal_sell_score3": "signal retombé",
    "protection_exhausted": "protection épuisée", "manual_sell_ios": "vente manuelle",
    "oco_not_found": "OCO introuvable", "oco_filled_detected": "OCO déjà exécuté",
}
UNKNOWN_REASON = "non renseignée"


def close_reason_label(raw) -> str:
    return CLOSE_REASON_LABELS.get(raw, UNKNOWN_REASON if not raw else str(raw))


def _suspect_exit(trade: dict) -> str | None:
    """Un prix de sortie qui impliquerait un gain alors que le résultat enregistré est une perte
    ne peut pas être vrai (#455). Cas connu : SYN 38515bab, stop « déclenché » au-dessus du prix
    d'entrée. On signale sans corriger — c'est le prix qui est faux, pas le résultat."""
    entry, exit_price = trade.get("entry_price"), trade.get("exit_price")
    quantity, net = trade.get("quantity"), trade.get("pnl_usdc")
    if None in (entry, exit_price, quantity, net):
        return None
    if (exit_price - entry) * quantity > 1 and net < 0:
        return "prix de sortie incohérent avec le résultat enregistré"
    return None


def build_sales_rows(closed_trades: list, tz_name: str) -> list:
    rows = []
    for trade in closed_trades or []:
        entered, exited = parse_iso(trade.get("entry_date")), parse_iso(trade.get("exit_date"))
        rows.append({
            **trade,
            "reason_label": close_reason_label(trade.get("close_reason")),
            "entry_local": to_local(entered, tz_name, fmt="%d/%m") if entered else "—",
            "exit_local": to_local(exited, tz_name, fmt="%d/%m") if exited else "—",
            "hold_label": _hold_label(trade.get("hold_hours")),
            "suspect": _suspect_exit(trade),
            "is_win": (trade.get("pnl_usdc") or 0) > 0,
            # montants en USDC : c'est ce qui est sorti et rentré du portefeuille, plus
            # parlant que le prix unitaire du coin (retour de review #455)
            "invested": (trade.get("quantity") or 0) * trade.get("entry_price")
            if trade.get("entry_price") is not None else None,
            "proceeds": (trade.get("quantity") or 0) * trade.get("exit_price")
            if trade.get("exit_price") is not None else None,
            "trigger": sale_trigger(trade.get("close_reason"))[0],
            "trigger_detail": sale_trigger(trade.get("close_reason"))[1],
            "anomaly": sale_anomaly(trade),
        })
    return rows


def _hold_label(hours) -> str:
    if hours is None:
        return "—"
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.0f} j"


SALES_WINDOWS = [("7j", "1 semaine", 7), ("30j", "1 mois", 30),
                 ("90j", "3 mois", 90), ("180j", "6 mois", 180), ("tout", "tout", None)]


def filter_sales_window(closed_trades: list, key: str, now: datetime | None = None) -> list:
    """Restreint les ventes à une fenêtre. Le filtre s'applique **avant** les agrégats : les
    totaux, les motifs et les durées portent tous sur la même période, sinon le bandeau
    contredirait le journal juste en dessous."""
    days = next((d for k, _, d in SALES_WINDOWS if k == key), None)
    if days is None:
        return closed_trades
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    kept = []
    for trade in closed_trades or []:
        exited = parse_iso(trade.get("exit_date"))
        if exited is not None and exited >= cutoff:
            kept.append(trade)
    return kept


def _build_reasons_breakdown(rows: list) -> list:
    """Agrégation par motif de clôture avec calcul des médians de durée."""
    by_reason: dict = {}
    for row in rows:
        bucket = by_reason.setdefault(row["reason_label"], {"n": 0, "net": 0.0, "fees": 0.0, "holds": []})
        bucket["n"] += 1
        bucket["net"] += row.get("pnl_usdc") or 0
        bucket["fees"] += row.get("fees_usdc") or 0
        if row.get("hold_hours") is not None:
            bucket["holds"].append(row["hold_hours"])

    reasons = sorted(
        ({"label": label, "n": b["n"], "net": round(b["net"], 2),
          "fees": round(b["fees"], 2), "median_hold": _median(b["holds"])}
         for label, b in by_reason.items()),
        key=lambda r: r["net"],
    )
    extent = max((abs(r["net"]) for r in reasons), default=0) or 1.0
    for reason in reasons:
        reason["bar_pct"] = round(abs(reason["net"]) / extent * 50, 1)
    return reasons


def _build_totals(rows: list) -> dict:
    """Calcul des montants et statistiques globales."""
    net = sum(r.get("pnl_usdc") or 0 for r in rows)
    gross = sum(r.get("pnl_gross_usdc") or 0 for r in rows)
    fees = sum(r.get("fees_usdc") or 0 for r in rows)
    wins = [r for r in rows if r["is_win"]]
    return {
        "count": len(rows), "net": round(net, 2), "gross": round(gross, 2),
        "fees": round(fees, 2), "wins": len(wins),
        "win_pct": round(len(wins) / len(rows) * 100),
        "fees_pct_of_gross": round(fees / abs(gross) * 100) if gross else None,
        "invested": round(sum(r["invested"] or 0 for r in rows if not r["suspect"]), 2),
        "proceeds": round(sum(r["proceeds"] or 0 for r in rows if not r["suspect"]), 2),
        "excluded_from_amounts": sum(1 for r in rows if r["suspect"]),
    }


def _build_durations(rows: list, reasons: list) -> dict:
    """Calcul des durées de maintien par catégorie."""
    return {
        "wins": _median([r["hold_hours"] for r in rows if r["is_win"] and r["hold_hours"] is not None]),
        "losses": _median([r["hold_hours"] for r in rows if not r["is_win"] and r["hold_hours"] is not None]),
        "by_reason": {r["label"]: r["median_hold"] for r in reasons},
    }


def _build_quality(rows: list) -> dict:
    """Classement de la qualité des données de frais."""
    return {
        "estimated": sum(1 for r in rows if r.get("fees_estimated")),
        "missing_fees": sum(1 for r in rows if r.get("fees_usdc") is None),
        "suspect": sum(1 for r in rows if r["suspect"]),
        "reliable": sum(1 for r in rows if r.get("fees_usdc") is not None and not r.get("fees_estimated")),
    }


def build_sales_view(closed_trades: list, tz_name: str) -> dict:
    """Agrégats de l'onglet Ventes. Tout chiffre est accompagné de son effectif : sur 87 ventes
    dont un tiers porte des frais estimés, une moyenne sans son n induirait en erreur."""
    rows = build_sales_rows(closed_trades, tz_name)
    if not rows:
        return {"rows": [], "reasons": [], "totals": {}, "quality": {}, "durations": {}}

    reasons = _build_reasons_breakdown(rows)
    totals = _build_totals(rows)
    durations = _build_durations(rows, reasons)
    quality = _build_quality(rows)

    return {
        "rows": rows,
        "reasons": reasons,
        "totals": totals,
        "durations": durations,
        "triggers": _by_trigger(rows),
        "anomalies": [r for r in rows if r["anomaly"]],
        "quality": quality,
    }


def _median(values: list):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle])
    return round((ordered[middle - 1] + ordered[middle]) / 2)


# Qui a réellement déclenché la vente (#455, retour de review). Le motif de clôture le dit de
# façon fiable ; l'horodatage non — un tp_watcher tombe dans une fenêtre de cycle 6 fois sur 15
# par simple coïncidence, ce qui rendrait tout rattachement déduit faux dans 40 % des cas.
SALE_TRIGGERS = {
    "profit_target_phase0": ("cycle", "Phase 0 d'un cycle — seuil de profit atteint"),
    "signal_sell_score1": ("cycle", "pendant un cycle — signal retombé"),
    "signal_sell_score2": ("cycle", "pendant un cycle — signal retombé"),
    "signal_sell_score3": ("cycle", "pendant un cycle — signal retombé"),
    "protection_exhausted": ("cycle", "Phase 0 d'un cycle — protection épuisée"),
    "oco_not_found": ("cycle", "Phase 0 d'un cycle — OCO introuvable"),
    "oco_filled_detected": ("cycle", "Phase 0 d'un cycle — OCO déjà exécuté"),
    "tp_watcher": ("watcher", "TP watcher, hors cycle"),
    "tp_watcher_cycle": ("watcher", "TP watcher, hors cycle"),
    "sl_hit": ("kraken", "ordre stop exécuté chez Kraken, hors cycle"),
    "stop_hit": ("kraken", "ordre stop exécuté chez Kraken, hors cycle"),
    "sl": ("kraken", "ordre stop exécuté chez Kraken, hors cycle"),
    "manual_sell_ios": ("manuel", "vente déclenchée à la main"),
}
TRIGGER_LABELS = {"cycle": "cycle", "watcher": "watcher", "kraken": "stop Kraken",
                  "manuel": "manuel", "inconnu": "inconnu"}
# La prise de profit sort volontairement avant la cible : ce n'est pas un manquement du watcher.
_EARLY_BY_DESIGN = {"profit_target_phase0"}


def sale_trigger(raw) -> tuple[str, str]:
    return SALE_TRIGGERS.get(raw, ("inconnu", "motif de clôture non enregistré"))


def sale_anomaly(trade: dict) -> str | None:
    """Écarts entre ce que la vente aurait dû faire et ce qu'elle a fait (#455).

    Deux cas se lisent dans les données stockées, sans OHLC : une cible franchie alors qu'un
    autre mécanisme a vendu — le TP watcher aurait dû sortir en premier — et une sortie estampillée
    TP nettement sous la cible."""
    tp, exit_price = trade.get("tp_price"), trade.get("exit_price")
    reason = trade.get("close_reason")
    if tp is None or exit_price is None or not tp:
        return None
    kind, _ = sale_trigger(reason)

    if exit_price >= tp and kind not in ("watcher",) and reason not in _EARLY_BY_DESIGN:
        if kind == "inconnu":
            return None  # motif absent : on ne peut rien reprocher à personne
        return "cible franchie, mais la vente vient d'ailleurs — le TP n'a pas déclenché"

    if kind == "watcher" and exit_price < tp * 0.99:
        return f"vendu {abs(exit_price - tp) / tp * 100:.1f} % sous la cible annoncée"
    return None


def _by_trigger(rows: list) -> list:
    """Répartition des ventes par déclencheur, avec le net que chacun a produit."""
    buckets: dict = {}
    for row in rows:
        b = buckets.setdefault(row["trigger"], {"n": 0, "net": 0.0})
        b["n"] += 1
        b["net"] += row.get("pnl_usdc") or 0
    out = [{"key": k, "label": TRIGGER_LABELS.get(k, k), "n": v["n"], "net": round(v["net"], 2)}
           for k, v in buckets.items()]
    return sorted(out, key=lambda t: -t["n"])
