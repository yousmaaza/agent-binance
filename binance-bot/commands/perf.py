"""Commande /perf — bilan de performance : résultat net de frais, périodes, positions,
TP Watcher, stratégie maker. Lecture seule, retourne une str HTML pour Telegram."""
import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.env import PROJECT_DIR
from core.timing import fmt_local, parse_dt

_HISTORY_PATH = f"{PROJECT_DIR}/state/trade_history.json"
_CYCLE_LOG_PATH = f"{PROJECT_DIR}/state/cycle_log.jsonl"
_TP_WATCHER_STATE_PATH = f"{PROJECT_DIR}/state/tp_watcher_state.json"
_MAKER_WATCHER_STATE_PATH = f"{PROJECT_DIR}/state/maker_watcher_state.json"
_MAKER_PENDING_ORDERS_PATH = f"{PROJECT_DIR}/state/maker_pending_orders.json"

# Vulgarisation des skip_type internes (cf. CLAUDE.md) pour un public francophone non-crypto.
_SKIP_LABELS = {
    "TYPE_A": "score faible",
    "TYPE_B": "trop petit",
    "TYPE_C": "conditions dégradées",
    "TYPE_D": "indisponible",
}


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _load_history() -> list:
    data = _load_json(_HISTORY_PATH, [])
    return data if isinstance(data, list) else []


def _pnl(t: dict) -> float:
    return t.get("pnl_usdc") or 0


def _fees(t: dict) -> Optional[float]:
    return t.get("fees_usdc")


def _exit_dt(t: dict) -> Optional[datetime]:
    return parse_dt(t.get("exit_date"))


def _fmt_duration(td: timedelta) -> str:
    total_seconds = max(0, int(td.total_seconds()))
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, _ = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}"


def _tp_watcher_closed(closed: list) -> list:
    """Trades fermés par le TP Watcher — seule source fiable (cf. #396), utilisée à la fois
    par le Bloc Positions et le Bloc TP Watcher pour ne jamais afficher deux chiffres différents
    pour le même fait."""
    return [t for t in closed if "tp_watcher" in (t.get("close_reason") or "")]


def _brut_frais_net(trades: list) -> tuple[float, float, float]:
    """net est toujours connu (pnl_usdc). brut est dérivé de net + frais connus : pour les
    trades sans fees_usdc (garde-fou de cohérence du backfill, ex. SYN/PENDLE), cela revient à
    supposer des frais nuls sur ces trades précis — mais préserve l'identité brut - frais = net
    sans jamais fabriquer de frais estimés supplémentaires."""
    net = sum(_pnl(t) for t in trades)
    frais = sum(f for t in trades if (f := _fees(t)) is not None)
    return net + frais, frais, net


# ---------------------------------------------------------------------------
# Résultat net (brut → frais → net) + KPIs de base
# ---------------------------------------------------------------------------

