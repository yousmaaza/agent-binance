"""Thread watchdog : alerte Telegram si une phase Claude ne progresse plus depuis 15 min."""
import os
import threading
import time

from core.telegram import send_telegram
from botlogging.cycle_logger import CycleLogger

_STALL_THRESHOLD = 900   # secondes (15 min)
_POLL_INTERVAL = 60      # secondes


class WatchdogThread:
    def __init__(self, cycle_logger: CycleLogger):
        self._logger = cycle_logger
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def _run(self):
        jsonl_path = self._logger.jsonl_path
        cycle_id = self._logger.cycle_id
        already_warned = False
        last_mtime = None

        while not self._stop.is_set():
            self._stop.wait(timeout=_POLL_INTERVAL)
            if self._stop.is_set():
                break

            try:
                mtime = os.path.getmtime(jsonl_path)
            except FileNotFoundError:
                continue
            except Exception:
                continue

            if last_mtime is not None and mtime > last_mtime:
                already_warned = False
            last_mtime = mtime

            if already_warned:
                continue

            delta = time.time() - mtime
            if delta > _STALL_THRESHOLD:
                last_phase = self._logger.read_last_phase()
                elapsed_min = int(delta // 60)
                if last_phase is not None:
                    phase_num = last_phase.get("phase", "?")
                    msg = f"⚠️ Cycle {cycle_id} bloqué en Phase {phase_num} depuis {elapsed_min} min"
                else:
                    msg = f"⚠️ Cycle {cycle_id} bloqué depuis {elapsed_min} min (aucune phase enregistrée)"
                send_telegram(msg)
                already_warned = True
