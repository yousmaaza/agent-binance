"""Persistance du cycle en MongoDB — extrait de phases6_8.txt Phase 7.

Lit le document à persister depuis /tmp/cycle_{CYCLE_ID}_phase7_input.json :
{"doc": {...}}

En plus du document de cycle (collection `cycles`), reconstruit à chaque exécution un document
unique dans `dashboard_state` (#431) à partir des fichiers state/ et config.json — un instantané
DÉRIVÉ pour un dashboard externe, jamais une source de vérité : state/trade_history.json reste
la référence, en cas de divergence c'est le fichier qui fait foi.

Exécuté par Claude en Phase 7 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase7_mongo.py __CYCLE_ID__

Stdout : PHASE7_MONGO_DONE|status=ok ou PHASE7_MONGO_DONE|status=skipped
"""
import sys
import os
import json
from datetime import datetime, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.timing import parse_dt  # noqa: E402
from core.trade_helpers import tg, _load_config, load_maker_pending_orders  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

# Chemin fixe volontaire (contrat avec prompts/phases/phases6_8.txt) : neutralisation
# bandit temporaire, à lever avec le déplacement /tmp -> state/ (#392, #403)
in_path = f"/tmp/cycle_{CYCLE_ID}_phase7_input.json"  # nosec B108
with open(in_path) as f:
    inp = json.load(f)

doc = inp.get("doc", {})
uri = os.environ.get("MONGODB_URI", "").strip()

if not uri:
    print("PHASE7_MONGO_DONE|status=skipped")
    sys.exit(0)

TRADE_HISTORY_PATH = os.path.join(PROJECT_DIR, "state", "trade_history.json")
MAKER_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "maker_watcher_state.json")
TP_WATCHER_STATE_PATH = os.path.join(PROJECT_DIR, "state", "tp_watcher_state.json")

# Clés de config.json qui pilotent le comportement (#431) — cf. issue pour la liste exacte.
# display_timezone ajoutée pour #432 : le dashboard en a besoin pour convertir les heures affichées.
_CONFIG_KEYS = [
    "min_signal_score", "min_signal_score_degraded", "rsi_zone_min", "rsi_zone_max",
    "max_open_positions", "reward_risk_ratio", "fee_round_trip_pct", "max_tp_pct",
    "max_spread_pct", "risk_per_trade_pct", "daily_loss_limit_pct", "min_profit_pct_take",
    "display_timezone",
]


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


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


def _build_dashboard_state(cycle_id: str, cycle_status: str) -> dict:
    history = _load_json(TRADE_HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []
    closed = [t for t in history if t.get("status") == "closed"]

    full_config = _load_config(PROJECT_DIR)
    active_config = {k: full_config.get(k) for k in _CONFIG_KEYS}

    return {
        "_id": "current",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "cycle_status": cycle_status,
        "open_positions": _open_positions(history),
        "financials": _financials(closed),
        "watchers": {
            "maker_watcher": _load_json(MAKER_WATCHER_STATE_PATH, {}),
            "tp_watcher": _load_json(TP_WATCHER_STATE_PATH, {}),
            "maker_pending_orders": load_maker_pending_orders(PROJECT_DIR),
        },
        "config": active_config,
    }


try:
    from pymongo import MongoClient
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[os.environ.get("MONGODB_DB", "agent-binance")]
    db.cycles.update_one({"_id": CYCLE_ID}, {"$set": doc}, upsert=True)
    dashboard_doc = _build_dashboard_state(CYCLE_ID, doc.get("status", "unknown"))
    db.dashboard_state.update_one({"_id": "current"}, {"$set": dashboard_doc}, upsert=True)
    client.close()
    print("PHASE7_MONGO_DONE|status=ok")
except Exception as e:
    tg(f"⚠️ Mongo write failed : {e}")
    print(f"PHASE7_MONGO_DONE|status=error|{e}")
    sys.exit(1)
