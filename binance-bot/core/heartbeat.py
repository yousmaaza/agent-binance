"""Heartbeat JSONL par cycle de trading.

Importé par chaque script de phase via :
    from core.heartbeat import hb, _hb_start, init as _hb_init
    _hb_init(CYCLE_ID, trigger=_trigger, project_dir=PROJECT_DIR)

Les fonctions hb() et _hb_start() utilisent l'état module-level initialisé par init().
init() DOIT être appelé une fois en tête de chaque script de phase.
"""
import datetime
import json
import os

_phase_start: dict = {}
_hb_path: str = ""
_trigger: str = "manual"


def init(cycle_id: str, trigger: str = "manual", project_dir: str = "") -> None:
    """Initialise le heartbeat pour un cycle. Appeler une fois par script de phase."""
    global _hb_path, _trigger, _phase_start
    _phase_start = {}
    _trigger = trigger
    if not project_dir:
        project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(project_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    _hb_path = os.path.join(log_dir, f"cycle_{cycle_id}_phases.jsonl")


def _hb_start(phase: int) -> None:
    """Démarre le timer d'une phase."""
    _phase_start[phase] = datetime.datetime.now(datetime.timezone.utc).timestamp()


def hb(phase: int, status: str = "ok", summary: str = "") -> None:
    """Écrit un heartbeat JSONL pour la phase donnée, avec déduplication par phase."""
    t0 = _phase_start.pop(phase, None)
    duration_s = (
        round(datetime.datetime.now(datetime.timezone.utc).timestamp() - t0, 1)
        if t0 is not None
        else -1
    )
    entry = json.dumps({
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": phase,
        "status": status,
        "duration_s": duration_s,
        "summary": summary,
        "trigger": _trigger,
    })
    lines = []
    if os.path.exists(_hb_path):
        with open(_hb_path) as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        if json.loads(ln).get("phase") != phase:
                            lines.append(ln)
                    except Exception:
                        lines.append(ln)
    lines.append(entry)
    with open(_hb_path, "w") as f:
        f.write("\n".join(lines) + "\n")
        f.flush()
