"""Gestion atomique et validation de state/trade_history.json."""
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone

from core.env import PROJECT_DIR
from loguru import logger


def _validate_trade_history(data):
    """Valide la structure d'un trade_history.json."""
    if not isinstance(data, list):
        raise ValueError(f"Expected list, got {type(data).__name__}")
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"Trade item must be dict, got {type(item).__name__}")
        if "coin" not in item or "status" not in item:
            raise ValueError(f"Trade missing required fields: {item}")
    return True


def load_trade_history(path=None):
    """
    Charge et valide trade_history.json.

    Returns:
        list: Liste des trades validée

    Raises:
        ValueError: Si JSON invalide
        FileNotFoundError: Si fichier absent
    """
    if path is None:
        path = os.path.join(PROJECT_DIR, "state", "trade_history.json")

    with open(path) as f:
        data = json.load(f)

    _validate_trade_history(data)
    return data


def save_trade_history(data, path=None):
    """
    Sauvegarde trade_history.json de manière atomique.

    Utilise un fichier temporaire + os.replace() pour garantir l'atomicité.

    Args:
        data: Liste des trades à sauvegarder
        path: Chemin personnalisé (défaut: PROJECT_DIR/state/trade_history.json)

    Raises:
        ValueError: Si data invalide
    """
    if path is None:
        path = os.path.join(PROJECT_DIR, "state", "trade_history.json")

    _validate_trade_history(data)

    parent_dir = os.path.dirname(path)
    os.makedirs(parent_dir, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=parent_dir, text=True, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    except Exception as e:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def validate_and_repair_boot():
    """
    Valide trade_history.json au démarrage du bot.

    Si corrompu :
    1. Crée un backup daté
    2. Réinitialise le fichier à []
    3. Retourne (False, erreur_msg)

    Returns:
        tuple: (is_valid: bool, error_msg: str or None)
    """
    path = os.path.join(PROJECT_DIR, "state", "trade_history.json")

    if not os.path.exists(path):
        logger.info("trade_history.json absent, création")
        save_trade_history([])
        return (True, None)

    try:
        with open(path) as f:
            content = f.read().strip()

        if not content:
            logger.info("trade_history.json vide, création []")
            save_trade_history([])
            return (True, None)

        data = json.loads(content)
        _validate_trade_history(data)
        logger.info("trade_history.json valide")
        return (True, None)

    except json.JSONDecodeError as e:
        error_msg = f"JSON invalide (ligne {e.lineno}): {e.msg}"
        logger.error(f"trade_history.json corrompu — {error_msg}")

        backup_path = f"{path}.bak.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        try:
            shutil.copy2(path, backup_path)
            logger.info(f"Backup créé : {backup_path}")
        except Exception as be:
            logger.error(f"Impossible de créer backup : {be}")

        save_trade_history([])
        logger.info("trade_history.json réinitialisé à []")

        return (False, error_msg)

    except (ValueError, OSError) as e:
        error_msg = str(e)
        logger.error(f"trade_history.json invalide — {error_msg}")

        backup_path = f"{path}.bak.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        try:
            shutil.copy2(path, backup_path)
            logger.info(f"Backup créé : {backup_path}")
        except Exception as be:
            logger.error(f"Impossible de créer backup : {be}")

        save_trade_history([])
        logger.info("trade_history.json réinitialisé à []")

        return (False, error_msg)
