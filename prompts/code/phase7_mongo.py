"""Persistance du cycle en MongoDB — extrait de phases6_8.txt Phase 7.

Lit le document à persister depuis /tmp/cycle_{CYCLE_ID}_phase7_input.json :
{"doc": {...}}

Exécuté par Claude en Phase 7 :
    python3 __PROJECT_DIR__/prompts/code/phase7_mongo.py __CYCLE_ID__

Stdout : PHASE7_MONGO_DONE|status=ok ou PHASE7_MONGO_DONE|status=skipped
"""
import sys
import os
import json

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

in_path = f"/tmp/cycle_{CYCLE_ID}_phase7_input.json"
with open(in_path) as f:
    inp = json.load(f)

doc = inp.get("doc", {})
uri = os.environ.get("MONGODB_URI", "").strip()

if not uri:
    print("PHASE7_MONGO_DONE|status=skipped")
    sys.exit(0)

try:
    from pymongo import MongoClient
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[os.environ.get("MONGODB_DB", "agent-binance")]
    db.cycles.update_one({"_id": CYCLE_ID}, {"$set": doc}, upsert=True)
    client.close()
    print("PHASE7_MONGO_DONE|status=ok")
except Exception as e:
    tg(f"⚠️ Mongo write failed : {e}")
    print(f"PHASE7_MONGO_DONE|status=error|{e}")
    sys.exit(1)
