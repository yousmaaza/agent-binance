"""Bootstrap : chargement .env, constantes globales, setup loguru, chargement du prompt."""
import hashlib
import os
import shutil

from loguru import logger

logger.remove(0)  # évite la double écriture via nohup 2>&1

# Clés qui ne doivent jamais être injectées dans le processus — on force l'abonnement Claude
KEYS_NEVER_LOAD = {"ANTHROPIC_API_KEY"}


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    if key in KEYS_NEVER_LOAD:
                        continue  # ne jamais injecter cette clé dans le processus
                    os.environ.setdefault(key, val.strip())


_load_env()

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KRAKEN_CLI_PATH = shutil.which("kraken") or os.path.expanduser("~/.cargo/bin/kraken")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
MONGO_URI = os.environ.get("MONGODB_URI", "").strip()
MONGO_DB = os.environ.get("MONGODB_DB", "agent-binance").strip()

def get_cycle_phases_log_path(cycle_id: str) -> str:
    return os.path.join(LOGS_DIR, f"cycle_{cycle_id}_phases.jsonl")

if not TOKEN or not CHAT_ID:
    logger.warning("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant dans .env")

# Création des dossiers de logs
os.makedirs(f"{LOGS_DIR}/stdout", exist_ok=True)
os.makedirs(f"{LOGS_DIR}/stderr", exist_ok=True)

# Initialisation du cycle log JSONL si absent
_cycle_log_path = os.path.join(PROJECT_DIR, "state", "cycle_log.jsonl")
if not os.path.exists(_cycle_log_path):
    with open(_cycle_log_path, "w"):
        pass

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

def assemble_prompt(prompts_dir: str = "") -> str:
    """Assemble le prompt de trading depuis les sous-fichiers par phase.

    Ordre : header (trade_prompt.txt) + api_reference + phase0..phase5 + phases6_8.
    PROMPT_VERSION est calculé sur le contenu assemblé final.
    """
    if not prompts_dir:
        prompts_dir = os.path.join(PROJECT_DIR, "prompts")
    parts = [
        os.path.join(prompts_dir, "trade_prompt.txt"),
        os.path.join(prompts_dir, "shared", "api_reference.txt"),
        os.path.join(prompts_dir, "phases", "phase0_snapshot.txt"),
        os.path.join(prompts_dir, "phases", "phase1_scan.txt"),
        os.path.join(prompts_dir, "phases", "phase2_analysis.txt"),
        os.path.join(prompts_dir, "phases", "phase3_scoring.txt"),
        os.path.join(prompts_dir, "phases", "phase4_sizing.txt"),
        os.path.join(prompts_dir, "phases", "phase5_execution.txt"),
        os.path.join(prompts_dir, "phases", "phases6_8.txt"),
    ]
    return "\n".join(open(p).read() for p in parts)


# Assemblage du prompt de trading depuis les sous-fichiers par phase
_TRADE_PROMPT_TEMPLATE = assemble_prompt(os.path.join(PROJECT_DIR, "prompts"))

# Chargement du prompt position depuis prompts/position_prompt.txt
_POSITION_PROMPT_FILE = os.path.join(PROJECT_DIR, "prompts", "position_prompt.txt")
with open(_POSITION_PROMPT_FILE) as _f:
    _POSITION_PROMPT_TEMPLATE = _f.read()

# SHA1 du prompt assemblé pour versionner (fingerprint non-cryptographique, stable entre cycles)
# usedforsecurity=False supprime le warning Bandit B324 (usage déclaré non-cryptographique)
PROMPT_VERSION = hashlib.sha1(_TRADE_PROMPT_TEMPLATE.encode(), usedforsecurity=False).hexdigest()[:8]

# Substitutions statiques (TOKEN, CHAT_ID, PROJECT_DIR, KRAKEN_CLI_PATH) — effectuées une seule fois au démarrage
TRADE_PROMPT = (
    _TRADE_PROMPT_TEMPLATE
    .replace("__BOT_TOKEN__", TOKEN)
    .replace("__CHAT_ID__", CHAT_ID)
    .replace("__PROJECT_DIR__", PROJECT_DIR)
    .replace("__KRAKEN_CLI_PATH__", KRAKEN_CLI_PATH)
)

POSITION_PROMPT = (
    _POSITION_PROMPT_TEMPLATE
    .replace("__BOT_TOKEN__", TOKEN)
    .replace("__CHAT_ID__", CHAT_ID)
    .replace("__PROJECT_DIR__", PROJECT_DIR)
    .replace("__KRAKEN_CLI_PATH__", KRAKEN_CLI_PATH)
)
