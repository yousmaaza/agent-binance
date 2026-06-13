"""Logging structuré par cycle : heartbeats JSONL + messages loguru préfixés."""
import json
from datetime import datetime, timezone

from loguru import logger

from core.env import get_cycle_phases_log_path


class CycleLogger:
    def __init__(self, cycle_id: str):
        self.cycle_id = cycle_id
        self.jsonl_path = get_cycle_phases_log_path(cycle_id)

    def heartbeat(self, phase: int, summary: str = "") -> None:
        entry = {
            "phase": phase,
            "ts": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }
        try:
            with open(self.jsonl_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"[Cycle {self.cycle_id}] heartbeat write failed: {e}")
        logger.info(f"[Cycle {self.cycle_id}] Phase {phase} {summary}")

    def info(self, msg: str) -> None:
        logger.info(f"[Cycle {self.cycle_id}] {msg}")

    def error(self, msg: str) -> None:
        logger.error(f"[Cycle {self.cycle_id}] {msg}")

    def warning(self, msg: str) -> None:
        logger.warning(f"[Cycle {self.cycle_id}] {msg}")

    def debug(self, msg: str) -> None:
        logger.debug(f"[Cycle {self.cycle_id}] {msg}")

    def read_last_phase(self) -> dict | None:
        """Retourne le dernier objet JSON valide du fichier JSONL, ou None."""
        try:
            with open(self.jsonl_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                if size == 0:
                    return None
                buf_size = min(4096, size)
                f.seek(-buf_size, 2)
                tail = f.read().decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
            return json.loads(lines[-1]) if lines else None
        except Exception:
            return None
