"""Configuration LLM : modèle Claude, flags CLI, chemin du prompt, patterns d'erreur ressource."""
import os

from core.env import PROJECT_DIR

# Fichier source du prompt — versionnable en git
PROMPT_FILE = os.path.join(PROJECT_DIR, "prompts", "trade_prompt.txt")

# Fallback model name when --model flag is not found in CLAUDE_CLI_FLAGS
FALLBACK_MODEL_NAME = "claude (défaut)"

# Flags passés au sous-processus claude CLI
# --model force Sonnet sur l'abonnement (le CLI choisit Opus par défaut sur Max)
CLAUDE_CLI_FLAGS = [
    "--print",
    "--verbose",
    "--output-format", "stream-json",
    "--dangerously-skip-permissions",
    "--model", "claude-sonnet-4-6",
]


def get_configured_model() -> str:
    """Extrait le modèle configuré depuis CLAUDE_CLI_FLAGS."""
    try:
        idx = CLAUDE_CLI_FLAGS.index("--model")
        if idx + 1 < len(CLAUDE_CLI_FLAGS):
            return CLAUDE_CLI_FLAGS[idx + 1]
    except (ValueError, IndexError):
        pass
    return FALLBACK_MODEL_NAME

# Clés de substitution dans le template (pour référence et validation)
SUBSTITUTION_KEYS = [
    "__BOT_TOKEN__",
    "__CHAT_ID__",
    "__PROJECT_DIR__",
    "__CYCLE_ID__",
    "__PROMPT_VERSION__",
]

# Patterns détectant un dépassement de quota d'abonnement → message d'erreur Telegram
RESOURCE_ERROR_PATTERNS = [
    "Credit balance is too low",
    "rate_limit_error",
    "overloaded_error",
    "Your account has hit",
    "quota exceeded",
    "This model is currently overloaded",
    "You've hit your session limit",
    "session limit",
]
