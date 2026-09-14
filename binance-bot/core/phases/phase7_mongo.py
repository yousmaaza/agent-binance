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
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.dashboard_state import _closed_trades, _financials, _open_positions  # noqa: E402
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
    "display_timezone", "maker_max_concession_pct", "maker_timeout_seconds",
]


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


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
        "closed_trades": _closed_trades(closed),
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
