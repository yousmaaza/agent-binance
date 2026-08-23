"""Calcul de l'heure du prochain cycle 4h — extrait de phases6_8.txt Phase 6.

Exécuté par Claude en Phase 6 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase6_next_cycle.py __CYCLE_ID__

Stdout : PHASE6_NEXT_CYCLE_DONE|next=DD/MM HH:MM (heure locale)
Output : /tmp/cycle_{CYCLE_ID}_phase6_next_output.json
"""
import sys
import os
import json

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.timing import fmt_local, next_4h_slot  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

next_slot = next_4h_slot()
next_str = fmt_local(next_slot)

print(f"PHASE6_NEXT_CYCLE_DONE|next={next_str}")
# Chemin fixe volontaire (contrat avec prompts/phases/phases6_8.txt) : neutralisation
# bandit temporaire, à lever avec le déplacement /tmp -> state/ (#392, #403)
with open(f"/tmp/cycle_{CYCLE_ID}_phase6_next_output.json", "w") as f:  # nosec B108
    json.dump({"next_str": next_str}, f)
