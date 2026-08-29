"""Chargement de la config (variables d'environnement) — application indépendante du bot,
jamais de dépendance sur binance-bot/ ni sur .env du bot (#432)."""
import os


def _load_dotenv_if_present():
    """Charge un .env local (dev uniquement) — Railway injecte les env vars directement,
    ce chargement est un no-op en production s'il n'y a pas de fichier .env à côté."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


_load_dotenv_if_present()

MONGODB_URI = os.environ.get("MONGODB_URI", "").strip()
MONGODB_DB = os.environ.get("MONGODB_DB", "agent-binance").strip()

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "").strip()
DASHBOARD_SECRET_KEY = os.environ.get("DASHBOARD_SECRET_KEY", "").strip()

# Cadence du bot = 4h — un seuil de péremption à 5h laisse 1h de marge avant d'alerter (#432).
STALE_THRESHOLD_MINUTES = int(os.environ.get("DASHBOARD_STALE_THRESHOLD_MINUTES", "300"))

DASHBOARD_STATE_CACHE_TTL_S = int(os.environ.get("DASHBOARD_STATE_CACHE_TTL_S", "60"))
CYCLES_CACHE_TTL_S = int(os.environ.get("DASHBOARD_CYCLES_CACHE_TTL_S", "60"))
KRAKEN_CACHE_TTL_S = int(os.environ.get("DASHBOARD_KRAKEN_CACHE_TTL_S", "30"))

# Repli si display_timezone absent de dashboard_state.config (ex. instantané généré avant #432).
DEFAULT_DISPLAY_TIMEZONE = "Europe/Paris"

CYCLES_JOURNAL_LIMIT = int(os.environ.get("DASHBOARD_CYCLES_JOURNAL_LIMIT", "60"))

# Profondeur de la grille des cycles (#450). 30 jours = 180 créneaux de 4 h : cohérent avec la
# fiabilité 30 jours affichée juste à côté, et défilable sur mobile sans écraser les cases.
CYCLE_GRID_DAYS = int(os.environ.get("DASHBOARD_CYCLE_GRID_DAYS", "30"))
