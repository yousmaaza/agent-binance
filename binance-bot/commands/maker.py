"""Commande /maker — retourne une str (compatible Telegram et CLI).

Lecture seule : lit state/maker_watcher_state.json, state/maker_pending_orders.json et
state/trade_history.json, ne modifie jamais l'état ni n'interfère avec core/maker_watcher.py (#388).
"""
import json
import statistics
from datetime import datetime, timedelta, timezone

from core.env import PROJECT_DIR
from core.timing import fmt_local, parse_dt
from core.trade_helpers import _load_config

_WATCHER_STATE_PATH = f"{PROJECT_DIR}/state/maker_watcher_state.json"
_PENDING_ORDERS_PATH = f"{PROJECT_DIR}/state/maker_pending_orders.json"
_HISTORY_PATH = f"{PROJECT_DIR}/state/trade_history.json"

_MAX_ORDERS_SHOWN = 8
_STALE_TICK_FACTOR = 5  # marge avant de considérer le watcher en panne (vs maker_tick_seconds)


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _fmt_duration(td: timedelta) -> str:
    total_seconds = max(0, int(td.total_seconds()))
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, _ = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}"


def _fmt_seconds_precise(seconds: float) -> str:
    """Précision à la seconde (#430) : contrairement à _fmt_duration, jamais tronqué à la
    minute — cette métrique sert à régler maker_max_concession_pct et maker_timeout_seconds."""
    return f"{round(seconds)}s"


# ---------------------------------------------------------------------------
# Bloc 1 — Santé du watcher
# ---------------------------------------------------------------------------

def _format_health_section(cfg: dict, state: dict | None) -> list[str]:
    lines = ["🧊 <b>Watcher maker</b>"]

    if not cfg.get("maker_entry_enabled", True):
        lines.append("  🔴 Désactivé (<code>maker_entry_enabled: false</code>) — entrées en BUY MARKET direct")
        return lines

    if state is None:
        lines.append("  ⏳ En attente du premier tick (watcher tout juste démarré)")
        return lines

    tick_seconds = cfg.get("maker_tick_seconds", 20)
    last_tick_dt = parse_dt(state.get("last_tick"))
    if last_tick_dt is not None:
        age_seconds = (datetime.now(timezone.utc) - last_tick_dt).total_seconds()
        stale = age_seconds > tick_seconds * _STALE_TICK_FACTOR
        tick_str = fmt_local(last_tick_dt)
    else:
        stale = True
        tick_str = "–"

    last_error = state.get("last_error")
    if last_error:
        health = "🔴 Erreur"
    elif stale:
        health = "⚠️ Lent / inactif"
    else:
        health = "✅ OK"

    lines.append(f"  Statut : {health}")
    lines.append(f"  Dernier tick : {tick_str}")
    if last_error:
        lines.append(f"  Dernière erreur : {last_error}")
    lines.append(
        f"  Cumul : {state.get('total_ticks', 0)} ticks, "
        f"{state.get('total_fills', 0)} remplis, {state.get('total_fallbacks', 0)} replis marché, "
        f"{state.get('total_abandoned', 0)} abandonné(s)"
    )
    return lines


# ---------------------------------------------------------------------------
# Bloc 2 — Ordres en cours de poursuite
# ---------------------------------------------------------------------------

def _format_pending_section(cfg: dict) -> list[str]:
    pending_orders = _load_json(_PENDING_ORDERS_PATH, [])
    lines = ["\n📋 <b>Ordres en cours de poursuite</b>"]

    if not pending_orders:
        lines.append("  Aucun ordre en attente.")
        return lines

    budget_pct = cfg.get("maker_max_concession_pct", 0.003)
    shown = pending_orders[:_MAX_ORDERS_SHOWN]
    for o in shown:
        coin = o.get("coin", "?")
        qty = float(o.get("quantity", 0) or 0)
        initial_price = float(o.get("initial_limit_price", 0) or 0)
        current_price = float(o.get("current_limit_price") or initial_price)
        concession_pct = max(0.0, (current_price - initial_price) / initial_price) if initial_price else 0.0
        ratio = concession_pct / budget_pct if budget_pct else 0.0
        alert = " ⚠️" if ratio >= 0.8 else ""
        adjustments = o.get("adjustments", 0)

        placed_at_dt = parse_dt(o.get("placed_at"))
        elapsed_str = _fmt_duration(datetime.now(timezone.utc) - placed_at_dt) if placed_at_dt else "–"

        lines.append(
            f"  🪙 <b>{coin}</b> : {qty:.6g} @ {current_price:.4g}{alert}\n"
            f"     Concession : {concession_pct * 100:.2f}% / {budget_pct * 100:.2f}% | "
            f"{adjustments} ajustement(s) | depuis {elapsed_str}"
        )

    remaining = len(pending_orders) - len(shown)
    if remaining > 0:
        lines.append(f"  … et {remaining} autre(s) ordre(s) non affiché(s)")
    return lines


# ---------------------------------------------------------------------------
# Bloc 3 — Efficacité cumulée
# ---------------------------------------------------------------------------