def _bloc_resultat(closed: list) -> list[str]:
    brut, frais, net = _brut_frais_net(closed)
    frais_pct_str = f"{frais / brut * 100:.0f}%" if brut > 0 else "n/d"

    wins = [t for t in closed if _pnl(t) > 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    best = max(closed, key=_pnl) if closed else None
    worst = min(closed, key=_pnl) if closed else None

    coin_pnl: dict[str, float] = {}
    for t in closed:
        c = t.get("coin", "?")
        coin_pnl[c] = coin_pnl.get(c, 0) + _pnl(t)
    top_coins = sorted(coin_pnl.items(), key=lambda x: x[1], reverse=True)[:3]

    durations = []
    for t in closed:
        e = parse_dt(t.get("date"))
        x = _exit_dt(t)
        if e and x:
            durations.append((x - e).total_seconds())
    avg_h = (sum(durations) / len(durations) / 3600) if durations else 0
    hold_str = f"{avg_h / 24:.1f}j" if avg_h >= 24 else f"{avg_h:.1f}h"

    def trade_label(t):
        d = _exit_dt(t)
        return f"{t.get('coin')} {_pnl(t):+.2f} USDC ({fmt_local(d)[:5] if d else '?'})"

    lines = [f"\n📈 <b>Résultat net ({len(closed)} trades fermés)</b>"]
    lines.append(
        f"Brut <code>{brut:+.2f}</code> → frais <code>-{frais:.2f}</code>"
        f" ({frais_pct_str} du brut) → net <code>{net:+.2f} USDC</code>"
    )
    lines.append(f"Gagnants : <code>{win_rate:.1f}%</code>  ({len(wins)}W / {len(closed) - len(wins)}L)")
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
# Périodes non chevauchantes 0-7j / 8-30j / au-delà
# ---------------------------------------------------------------------------

def _bloc_periodes(closed: list) -> list[str]:
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    buckets: dict[str, list] = {"0-7": [], "8-30": [], "30+": []}
    for t in closed:
        dt = _exit_dt(t)
        if dt is None:
            continue
        if dt >= cutoff_7d:
            buckets["0-7"].append(t)
        elif dt >= cutoff_30d:
            buckets["8-30"].append(t)
        else:
            buckets["30+"].append(t)

    labels = {"0-7": "0-7 j", "8-30": "8-30 j", "30+": "au-delà"}
    lines = ["\n📅 <b>Par période (non chevauchantes)</b>"]
    for key in ("0-7", "8-30", "30+"):
        trades = buckets[key]
        if not trades:
            lines.append(f"{labels[key]} : <code>0 trade</code>")
            continue
        brut, frais, net = _brut_frais_net(trades)
        lines.append(
            f"{labels[key]} ({len(trades)}) : brut <code>{brut:+.2f}</code>"
            f"  frais <code>-{frais:.2f}</code>  net <code>{net:+.2f}</code>"
        )
    return lines


# ---------------------------------------------------------------------------
# Frais payés (mesurés / estimés / non calculés)
# ---------------------------------------------------------------------------

def _bloc_frais(closed: list) -> list[str]:
    with_fees = [t for t in closed if _fees(t) is not None]
    measured = [t for t in with_fees if not t.get("fees_estimated")]
    estimated = [t for t in with_fees if t.get("fees_estimated")]
    missing = len(closed) - len(with_fees)

    total_fees = sum(_fees(t) for t in with_fees)
    avg_fee = total_fees / len(with_fees) if with_fees else 0

    lines = ["\n💸 <b>Frais payés</b>"]
    lines.append(f"Total : <code>{total_fees:.2f} USDC</code>  |  moy./trade : <code>{avg_fee:.2f}</code>")
    lines.append(
        f"Mesurés : <code>{len(measured)}</code>"
        f"  |  Estimés : <code>{len(estimated)}</code>"
        f"  |  Non calculés : <code>{missing}</code>"
    )
    return lines


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

def _load_cycles_jsonl() -> list:
    try:
        cycles = []
        with open(_CYCLE_LOG_PATH) as f:
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


def _format_cycle_lines(
    total: int,
    with_buy: int,
    skip_counts: dict,
    avg_dur: Optional[float] = None,
    errors: Optional[int] = None,
    quota: Optional[int] = None,
    source: str = "",
) -> list[str]:
    lines = [
        f"Total : <code>{total}</code>"
        f"  |  Avec BUY : <code>{with_buy}</code>"
        f"  |  Sans trade : <code>{total - with_buy}</code>"
    ]
    skip_str = "  ".join(f"{_SKIP_LABELS.get(k, k)}: {v}" for k, v in skip_counts.items())
    lines.append(f"Skips : <code>{skip_str}</code>")
    if avg_dur is not None:
        lines.append(f"Durée moy. : <code>{avg_dur:.0f}s</code>")
    if errors is not None:
        lines.append(f"Erreurs : <code>{errors}</code>  |  Blocage quota : <code>{quota}</code>")
    lines.append(f"(source : {source})")
    return lines


def _bloc_cycles() -> list[str]:
    lines = ["\n🔄 <b>Cycles</b>"]

    mongo_rows = None
    try:
        from storage.mongo import mongo_repo
        db = mongo_repo._db()
        if db is not None:
            mongo_rows = list(db.cycles.find({}, {
                "execution": 1, "decisions": 1,
                "duration_s": 1, "error_type": 1,
            }))
    except Exception:
        pass

    if mongo_rows is not None:
        skip_counts = {"TYPE_A": 0, "TYPE_B": 0, "TYPE_C": 0, "TYPE_D": 0}
        for c in mongo_rows:
            for d in (c.get("decisions") or []):
                st = d.get("skip_type")
                if st in skip_counts:
                    skip_counts[st] += 1
        durations = [c["duration_s"] for c in mongo_rows if c.get("duration_s") is not None]
        lines.extend(_format_cycle_lines(
            total=len(mongo_rows),
            with_buy=sum(1 for c in mongo_rows if (c.get("execution") or {}).get("executed", 0) > 0),
            skip_counts=skip_counts,
            avg_dur=sum(durations) / len(durations) if durations else None,
            errors=sum(1 for c in mongo_rows if c.get("error_type") is not None),
            quota=sum(1 for c in mongo_rows if c.get("error_type") == "quota"),
            source="Mongo",
        ))
    else:
        cycles = _load_cycles_jsonl()
        skip_counts = {"TYPE_A": 0, "TYPE_B": 0, "TYPE_C": 0, "TYPE_D": 0}
        for c in cycles:
            st = c.get("skip_type")
            if st in skip_counts:
                skip_counts[st] += 1
        lines.extend(_format_cycle_lines(
            total=len(cycles),
            with_buy=sum(1 for c in cycles if c.get("executed", 0) > 0),
            skip_counts=skip_counts,
            source="cycle_log.jsonl — duration_s/erreurs non disponibles",
        ))

    return lines


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def _bloc_positions(history: list) -> list[str]:
    open_trades = [t for t in history if t.get("status") == "open"]
    closed = [t for t in history if t.get("status") == "closed"]
    cancelled = [t for t in history if t.get("status") == "cancelled"]

    sl_hits = sum(
        1 for t in closed
        if t.get("close_reason") in ("sl_hit", "stop_hit", "sl")
    )
    tp_watcher_hits = len(_tp_watcher_closed(closed))
    profit_phase0 = sum(
        1 for t in closed
        if t.get("close_reason") == "profit_target_phase0"
    )

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

    lines = ["\n📊 <b>Positions</b>"]
    lines.append(
        f"Ouvertes : <code>{len(open_trades)}</code>"
        f"  |  Fermées : <code>{len(closed)}</code>"
        f"  |  Annulées : <code>{len(cancelled)}</code>"
    )
    lines.append(
        f"Par SL : <code>{sl_hits}</code>"
        f"  |  Par TP Watcher : <code>{tp_watcher_hits}</code>"
        f"  |  Profit Phase 0 : <code>{profit_phase0}</code>"
    )
    lines.append(f"Série en cours : <code>{streak_str}</code>")
    return lines


# ---------------------------------------------------------------------------
# TP Watcher
# ---------------------------------------------------------------------------

def _bloc_watcher(closed: list) -> list[str]:
    state = _load_json(_TP_WATCHER_STATE_PATH, None)
    tp_trades = _tp_watcher_closed(closed)

    lines = ["\n🤖 <b>TP Watcher</b>"]
    if state is None:
        lines.append("Ticks total : <code>inconnu</code> (fichier d'état absent)")
    else:
        lines.append(f"Ticks total : <code>{state.get('total_ticks', 'N/A')}</code>")

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    def in_period(t, cutoff):
        dt = _exit_dt(t)
        return dt is not None and dt >= cutoff

    sales_24h = sum(1 for t in tp_trades if in_period(t, cutoff_24h))
    sales_7d = sum(1 for t in tp_trades if in_period(t, cutoff_7d))
    usdc_watcher = sum(_pnl(t) for t in tp_trades)

    # Ventes (historique) reprend le même décompte que le Bloc Positions (source unique :
    # trade_history.json) — total_sales de tp_watcher_state.json n'est plus affiché ici, car ce
    # compteur repart à zéro à chaque redémarrage du service et contredisait ce chiffre (#396).
    lines.append(
        f"Ventes (historique) : <code>{len(tp_trades)}</code>"
        f"  |  24h : <code>{sales_24h}</code>"
        f"  |  7j : <code>{sales_7d}</code>"
    )
    lines.append(f"USDC réalisés via watcher : <code>{usdc_watcher:+.2f}</code>")
    return lines


# ---------------------------------------------------------------------------
# Stratégie maker
# ---------------------------------------------------------------------------

def _bloc_maker(history: list) -> list[str]:
    lines = ["\n🧊 <b>Stratégie maker</b>"]

    pending = _load_json(_MAKER_PENDING_ORDERS_PATH, [])
    if not isinstance(pending, list):
        pending = []
    capital_immobilise = sum(
        float(o.get("quantity", 0) or 0)
        * float(o.get("current_limit_price") or o.get("initial_limit_price") or 0)
        for o in pending
    )
    lines.append(
        f"En attente : <code>{len(pending)}</code> ordre(s)"
        f"  |  Capital immobilisé : <code>{capital_immobilise:.2f} USDC</code>"
    )

    watcher_state = _load_json(_MAKER_WATCHER_STATE_PATH, None)
    if watcher_state is None:
        lines.append("Répartition : pas encore de données (watcher pas encore démarré)")
    else:
        fills = watcher_state.get("total_fills", 0)
        fallbacks = watcher_state.get("total_fallbacks", 0)
        abandoned = watcher_state.get("total_abandoned", 0)
        total = fills + fallbacks + abandoned
        if total:
            lines.append(
                f"Servies en maker : <code>{fills}</code> ({fills / total * 100:.0f}%)"
                f"  |  Repli marché : <code>{fallbacks}</code> ({fallbacks / total * 100:.0f}%)"
                f"  |  Abandonnées : <code>{abandoned}</code> ({abandoned / total * 100:.0f}%)"
            )
        else:
            lines.append("Répartition : pas encore d'entrée traitée")

    # Les trades sans maker_or_taker (historique avant #382, ou ordertype non classable) sont
    # exclus : ne jamais les compter à tort comme taker.
    classified = [t for t in history if t.get("maker_or_taker") in ("maker", "taker")]
    if not classified:
        lines.append("Économie vs tout-taker : pas encore de donnée")
    else:
        maker_trades = [t for t in classified if t.get("maker_or_taker") == "maker"]
        economie = sum(
            t["entry_fee_usdc"] for t in maker_trades if t.get("entry_fee_usdc") is not None
        )
        lines.append(f"Économie vs tout-taker : <code>~{economie:.2f} USDC</code>")

        delays = [
            t["maker_fill_seconds"] for t in maker_trades
            if t.get("maker_fill_seconds") is not None
        ]
        if delays:
            median_str = _fmt_duration(timedelta(seconds=statistics.median(delays)))
            lines.append(f"Délai médian de service : <code>{median_str}</code>")
        else:
            lines.append("Délai médian de service : <code>n/d</code>")

    lines.append("Détail des poursuites en cours : /maker")
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
        lines.extend(_bloc_resultat(closed))
        lines.extend(_bloc_periodes(closed))
        lines.extend(_bloc_frais(closed))
    else:
        lines.append("\n📈 <b>Résultat net</b> : aucun trade fermé")

    lines.extend(_bloc_cycles())
    lines.extend(_bloc_positions(history))
    lines.extend(_bloc_watcher(closed))
    lines.extend(_bloc_maker(history))

    msg = "\n".join(lines)

    if len(msg) > 4000:
        msg = msg[:3970] + "\n\n⚠️ <i>(message tronqué)</i>"

    return msg
