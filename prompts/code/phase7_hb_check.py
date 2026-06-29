"""Vérification complétude heartbeats phases 0-6 — extrait de phases6_8.txt Phase 7.

Exécuté par Claude en Phase 7 avant hb(7) :
    python3 __PROJECT_DIR__/prompts/code/phase7_hb_check.py __CYCLE_ID__

Stdout : PHASE7_HB_CHECK_DONE|missing=[...]
"""
import sys
import os
import json

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg  # noqa: E402
from core.heartbeat import hb, init as _hb_init  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

_hb_init(CYCLE_ID, project_dir=PROJECT_DIR)

hb_check_path = os.path.join(PROJECT_DIR, "logs", f"cycle___{CYCLE_ID}___phases.jsonl")
hb_check_phases = set()
try:
    if os.path.exists(hb_check_path):
        with open(hb_check_path) as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        hb_check_phases.add(entry.get("phase"))
                    except Exception:
                        pass
except Exception:
    pass

missing_phases = [p for p in range(0, 7) if p not in hb_check_phases]
if missing_phases:
    tg(f"⚠️ Heartbeats manquants détectés : phases {missing_phases}. Complétude garantie...")
    for p in missing_phases:
        hb(p, status="recovered", summary=f"Heartbeat manquant pour phase {p}, ajouté en Phase 7")

print(f"PHASE7_HB_CHECK_DONE|missing={missing_phases}")
