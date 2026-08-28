"""Conversion UTC -> heure locale d'affichage (#432, cf. issues #393 et #421 : jamais d'UTC brut).

Réimplémentation autonome (pas d'import de binance-bot/core/timing.py) : le dashboard est un
déploiement indépendant, ne doit pas dépendre de la présence du dossier binance-bot/ sur Railway."""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_iso(raw: Optional[str]) -> Optional[datetime]:
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


def to_local(dt_utc: datetime, tz_name: str, fmt: str = "%d/%m %H:%M") -> str:
    try:
        local = dt_utc.astimezone(ZoneInfo(tz_name)) if tz_name else dt_utc.astimezone()
    except ZoneInfoNotFoundError:
        local = dt_utc.astimezone()
    return local.strftime(fmt)


def age_minutes(dt_utc: datetime, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    return (now - dt_utc).total_seconds() / 60
