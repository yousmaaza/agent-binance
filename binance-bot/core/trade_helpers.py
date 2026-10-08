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
        check=False,
    )


def binance(*args, _retries: int = 3) -> str:
    """Appelle kraken avec retry exponentiel. Lève ValueError si symbole invalide."""
    for attempt in range(_retries):
        r = subprocess.run([_EXCHANGE_CLI] + list(args), capture_output=True, text=True, timeout=30, check=False)
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


# Actifs historiques Kraken exposés sous un code préfixé dans `kraken balance` (#476) — liste
# fermée mais arbitraire (SOL, ADA, LINK, BNB, TRUMP n'ont pas de préfixe), donc constatée plutôt
# que déduite d'une règle générale. Constatée via `kraken assets -o json` en production (#476 review)
# -- exclut volontairement XAUT/XION/XTER/XU3O8 (actifs qui s'appellent réellement ainsi, pas des
# formes préfixées) et XBT.M/XTZ.S (variantes de staking). BTC et DOGE ajoutés en plus de XBT/XDG :
# le bot a utilisé les deux nominations au fil du temps (trades anciens vs récents).
KRAKEN_ASSET_ALIASES = {
    "ETC": "XETC",
    "ETH": "XETH",
    "LTC": "XLTC",
    "MLN": "XMLN",
    "REP": "XREP",
    "XBT": "XXBT",
    "BTC": "XXBT",
    "XDG": "XXDG",
    "DOGE": "XXDG",
    "XLM": "XXLM",
    "XMR": "XXMR",
    "XRP": "XXRP",
    "ZEC": "XZEC",
}


def kraken_coin_balance(balance: dict, coin: str) -> float:
    """Résout le solde d'un coin dans la réponse `kraken balance -o json` : essaie la clé brute
    (coin), puis l'alias Kraken connu (KRAKEN_ASSET_ALIASES). Lève KeyError si aucune des deux
    n'existe -- un actif absent du solde ne doit jamais être confondu avec un solde réellement nul
    (#476, cf. bug ETH/XBT/XRP/XDG jamais vendus)."""
    if coin in balance:
        return float(balance[coin] or 0)
    alias = KRAKEN_ASSET_ALIASES.get(coin)
    if alias and alias in balance:
        return float(balance[alias] or 0)
    raise KeyError(coin)


def initial_stop_price(trade: dict, fee_round_trip_pct: float = 0.009) -> float:
    """Stop d'origine d'un trade (#513) : indispensable une fois le stop courant remonté au
    break-even ou suivi, sinon la distance de stop (trailing, recalibrage TP) tombe à zéro.

    Priorité : champ initial_stop_price (posé à l'entrée) ; sinon reconstruction depuis
    risk_usdc (risk = entry x qty x (stop_distance + frais), cf. phase4_sizing) ; sinon stop courant.
    """
    stored = trade.get("initial_stop_price")
    if stored:
        return float(stored)
    entry = float(trade.get("entry_price") or 0)
    qty = float(trade.get("quantity") or 0)
    risk = trade.get("risk_usdc")
    if risk and entry > 0 and qty > 0:
        sd = float(risk) / (entry * qty) - fee_round_trip_pct
        if 0 < sd < 0.5:
            return entry * (1 - sd)
    return float(trade["stop_price"])


RESISTANCE_TP_FACTOR = 0.98
CANDLE_4H_SECONDS = 4 * 3600


def resistance_from_candles(candles: list, lookback: int, now_ts: float | None = None) -> float | None:
    """Plus haut des `lookback` dernières bougies 4h CLÔTURÉES (#516). La bougie en cours (ouverte
    il y a moins de 4h) est exclue : son plus haut n'est pas encore figé. Format Kraken ohlc :
    [open_time, open, high, low, close, vwap, volume, count]. None si aucune bougie exploitable."""
    now_ts = time.time() if now_ts is None else now_ts
    closed = [c for c in candles if float(c[0]) + CANDLE_4H_SECONDS <= now_ts]
    highs = [float(c[2]) for c in closed[-lookback:]]
    return max(highs) if highs else None


