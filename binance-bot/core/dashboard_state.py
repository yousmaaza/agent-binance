"""Dérivation des slices `dashboard_state` à partir de `trade_history` (#431, #500).

Extrait de `core/phases/phase7_mongo.py` (#500) : ce dernier est un script de phase qui
s'exécute au chargement (lit `sys.argv`, ouvre un fichier `/tmp`), donc pas importable proprement
par les watchers. Module partagé, consommé à la fois par la Phase 7 (document complet en fin de
cycle) et par `core/maker_watcher.py`, `core/maker_exit_watcher.py`, `core/tp_watcher.py`
(republication de `open_positions`/`closed_trades`/`financials` à chaque modification de
`trade_history` entre deux cycles, sans attendre les 4h du cycle suivant)."""
from datetime import datetime, timedelta, timezone

from loguru import logger

from core.timing import parse_dt
from storage.mongo import mongo_repo

CLOSED_TRADES_LIMIT = 200  # borne le document : 87 ventes en 4 mois, la marge est large


def _pnl(t: dict) -> float:
    return t.get("pnl_usdc") or 0


def _open_positions(history: list) -> list:
    return [
        {
            "coin": t.get("coin"),
            "entry_price": t.get("entry_price"),
            "stop_price": t.get("stop_price"),
            "tp_price": t.get("tp_price"),
            "quantity": t.get("quantity"),
            "opened_at": t.get("date"),
            "entry_fee_usdc": t.get("entry_fee_usdc"),
            "maker_or_taker": t.get("maker_or_taker"),
        }
        for t in history if t.get("status") == "open"
    ]


def _brut_frais_net(trades: list) -> dict:
    """net = pnl_usdc (toujours connu). brut est dérivé de net + frais connus : pour les trades
    sans fees_usdc (garde-fou de cohérence du backfill, ex. SYN/PENDLE), cela suppose des frais
    nuls sur ces trades précis, sans jamais fabriquer de frais estimés (même logique que /perf)."""
    net = sum(_pnl(t) for t in trades)
    frais = sum(f for t in trades if (f := t.get("fees_usdc")) is not None)
    return {"gross_usdc": net + frais, "fees_usdc": frais, "net_usdc": net, "count": len(trades)}


def _equity_curve(closed: list) -> list:
    dated = sorted(
        (
            (dt, _pnl(t)) for t in closed
            if (dt := parse_dt(t.get("exit_date"))) is not None
        ),
        key=lambda pair: pair[0],
    )
    curve: list = []
    cumulative = 0.0
    last_day = None
    for dt, pnl in dated:
        cumulative += pnl
        day = dt.strftime("%Y-%m-%d")
        if day == last_day:
            curve[-1]["cumulative_pnl_usdc"] = round(cumulative, 4)
        else:
            curve.append({"date": day, "cumulative_pnl_usdc": round(cumulative, 4)})
            last_day = day
    return curve


def _financials(closed: list) -> dict:
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)
    buckets = {"0_7d": [], "8_30d": [], "30d_plus": []}
    for t in closed:
        dt = parse_dt(t.get("exit_date"))
        if dt is None:
            continue
        if dt >= cutoff_7d:
            buckets["0_7d"].append(t)
        elif dt >= cutoff_30d:
            buckets["8_30d"].append(t)
        else:
            buckets["30d_plus"].append(t)

    pnl_by_coin: dict = {}
    for t in closed:
        c = t.get("coin", "?")
        pnl_by_coin[c] = pnl_by_coin.get(c, 0) + _pnl(t)

    close_reason_counts: dict = {}
    for t in closed:
        reason = t.get("close_reason") or "unknown"
        close_reason_counts[reason] = close_reason_counts.get(reason, 0) + 1

    global_stats = _brut_frais_net(closed)
    global_stats["wins"] = sum(1 for t in closed if _pnl(t) > 0)
    global_stats["losses"] = sum(1 for t in closed if _pnl(t) < 0)
    global_stats["trades_without_fees"] = sum(1 for t in closed if t.get("fees_usdc") is None)

    return {
        "global": global_stats,
        "by_period": {k: _brut_frais_net(v) for k, v in buckets.items()},
        "pnl_by_coin": pnl_by_coin,
        "close_reason_counts": close_reason_counts,
        # Courbe d'équité réduite à un point par jour (dernier cumul du jour) plutôt qu'aux 84
        # trades intégraux : suffisant pour un tracé lisible, sans gonfler le document (#431).
        "equity_curve": _equity_curve(closed),
    }


def _closed_trades(closed: list, limit: int = CLOSED_TRADES_LIMIT) -> list:
    """Les ventes récentes, pour l'onglet Ventes du dashboard (#455).

    Projection volontairement étroite : le dashboard n'a pas besoin des identifiants d'ordres
    ni des prix de stop. Les indicateurs de fiabilité (`fees_estimated`, frais absents) sont
    transmis tels quels — masquer qu'un frais est estimé donnerait au net une précision qu'il
    n'a pas."""
    rows = []
    for trade in closed:
        exited = parse_dt(trade.get("exit_date"))
        entered = parse_dt(trade.get("date"))
        rows.append({
            "coin": trade.get("coin"),
            "entry_date": trade.get("date"),
            "exit_date": trade.get("exit_date"),
            "hold_hours": round((exited - entered).total_seconds() / 3600, 1)
            if exited and entered else None,
            "entry_price": trade.get("entry_price"),
            "exit_price": trade.get("exit_price"),
            # cible et stop : nécessaires pour détecter une sortie qui n'a pas suivi le plan
            # (cible franchie sans que le TP déclenche, sortie TP sous sa cible) — #455
            "tp_price": trade.get("tp_price"),
            "stop_price": trade.get("stop_price"),
            "quantity": trade.get("quantity"),
            "pnl_gross_usdc": trade.get("pnl_gross_usdc"),
            "fees_usdc": trade.get("fees_usdc"),
            "pnl_usdc": trade.get("pnl_usdc"),
            "close_reason": trade.get("close_reason"),
            "cycle_id": trade.get("cycle_id"),
            "maker_or_taker": trade.get("maker_or_taker"),
            "exit_maker_or_taker": trade.get("exit_maker_or_taker"),
            "exit_fee_usdc": trade.get("exit_fee_usdc"),
            "fees_estimated": bool(trade.get("fees_estimated")),
        })
    rows.sort(key=lambda r: r.get("exit_date") or "", reverse=True)
    return rows[:limit]


def publish_trade_history_slices(history: list, label: str) -> bool:
    """Republie `open_positions`/`closed_trades`/`financials` dans `dashboard_state` (#500),
    appelée par les watchers juste après une sauvegarde de `trade_history` — sans attendre le
    prochain passage de la Phase 7 (jusqu'à 4h). Mêmes garde-fous que
    `MongoRepository.save_maker_pending_orders` (#498) : écriture partielle, sans `upsert`,
    aucune exception remontée dans la boucle du watcher appelant (`label` identifie l'appelant
    dans les logs, ex. "Maker Watcher"). Confort d'affichage seulement : ces threads posent de
    vrais ordres, leur robustesse prime sur l'affichage."""
    closed = [t for t in history if t.get("status") == "closed"]
    try:
        return mongo_repo.save_trade_history_slices(
            _open_positions(history), _closed_trades(closed), _financials(closed),
        )
    except Exception as e:
        logger.warning(f"[{label}] Publication dashboard_state échouée : {e}")
        return False
