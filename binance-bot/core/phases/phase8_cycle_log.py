"""Écriture cycle_log.jsonl et push git — extrait de phases6_8.txt Phase 8.

Lit les variables de synthèse depuis /tmp/cycle_{CYCLE_ID}_phase8_input.json :
{
  "top_score": 0, "executed": 0, "skipped": 0,
  "skip_type": null, "skip_detail": null,
  "portfolio": 0.0, "sentiment": "Neutral", "open_positions": 0
}

Exécuté par Claude en Phase 8 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase8_cycle_log.py __CYCLE_ID__

Stdout : PHASE8_CYCLE_LOG_DONE|status=ok
"""
import sys
import os
import json
import datetime
import subprocess

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

in_path = f"/tmp/cycle_{CYCLE_ID}_phase8_input.json"
with open(in_path) as f:
    inp = json.load(f)

cl_path = os.path.join(PROJECT_DIR, "state", "cycle_log.jsonl")
cl_entry = {
    "date": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "cycle_id": CYCLE_ID,
    "top_score": inp.get("top_score", 0),
    "executed": inp.get("executed", 0),
    "skipped": inp.get("skipped", 0),
    "skip_type": inp.get("skip_type"),
    "skip_detail": inp.get("skip_detail"),
    "portfolio": inp.get("portfolio", 0),
    "sentiment": inp.get("sentiment", "Neutral"),
    "open_positions": inp.get("open_positions", 0),
}

try:
    cl_lines = []
    if os.path.exists(cl_path):
        with open(cl_path) as f:
            cl_lines = [ln for ln in f.read().splitlines() if ln.strip()]
    cl_lines.append(json.dumps(cl_entry))
    if len(cl_lines) > 90:
        cl_lines = cl_lines[-90:]
    with open(cl_path, "w") as f:
        f.write("\n".join(cl_lines) + "\n")
except Exception as cl_err:
    tg(f"⚠️ cycle_log.jsonl write failed : {cl_err}")

try:
    cl_script = (
        "#!/bin/bash\n"
        "source ~/.zshrc 2>/dev/null || true\n"
        "git-perso 2>/dev/null || true\n"
        f"cd {PROJECT_DIR}\n"
        "git add state/cycle_log.jsonl\n"
        f"git diff --cached --quiet || "
        f"(git commit -m 'chore: cycle log {CYCLE_ID}' && git push origin main)\n"
    )
    script_path = f"/tmp/_cl_push_{CYCLE_ID}.sh"
    with open(script_path, "w") as f:
        f.write(cl_script)
    os.chmod(script_path, 0o755)
    cl_git = subprocess.run([script_path], capture_output=True, text=True, timeout=60)
    if cl_git.returncode != 0:
        tg(f"⚠️ cycle_log push échoué (rc={cl_git.returncode}) : {(cl_git.stderr or cl_git.stdout)[:200]}")
except Exception as cl_git_err:
    tg(f"⚠️ cycle_log push exception : {cl_git_err}")

print("PHASE8_CYCLE_LOG_DONE|status=ok")
