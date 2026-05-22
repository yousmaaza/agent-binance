"""Bootstrap : chargement .env, constantes globales, setup loguru, chargement du prompt."""
import hashlib
import os

from loguru import logger

logger.remove(0)  # évite la double écriture via nohup 2>&1


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


_load_env()

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
MONGO_URI = os.environ.get("MONGODB_URI", "").strip()
MONGO_DB = os.environ.get("MONGODB_DB", "agent-binance").strip()

if not TOKEN or not CHAT_ID:
    logger.warning("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant dans .env")

# Création des dossiers de logs
os.makedirs(f"{LOGS_DIR}/stdout", exist_ok=True)
os.makedirs(f"{LOGS_DIR}/stderr", exist_ok=True)

logger.add(
    f"{LOGS_DIR}/bot_{{time:YYYY-MM-DD}}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
)
logger.add(
    f"{PROJECT_DIR}/state/daemon.log",
    rotation="10 MB",
    retention=5,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
)

# Chargement du prompt depuis prompts/trade_prompt.txt
_PROMPT_FILE = os.path.join(PROJECT_DIR, "prompts", "trade_prompt.txt")
with open(_PROMPT_FILE) as _f:
    _TRADE_PROMPT_TEMPLATE = _f.read()

# SHA1 calculé sur le template brut — stable entre cycles
PROMPT_VERSION = hashlib.sha1(_TRADE_PROMPT_TEMPLATE.encode(), usedforsecurity=False).hexdigest()[:8]

# Substitutions statiques (TOKEN, CHAT_ID, PROJECT_DIR) — effectuées une seule fois au démarrage
TRADE_PROMPT = (
    _TRADE_PROMPT_TEMPLATE
    .replace("__BOT_TOKEN__", TOKEN)
    .replace("__CHAT_ID__", CHAT_ID)
    .replace("__PROJECT_DIR__", PROJECT_DIR)
)
