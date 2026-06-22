"""Utilitaires de temps : calcul du prochain slot 4h UTC, formatage heure locale."""
from datetime import datetime, timezone, timedelta


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