def _fill_rate_pct(trades: list) -> float | None:
    if not trades:
        return None
    makers = sum(1 for t in trades if t.get("maker_or_taker") == "maker")
    return makers / len(trades) * 100


# En dessous de ce seuil de trades classés sur 7j, la tendance est trop bruitée pour être
# affichée sans induire en erreur (#430) — cf. échantillon actuel de 5 fills au total.
_MIN_TREND_SAMPLE = 5


def _format_watcher_funnel(state: dict | None) -> list[str]:
    """Fills/fallbacks/abandoned partagent le même dénominateur (compteurs cumulés de
    maker_watcher_state.json) : affichés ensemble pour sommer à ~100%, jamais mélangés avec
    les stats issues de trade_history (retour coordinateur #430).

    Population distincte de trade_history : ces compteurs repartent de zéro si le fichier
    d'état est perdu/corrompu (core/maker_watcher.py::_write_watcher_state, except
    FileNotFoundError/JSONDecodeError/KeyError), contrairement à trade_history qui ne se
    réinitialise jamais — d'où le label explicite pour ne pas laisser croire à un effondrement
    de la stratégie après une simple perte de fichier."""
    total_fills = (state or {}).get("total_fills", 0)
    total_fallbacks = (state or {}).get("total_fallbacks", 0)
    total_abandoned = (state or {}).get("total_abandoned", 0)
    total_attempts = total_fills + total_fallbacks + total_abandoned

    if not total_attempts:
        return ["  Funnel watcher (compteurs internes) : n/d (aucune tentative enregistrée)"]

    fills_pct = total_fills / total_attempts * 100
    fallbacks_pct = total_fallbacks / total_attempts * 100
    abandoned_pct = total_abandoned / total_attempts * 100
    return [
        f"  Funnel watcher (compteurs internes, remis à zéro si l'état est perdu — "
        f"{total_attempts} tentative(s)) :",
        f"    Remplis {fills_pct:.0f}% ({total_fills}) / Replis marché {fallbacks_pct:.0f}% ({total_fallbacks}) "
        f"/ Abandonnés {abandoned_pct:.0f}% ({total_abandoned})",
    ]


def _format_efficiency_section(state: dict | None) -> list[str]:
    history = _load_json(_HISTORY_PATH, [])
    lines = ["\n📈 <b>Efficacité cumulée</b>"]

    # Les trades sans maker_or_taker (historique avant #382, ou ordertype non classable) sont
    # exclus : ne jamais les compter à tort comme taker.
    classified = [t for t in history if t.get("maker_or_taker") in ("maker", "taker")]

    if not classified:
        lines.append("  Pas encore de données (aucun trade classé maker/taker).")
        lines.extend(_format_watcher_funnel(state))
        return lines

    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    today_trades = [t for t in classified if (dt := parse_dt(t.get("date"))) and dt >= cutoff_24h]

    rate_today = _fill_rate_pct(today_trades)
    rate_all = _fill_rate_pct(classified)
    rate_today_str = f"{rate_today:.0f}%" if rate_today is not None else "n/d"
    lines.append(
        f"  Taux de remplissage maker (historique trades) : {rate_today_str} (24h) / "
        f"{rate_all:.0f}% (depuis le début, sur {len(classified)} trade(s) classé(s))"
    )

    fees_avoided = sum(
        t["entry_fee_usdc"] for t in classified
        if t.get("maker_or_taker") == "maker" and t.get("entry_fee_usdc") is not None
    )
    lines.append(f"  Frais évités vs taker : ~{fees_avoided:.2f} USDC")

    delays = [
        t["maker_fill_seconds"] for t in classified
        if t.get("maker_or_taker") == "maker" and t.get("maker_fill_seconds") is not None
    ]
    if delays:
        median_str = _fmt_seconds_precise(statistics.median(delays))
        lines.append(f"  Délai médian de remplissage : {median_str} (sur {len(delays)} fill(s))")
    else:
        lines.append("  Délai médian de remplissage : n/d (pas encore de fill maker mesuré)")

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    week_trades = [t for t in classified if (dt := parse_dt(t.get("date"))) and dt >= cutoff_7d]
    if len(week_trades) < _MIN_TREND_SAMPLE:
        lines.append(
            f"  Tendance 7j : échantillon insuffisant ({len(week_trades)} trade(s) classé(s)) "
            "— pas de tendance fiable à ce stade"
        )
    else:
        rate_7d = _fill_rate_pct(week_trades)
        lines.append(
            f"  Tendance 7j : {rate_7d:.0f}% de remplissage (sur {len(week_trades)} trade(s)) "
            f"vs {rate_all:.0f}% depuis le début"
        )

    lines.extend(_format_watcher_funnel(state))
    return lines


def run_maker() -> str:
    cfg = _load_config(PROJECT_DIR)
    state = _load_json(_WATCHER_STATE_PATH, None)
    lines = _format_health_section(cfg, state)
    lines.extend(_format_pending_section(cfg))
    lines.extend(_format_efficiency_section(state))
    return "\n".join(lines)
