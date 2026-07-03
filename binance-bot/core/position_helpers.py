"""Helpers pour le cycle de gestion des positions ouvertes.

Importé via :
    from core.position_helpers import tg, binance, _load_config, _save_trade_history_atomic, _save_config_atomic

Security note: subprocess is used intentionally for curl calls (Telegram notifications).
- curl via subprocess is preferred over urllib to avoid DNS resolution issues on macOS
  (IPv6 DNS resolution failure in nohup context — see CLAUDE.md section 4).
- subprocess.run() is always called with a list of arguments (safe), never with shell=True
  or user-controlled strings, preventing command injection.
"""
import json
import os
import subprocess
import tempfile

from loguru import logger

from core.env import KRAKEN_CLI_PATH as _EXCHANGE_CLI, PROJECT_DIR as _PROJECT_DIR


def tg(text: str) -> None:
    """Envoie une notification Telegram via curl. Logue les erreurs en cas d'échec.

    Uses subprocess.run() with a list of arguments (safe, no command injection).
    curl is preferred over urllib to avoid DNS resolution failures on macOS.
    """
    tok = os.environ.get("TELEGRAM_TOKEN", "")
    cid = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not tok:
        logger.warning("tg(): TELEGRAM_TOKEN vide, notification non envoyée")
        return
    if not cid:
        logger.warning("tg(): TELEGRAM_CHAT_ID vide, notification non envoyée")
        return

    payload = json.dumps({"chat_id": cid, "text": text})
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             f"https://api.telegram.org/bot{tok}/sendMessage",
             "-H", "Content-Type: application/json",
             "-d", payload, "--max-time", "20"],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if result.returncode != 0:
            logger.error(f"tg(): curl exit code {result.returncode}, stderr: {result.stderr[:200]}")
        else:
            try:
                resp = json.loads(result.stdout) if result.stdout else {}
                if not resp.get("ok"):
                    error_msg = resp.get("description", "unknown error")
                    logger.error(f"tg(): Telegram API error: {error_msg}")
            except json.JSONDecodeError:
                logger.warning(f"tg(): curl succeeded but response is not JSON: {result.stdout[:200]}")
    except subprocess.TimeoutExpired:
        logger.error("tg(): curl timeout (25s)")
    except Exception as e:
        logger.error(f"tg(): unexpected error: {e}")


def binance(*args, _retries: int = 3) -> str:
    """Appelle kraken avec retry exponentiel.

    Uses subprocess.run() with a list of arguments (safe, no command injection).
    """
    import time

    def _is_invalid_symbol(output: str) -> bool:
        return output.startswith("Invalid symbol")

    def _is_success(output: str) -> bool:
        return output and not output.startswith("Request failed") and not output.startswith("Usage:")

    for attempt in range(_retries):
        # subprocess.run with list of arguments is safe (no shell=True, no string interpolation)
        r = subprocess.run([_EXCHANGE_CLI] + list(args), capture_output=True, text=True, timeout=30)
        raw = r.stdout.strip()

        if _is_invalid_symbol(raw):
            raise ValueError("Invalid symbol")

        if _is_success(raw):
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
