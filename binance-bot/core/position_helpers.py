"""Helpers pour le cycle de gestion des positions ouvertes.

Importé via :
    from core.position_helpers import tg, binance, _load_config, _save_trade_history_atomic, _save_config_atomic
"""
import json
import os
import subprocess
import tempfile

from core.env import KRAKEN_CLI_PATH as _EXCHANGE_CLI, PROJECT_DIR as _PROJECT_DIR


def tg(text: str) -> None:
    """Envoie une notification Telegram via curl."""
    tok = os.environ.get("TELEGRAM_TOKEN", "")
    cid = os.environ.get("TELEGRAM_CHAT_ID", "")
    payload = json.dumps({"chat_id": cid, "text": text})
    subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"https://api.telegram.org/bot{tok}/sendMessage",
         "-H", "Content-Type: application/json",
         "-d", payload, "--max-time", "20"],
        capture_output=True,
    )


def binance(*args, _retries: int = 3) -> str:
    """Appelle kraken avec retry exponentiel."""
    import time
    for attempt in range(_retries):
        r = subprocess.run([_EXCHANGE_CLI] + list(args), capture_output=True, text=True, timeout=30)
        raw = r.stdout.strip()
        if raw.startswith("Invalid symbol"):
            raise ValueError("Invalid symbol")
        if raw and not raw.startswith("Request failed") and not raw.startswith("Usage:"):
            return raw
        if attempt < _retries - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"kraken failed after {_retries} retries: {raw[:120]}")


def _load_config(project_dir: str = "") -> dict:
    """Charge config.json et retourne un dict."""
    path = os.path.join(project_dir or _PROJECT_DIR, "config.json")
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_trade_history_atomic(data: list, path_override: str = "") -> None:
    """Écriture atomique de trade_history.json."""
    th_path = path_override or os.path.join(_PROJECT_DIR, "state", "trade_history.json")
    parent = os.path.dirname(th_path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, text=True, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, th_path)
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise e


def _save_config_atomic(data: dict, project_dir: str = "") -> None:
    """Écriture atomique de config.json."""
    cfg_path = os.path.join(project_dir or _PROJECT_DIR, "config.json")
    parent = os.path.dirname(cfg_path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, text=True, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, cfg_path)
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise e
