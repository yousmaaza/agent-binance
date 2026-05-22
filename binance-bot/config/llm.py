"""Configuration LLM : modèle Claude, flags CLI, chemin du prompt, patterns d'erreur ressource."""
import os

from core.env import PROJECT_DIR

# Fichier source du prompt — versionnable en git
PROMPT_FILE = os.path.join(PROJECT_DIR, "prompts", "trade_prompt.txt")

# Modèle de fallback quand le quota d'abonnement Claude Code est épuisé
CLAUDE_MODEL_FALLBACK = "claude-sonnet-4-6"

# Flags passés au sous-processus claude CLI
CLAUDE_CLI_FLAGS = [
    "--print",
    "--verbose",
    "--output-format", "stream-json",
    "--dangerously-skip-permissions",
]

# Clés de substitution dans le template (pour référence et validation)
SUBSTITUTION_KEYS = [
    "__BOT_TOKEN__",
    "__CHAT_ID__",
    "__PROJECT_DIR__",
    "__CYCLE_ID__",
    "__PROMPT_VERSION__",
]

# Patterns détectant un dépassement de quota d'abonnement → déclenche le fallback API
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
