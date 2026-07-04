"""Utilitaires de temps : calcul du prochain slot 4h UTC, formatage heure locale."""
from datetime import datetime, timezone, timedelta
from typing import Optional


def next_4h_slot() -> datetime:
    """Prochain slot 4h UTC + 5 min (aligné sur clôtures TradingView : 00:05, 04:05, ..., 20:05)."""
    now = datetime.now(timezone.utc)
    slot_hour = (now.hour // 4) * 4
    nxt = now.replace(hour=slot_hour, minute=5, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(hours=4)
    return nxt


def next_1h_slot() -> datetime:
    """Prochain slot horaire à :05 UTC, en sautant les slots 4h (00:05, 04:05, 08:05, 12:05, 16:05, 20:05)."""
    now = datetime.now(timezone.utc)
    nxt = now.replace(minute=5, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(hours=1)
    if nxt.hour % 4 == 0:
        nxt += timedelta(hours=1)
    return nxt


def fmt_local(dt_utc: datetime) -> str:
    """Convertit un datetime UTC en heure locale lisible, ex: '22/05 14:05 (heure locale)'."""
    local = dt_utc.astimezone()
    return local.strftime("%d/%m %H:%M") + " (heure locale)"


def parse_dt(raw: Optional[str]) -> Optional[datetime]:
    """Parse un timestamp ISO 8601 en datetime aware UTC. Gère le suffixe +00:00Z redondant."""
    if not raw:
        return None
    try:
        cleaned = raw.rstrip("Z") if raw.endswith("+00:00Z") else raw
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