def fetch_resistance_4h(coin: str, lookback: int = 30) -> float | None:
    """Résistance de plafonnement de la cible depuis les bougies 4h Kraken (#516). Retourne None si
    Kraken est indisponible ou si la réponse est inexploitable : l'appelant garde alors le TP existant
    (recalibrage) ou ne plafonne que par max_tp_pct (entrée) — jamais d'erreur bloquante."""
    pair = f"{coin}USDC"
    try:
        raw = binance("ohlc", pair, "--interval", "240", "-o", "json", _retries=2)
        return resistance_from_candles(json.loads(raw).get(pair, []), lookback)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError, KeyError, IndexError, TypeError):
        return None


CANDLE_1D_SECONDS = 24 * 3600


def ema_last(values: list, n: int) -> float | None:
    """Dernière valeur de l'EMA(n) (alpha 2/(n+1), amorcée sur la première valeur, comme le rejeu
    scripts/stop_trend_replay.py). None s'il y a moins de n valeurs : EMA pas encore fiable."""
    if len(values) < n:
        return None
    alpha = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e += alpha * (v - e)
    return e


def fetch_daily_trend(coin: str, ema_days: int = 100, now_ts: float | None = None) -> tuple[float, float] | None:
    """(clôture 1d, EMA(ema_days) 1d) d'un coin depuis les bougies 1d Kraken (#521). La bougie du jour
    en cours est exclue : sa clôture n'est pas figée. None si Kraken est indisponible, si la réponse
    est inexploitable ou s'il y a moins de ema_days bougies clôturées — l'appelant ne doit alors PAS
    acheter. Format Kraken ohlc : [open_time, open, high, low, close, vwap, volume, count]."""
    now_ts = time.time() if now_ts is None else now_ts
    pair = f"{coin}USDC"
    try:
        raw = binance("ohlc", pair, "--interval", "1440", "-o", "json", _retries=2)
        data = json.loads(raw)
        candles = data.get(pair) or next(v for k, v in data.items() if k != "last")
        closes = [float(c[4]) for c in candles if float(c[0]) + CANDLE_1D_SECONDS <= now_ts]
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError, KeyError, IndexError, TypeError,
            StopIteration, AttributeError):
        return None
    e = ema_last(closes, ema_days)
    return None if e is None else (closes[-1], e)


def compute_tp_target(entry_price: float, stop_distance_pct: float, reward_risk_ratio: float,
                      fee_round_trip_pct: float, max_tp_pct: float,
                      resistance: float | None = None) -> float:
    """Cible de TP unique pour l'entrée (phase 4/5, maker_watcher) et le recalibrage Phase 0 (#516).

    tp_mecanique = cible nette de frais (#411), toujours plafonnée à entry x (1 + max_tp_pct) (#428).
    Si une résistance 4h > entry existe : tp = min(plafond, résistance x 0.98). Si cette cible tombe
    sous le plancher de viabilité (entry x (1 + 2 x frais)), la cible = le plancher (#519) : la
    résistance est trop proche pour viser plus haut. Résistance absente ou <= entry : min(mécanique,
    plafond). Un plafond max_tp_pct configuré sous le plancher reste appliqué.
    """
    tp_mecanique = entry_price * (1 + (stop_distance_pct + fee_round_trip_pct) * reward_risk_ratio + fee_round_trip_pct)
    tp_plafond = entry_price * (1 + max_tp_pct)
    tp_plancher = entry_price * (1 + 2 * fee_round_trip_pct)
    tp_capped = min(tp_mecanique, tp_plafond)
    if resistance is not None and resistance > entry_price:
        if resistance * RESISTANCE_TP_FACTOR < tp_plancher:
            return tp_plancher
        tp_resistance = min(tp_capped, resistance * RESISTANCE_TP_FACTOR)
        if tp_resistance >= tp_plancher:
            return tp_resistance
    return tp_capped


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
