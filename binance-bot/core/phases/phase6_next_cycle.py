"""Calcul de l'heure du prochain cycle 4h — extrait de phases6_8.txt Phase 6.

Exécuté par Claude en Phase 6 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase6_next_cycle.py __CYCLE_ID__

Stdout : PHASE6_NEXT_CYCLE_DONE|next=DD/MM HH:MM (heure locale)
Output : /tmp/cycle_{CYCLE_ID}_phase6_next_output.json
"""
import sys
import os
import json
import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

now = datetime.datetime.now(datetime.timezone.utc)
slot_h = (now.hour // 4) * 4
next_slot = now.replace(hour=slot_h, minute=5, second=0, microsecond=0)
if next_slot <= now:
    next_slot += datetime.timedelta(hours=4)
next_str = next_slot.astimezone().strftime("%d/%m %H:%M") + " (heure locale)"

print(f"PHASE6_NEXT_CYCLE_DONE|next={next_str}")
with open(f"/tmp/cycle_{CYCLE_ID}_phase6_next_output.json", "w") as f:
    json.dump({"next_str": next_str}, f)
