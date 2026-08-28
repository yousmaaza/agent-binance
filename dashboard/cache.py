"""Cache TTL en mémoire — évite de solliciter MongoDB/Kraken à chaque rafraîchissement (#432).

Volontairement basique (process-local, pas de Redis) : un seul dyno web sur Railway pour ce
dashboard, un cache partagé entre requêtes n'apporte rien de plus ici."""
import time
from typing import Any, Callable


class TTLCache:
    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}

    def get_or_set(self, key: str, ttl_s: int, fn: Callable[[], Any]) -> Any:
        now = time.monotonic()
        cached = self._store.get(key)
        if cached is not None and now - cached[0] < ttl_s:
            return cached[1]
        value = fn()
        self._store[key] = (now, value)
        return value

    def clear(self):
        self._store.clear()


cache = TTLCache()
