"""Helpers partagés pour les scripts Python générés par les cycles de trading.

Importé par chaque script de phase via :
    from core.trade_helpers import tg, binance, _load_config, _save_trade_history_atomic
"""
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from core.env import KRAKEN_CLI_PATH as _EXCHANGE_CLI, PROJECT_DIR as _PROJECT_DIR


def tg(text: str) -> None:
    """Envoie une notification Telegram via curl (jamais urllib — cf. CLAUDE.md)."""
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
    """Appelle kraken avec retry exponentiel. Lève ValueError si symbole invalide."""
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
    """Charge config.json et retourne un dict. Retourne {} en cas d'erreur."""
    path = os.path.join(project_dir or _PROJECT_DIR, "config.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}


def _save_json_atomic(data: dict | list, path: str) -> None:
    """Écriture atomique via fichier temporaire + os.replace."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, text=True, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise e


def _save_trade_history_atomic(data: list, path_override: str = "") -> None:
    """Écriture atomique de trade_history.json via fichier temporaire + os.replace."""
    th_path = path_override or os.path.join(_PROJECT_DIR, "state", "trade_history.json")
    _save_json_atomic(data, th_path)


def _save_config_atomic(data: dict, project_dir: str = "") -> None:
    """Écriture atomique de config.json via fichier temporaire + os.replace."""
    cfg_path = os.path.join(project_dir or _PROJECT_DIR, "config.json")
    _save_json_atomic(data, cfg_path)


def _maker_pending_orders_path(project_dir: str = "") -> str:
    return os.path.join(project_dir or _PROJECT_DIR, "state", "maker_pending_orders.json")


def load_maker_pending_orders(project_dir: str = "") -> list:
    """Charge state/maker_pending_orders.json (#388) — ordres limite d'entrée en attente,
    survit à un redémarrage du bot. Retourne [] si absent/corrompu."""
    try:
        with open(_maker_pending_orders_path(project_dir)) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_maker_pending_orders(data: list, project_dir: str = "") -> None:
    """Écriture atomique de state/maker_pending_orders.json (#388)."""
    _save_json_atomic(data, _maker_pending_orders_path(project_dir))


def compute_net_pnl(entry_price: float, exit_price: float, qty: float, entry_fee_usdc: float, exit_fee_usdc: float) -> dict:
    """PnL net = PnL brut (diff de prix) moins les frais Kraken entrée+sortie (#382).

    pnl_pct est le pourcentage NET (pnl_usdc rapporté au notionnel d'entrée), en miroir de
    pnl_usdc — jamais un pourcentage brut à côté d'un montant net (signes qui se contredisent).
    pnl_gross_pct conserve l'ancien calcul brut, en miroir de pnl_gross_usdc.
    """
    pnl_gross_usdc = (exit_price - entry_price) * qty
    fees_usdc = entry_fee_usdc + exit_fee_usdc
    pnl_usdc = pnl_gross_usdc - fees_usdc
    pnl_gross_pct = (exit_price - entry_price) / entry_price * 100 if entry_price else 0.0
    notional = entry_price * qty
    pnl_pct = pnl_usdc / notional * 100 if notional else 0.0
    return {
        "pnl_gross_usdc": pnl_gross_usdc,
        "fees_usdc": fees_usdc,
        "pnl_usdc": pnl_usdc,
        "pnl_gross_pct": pnl_gross_pct,
        "pnl_pct": pnl_pct,
    }


def maker_or_taker_from_ordertype(ordertype: str, post_only: bool = False) -> str | None:
    """Dérive maker/taker depuis descr.ordertype de la réponse query-orders de l'ordre d'entrée.

    market et stop-loss (une fois déclenché) sont toujours exécutés en taker chez Kraken. Un ordre
    limit posé avec le drapeau post-only (#388) est garanti maker : Kraken rejette la pose s'il
    croiserait le carnet au lieu de l'exécuter en taker, donc tout remplissage constaté est un
    maker par construction — post_only=True sur un ordertype "limit" retourne "maker". Pour un
    limit sans post_only (pas utilisé actuellement par le bot), le statut n'est pas déductible
    depuis ordertype seul (le champ "maker" n'existe que côté query-trades, pas query-orders) —
    retourne None plutôt qu'une valeur affirmative fausse ; #389 (commande /maker) doit gérer ce None.
    """
    if ordertype in ("market", "stop-loss"):
        return "taker"
    if ordertype == "limit" and post_only:
        return "maker"
    return None


def log_phase0_event(cycle_id: str, phase: str, coin: str, action: str, details: dict | None = None) -> None:
    """Écrit un événement structuré (JSON) dans logs/phase0_events.jsonl pour traçabilité."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "phase": phase,
        "coin": coin,
        "action": action,
        "details": details or {},
    }
    logs_dir = os.path.join(_PROJECT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, "phase0_events.jsonl")
    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(event) + "\n")
    except (IOError, OSError):
        pass
