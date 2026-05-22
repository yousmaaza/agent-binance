"""Gestion du verrou de cycle (agent_lock.json). Expire automatiquement après 2h."""
import json
from datetime import datetime, timezone

from core.env import PROJECT_DIR

_LOCK_FILE = f"{PROJECT_DIR}/state/agent_lock.json"
_LOCK_TTL_SECONDS = 7200  # 2h


def is_locked() -> bool:
    try:
        with open(_LOCK_FILE) as f:
            lock = json.load(f)
        if not lock.get("running"):
            return False
        started = lock.get("started_at")
        if started:
            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(started.replace("Z", "+00:00"))
            ).total_seconds()
            if age < _LOCK_TTL_SECONDS:
                return True
            # Expiration automatique
            with open(_LOCK_FILE, "w") as f:
                json.dump({"running": False, "started_at": None}, f)
    except Exception:
        pass
    return False


def acquire_lock() -> None:
    with open(_LOCK_FILE, "w") as f:
        json.dump({"running": True, "started_at": datetime.now(timezone.utc).isoformat()}, f)


def release_lock() -> None:
    with open(_LOCK_FILE, "w") as f:
        json.dump({"running": False, "started_at": None}, f)
