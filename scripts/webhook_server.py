#!/usr/bin/env python3
"""
Telegram polling bot for Binance trading agent v2.
- Market-wide scan, multi-timeframe scoring (0-10), auto stop-loss + take-profit
- Trade journal + /perf with p-value
- Auto-scheduler: runs every 4h aligned to TradingView candle closes (00:05, 04:05, ..., 20:05 UTC)
- Secrets loaded from .env (never hardcoded)
"""

import glob
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta

from loguru import logger
from pymongo import MongoClient

logger.remove(0)  # Retire le handler stderr par défaut avant tout logger.add() pour éviter la double écriture via nohup 2>&1


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())

_load_env()

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

if not TOKEN or not CHAT_ID:
    logger.warning("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant dans .env")

# Setup loguru : logs internes du bot avec rotation quotidienne, rétention 30j
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
os.makedirs(f"{LOGS_DIR}/stdout", exist_ok=True)
os.makedirs(f"{LOGS_DIR}/stderr", exist_ok=True)
logger.add(
    f"{LOGS_DIR}/bot_{{time:YYYY-MM-DD}}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
)

# Handler daemon.log avec rotation 10 MB, rétention 5 fichiers
logger.add(
    f"{PROJECT_DIR}/state/daemon.log",
    rotation="10 MB",
    retention=5,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
)

# MongoDB (lazy connection)
MONGO_URI = os.environ.get("MONGODB_URI", "").strip()
MONGO_DB = os.environ.get("MONGODB_DB", "agent-binance").strip()
_mongo_client = None


def get_mongo():
    """Retourne la DB Mongo ou None si non configuré / non joignable."""
    global _mongo_client
    if not MONGO_URI:
        return None
    if _mongo_client is None:
        try:
            _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            _mongo_client.admin.command("ping")
            logger.info("MongoDB connecté")
        except Exception as e:
            logger.error(f"MongoDB connexion échouée : {e}")
            _mongo_client = None
            return None
    return _mongo_client[MONGO_DB]

# Template: __BOT_TOKEN__ et __CHAT_ID__ sont remplacés dynamiquement au démarrage
_TRADE_PROMPT_TEMPLATE = """Tu es un agent de trading Binance automatisé. Répertoire de travail : __PROJECT_DIR__

Pour envoyer des notifications Telegram à chaque étape, exécute ce code Python (utilise curl, pas urllib) :

import subprocess, json as _json
def tg(text):
    payload = _json.dumps({"chat_id": "__CHAT_ID__", "text": text})
    subprocess.run(
        ["curl", "-s", "-X", "POST",
         "https://api.telegram.org/bot__BOT_TOKEN__/sendMessage",
         "-H", "Content-Type: application/json",
         "-d", payload, "--max-time", "20"],
        capture_output=True)

import json as _hb_json, datetime as _hb_dt, os as _hb_os
_HB_PATH = "__PROJECT_DIR__/logs/cycle___CYCLE_ID___phases.jsonl"
_hb_os.makedirs(_hb_os.path.dirname(_HB_PATH), exist_ok=True)
_hb_phase_start = {}

def _hb_start(phase):
    _hb_phase_start[phase] = _hb_dt.datetime.utcnow().timestamp()

def hb(phase, status="ok", summary=""):
    t0 = _hb_phase_start.pop(phase, None)
    duration_s = round(_hb_dt.datetime.utcnow().timestamp() - t0, 1) if t0 is not None else None
    with open(_HB_PATH, "a") as _f:
        _f.write(_hb_json.dumps({
            "ts": _hb_dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phase": phase,
            "status": status,
            "duration_s": duration_s,
            "summary": summary
        }) + "\n")
        _f.flush()

Envoie une notification à la FIN de chaque phase avant de passer à la suivante.

---

PHASE 0 — VÉRIFICATIONS PRÉALABLES
_hb_start(0)
Lis config.json pour récupérer TOUS les paramètres.
Exécute : binance-cli spot get-account --profile agent-profile
Calcule : portfolio_total = USDC_free + sum(locked USDC de tous les assets)
budget_disponible = USDC_free × usdc_allocation_pct

Lis state/trade_history.json.
Identifie les trades du jour (date = aujourd'hui UTC).
daily_pnl = sum(pnl_usdc pour trades fermés aujourd'hui)
Si daily_pnl < -(portfolio_total × daily_loss_limit_pct) :
→ tg("⛔ Daily loss limit atteinte. Trading pausé pour aujourd'hui.")
→ ARRÊTE.

Vérifie les trades "open" dans trade_history.json vs les ordres ouverts Binance :
Pour chaque trade open dans l'historique :
  binance-cli spot get-order --symbol {COIN}USDC --orderId {entry_order_id} --profile agent-profile
  Si l'ordre d'entrée est FILLED et que l'ordre stop ou TP n'est plus dans get-open-orders :
    → Le trade est fermé. Récupère le prix d'exécution.
    → Calcule pnl_usdc = (exit_price - entry_price) × quantity
    → Calcule pnl_pct = (exit_price - entry_price) / entry_price × 100
    → Met à jour trade_history.json : status="closed", exit_price, pnl_usdc, pnl_pct, exit_date
    → Si pnl_usdc > 0 : tg("✅ TP touché : {COIN} +{pnl_usdc:.2f} USDC (+{pnl_pct:.1f}%)")
    → Sinon : tg("🛑 Stop touché : {COIN} {pnl_usdc:.2f} USDC ({pnl_pct:.1f}%)")

RATTRAPAGE protection_failed — encapsuler dans un try/finally pour libérer le lock même en cas d'erreur :
Identifie les trades status="open" ET protection_failed=True dans trade_history.json.
Pour chaque trade non protégé (idempotence : vérifier qu'aucun OCO actif n'existe déjà pour ce coin) :

import json as _pf_json, subprocess as _pf_sub
try:
    with open("__PROJECT_DIR__/state/trade_history.json") as _f:
        _history = _pf_json.load(_f)
    _unprotected = [t for t in _history if t.get("status") == "open" and t.get("protection_failed") is True]

    for _t in _unprotected:
        _coin = _t["coin"]
        _qty = _t["quantity"]
        _entry = _t["entry_price"]
        _tp_calc = _t["tp_price"]
        _stop_calc = _t["stop_price"]

        # Vérifier qu'un OCO n'est pas déjà actif (idempotence)
        _open_orders_raw = _pf_sub.run(
            ["binance-cli", "spot", "get-open-orders", "--symbol", f"{_coin}USDC", "--profile", "agent-profile"],
            capture_output=True, text=True
        )
        _open_orders = _pf_json.loads(_open_orders_raw.stdout) if _open_orders_raw.stdout.strip() else []
        _has_oco = any(o.get("type") in ("LIMIT_MAKER", "STOP_LOSS_LIMIT") for o in _open_orders)
        if _has_oco:
            # OCO déjà présent — mettre à jour protection_failed=False et continuer
            for _item in _history:
                if _item.get("trade_id") == _t.get("trade_id"):
                    _item["protection_failed"] = False
            tg(f"ℹ️ {_coin} : OCO déjà actif, protection_failed corrigé")
            continue

        # Récupérer le prix actuel
        _ticker_raw = _pf_sub.run(
            ["binance-cli", "spot", "get-symbol-price-ticker", "--symbol", f"{_coin}USDC", "--profile", "agent-profile"],
            capture_output=True, text=True
        )
        _ticker = _pf_json.loads(_ticker_raw.stdout)
        _prix_actuel = float(_ticker["price"])

        if _prix_actuel > _tp_calc:
            # Prix marché au-dessus du TP calculé → fermeture à market immédiate
            _sell_raw = _pf_sub.run(
                ["binance-cli", "spot", "order-market", "--symbol", f"{_coin}USDC",
                 "--side", "SELL", "--quantity", str(_qty), "--profile", "agent-profile"],
                capture_output=True, text=True
            )
            _sell_resp = _pf_json.loads(_sell_raw.stdout) if _sell_raw.stdout.strip() else {}
            if _sell_resp.get("orderId"):
                _fill_exit = float(_sell_resp.get("cummulativeQuoteQty", 0)) / float(_sell_resp.get("executedQty", _qty))
                _pnl_usdc = (_fill_exit - _entry) * _qty
                _pnl_pct = (_fill_exit - _entry) / _entry * 100
                for _item in _history:
                    if _item.get("trade_id") == _t.get("trade_id"):
                        _item.update({"status": "closed", "exit_price": _fill_exit,
                                      "pnl_usdc": _pnl_usdc, "pnl_pct": _pnl_pct,
                                      "exit_date": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                                      "protection_failed": False, "close_reason": "market_above_tp"})
                tg(f"✅ {_coin} fermé à market (prix {_prix_actuel:.4g} > TP {_tp_calc:.4g}) : {_pnl_usdc:+.2f} USDC ({_pnl_pct:+.1f}%)")
            else:
                tg(f"⚠️ {_coin} : fermeture market échouée — {_sell_raw.stdout[:200]}")
        else:
            # Prix sous le TP → replacer un OCO de rattrapage
            # Vérifier filtres LOT_SIZE via exchange-info
            _ei_raw = _pf_sub.run(
                ["binance-cli", "spot", "get-exchange-info", "--symbol", f"{_coin}USDC", "--profile", "agent-profile"],
                capture_output=True, text=True
            )
            _ei = _pf_json.loads(_ei_raw.stdout) if _ei_raw.stdout.strip() else {}
            _filters = {f["filterType"]: f for sym in _ei.get("symbols", []) for f in sym.get("filters", [])}
            _step = float(_filters.get("LOT_SIZE", {}).get("stepSize", "1"))
            import math as _math
            _qty_adj = _math.floor(_qty / _step) * _step

            # S'assurer que le TP est strictement au-dessus du prix actuel
            _tp_oco = max(_tp_calc, _prix_actuel * 1.001)
            _oco_raw = _pf_sub.run(
                ["binance-cli", "spot", "order-list-oco",
                 "--symbol", f"{_coin}USDC",
                 "--side", "SELL",
                 "--quantity", str(_qty_adj),
                 "--above-type", "LIMIT_MAKER",
                 "--above-price", str(round(_tp_oco, 8)),
                 "--below-type", "STOP_LOSS_LIMIT",
                 "--below-price", str(round(_stop_calc, 8)),
                 "--below-stop-price", str(round(_stop_calc * 1.002, 8)),
                 "--below-time-in-force", "GTC",
                 "--profile", "agent-profile"],
                capture_output=True, text=True
            )
            _oco_resp = _pf_json.loads(_oco_raw.stdout) if _oco_raw.stdout.strip() else {}
            if _oco_resp.get("orderListId"):
                _reports = {r["type"]: r for r in _oco_resp.get("orderReports", [])}
                _tp_id = _reports.get("LIMIT_MAKER", {}).get("orderId")
                _sl_id = _reports.get("STOP_LOSS_LIMIT", {}).get("orderId")
                for _item in _history:
                    if _item.get("trade_id") == _t.get("trade_id"):
                        _item.update({"protection_failed": False, "tp_order_id": _tp_id,
                                      "stop_order_id": _sl_id, "order_list_id": _oco_resp["orderListId"],
                                      "tp_price": _tp_oco, "stop_price": _stop_calc})
                tg(f"🛡️ {_coin} : OCO de rattrapage placé — TP {_tp_oco:.4g} / SL {_stop_calc:.4g}")
            else:
                tg(f"⚠️ {_coin} : OCO rattrapage échoué — {_oco_raw.stdout[:200]}")

    with open("__PROJECT_DIR__/state/trade_history.json", "w") as _f:
        _pf_json.dump(_history, _f, indent=2)
except Exception as _pf_err:
    tg(f"⚠️ Erreur routine rattrapage protection_failed : {_pf_err}")

# --- TRAILING STOP ---
# Pour chaque position ouverte avec OCO actif, vérifier si le prix a progressé
# et remonter le stop-loss en conséquence.

_ts_updates = []
for _t in _history:
    if _t.get("status") != "open" or not _t.get("order_list_id"):
        continue
    _coin = _t["coin"]
    _entry = float(_t["entry_price"])
    _cur_stop = float(_t["stop_price"])
    _cur_tp = float(_t["tp_price"])
    _trail_dist = _entry - _cur_stop  # distance originale

    # Prix actuel
    try:
        _ticker = json.loads(subprocess.check_output(
            ["binance-cli", "ticker", "--symbol", f"{_coin}USDC"], text=True))
        _price = float(_ticker["price"])
    except Exception as _e:
        tg(f"⚠️ Trailing stop {_coin} : impossible de récupérer le prix ({_e})")
        continue

    # Nouveau stop candidat
    _new_stop = round(_price - _trail_dist, 8)

    # Conditions de mise à jour
    if _new_stop <= _cur_stop + _trail_dist * 0.20:
        continue  # pas assez de progression
    if _new_stop >= _price * 0.98:
        continue  # trop proche du prix actuel

    # Nouveau TP : max(original_tp, current_price + 3 * trail_dist)
    _new_tp = max(_cur_tp, round(_price + _trail_dist * 3, 8))

    # Annuler l'OCO existant
    try:
        subprocess.check_output(
            ["binance-cli", "cancel-order", "--symbol", f"{_coin}USDC",
             "--order-list-id", str(_t["order_list_id"])], text=True)
    except Exception as _e:
        tg(f"⚠️ Trailing stop {_coin} : échec annulation OCO ({_e}), skip")
        continue

    # Récupérer lot_size et tick_size pour arrondir
    try:
        _info = json.loads(subprocess.check_output(
            ["binance-cli", "exchange-info", "--symbol", f"{_coin}USDC"], text=True))
        _filters = {f["filterType"]: f for f in _info.get("filters", [])}
        _tick = float(_filters.get("PRICE_FILTER", {}).get("tickSize", "0.00000001"))
        _lot = float(_filters.get("LOT_SIZE", {}).get("stepSize", "0.00000001"))
        import math
        def _round_price(p, tick):
            return round(round(p / tick) * tick, 8)
        def _round_qty(q, step):
            return round(math.floor(q / step) * step, 8)
        _qty = _round_qty(float(_t["quantity"]), _lot)
        _new_stop_r = _round_price(_new_stop, _tick)
        _new_tp_r = _round_price(_new_tp, _tick)
        _stop_limit_r = _round_price(_new_stop * 1.002, _tick)
    except Exception:
        _qty = float(_t["quantity"])
        _new_stop_r, _new_tp_r, _stop_limit_r = _new_stop, _new_tp, round(_new_stop * 1.002, 8)

    # Placer le nouvel OCO
    try:
        _oco_raw = subprocess.check_output([
            "binance-cli", "oco-sell",
            "--symbol", f"{_coin}USDC",
            "--quantity", str(_qty),
            "--above-type", "LIMIT_MAKER",
            "--above-price", str(_new_tp_r),
            "--below-type", "STOP_LOSS_LIMIT",
            "--below-price", str(_new_stop_r),
            "--below-stop-price", str(_stop_limit_r),
            "--below-time-in-force", "GTC"
        ], text=True)
        _oco = json.loads(_oco_raw)
        _new_list_id = _oco.get("orderListId")
        _new_tp_id = next((o["orderId"] for o in _oco.get("orderReports", [])
                           if o.get("type") == "LIMIT_MAKER"), None)
        _new_sl_id = next((o["orderId"] for o in _oco.get("orderReports", [])
                           if o.get("type") == "STOP_LOSS_LIMIT"), None)
    except Exception as _e:
        tg(f"⚠️ Trailing stop {_coin} : échec placement nouvel OCO ({_e})")
        continue

    # Mettre à jour trade_history.json
    _t["stop_price"] = _new_stop_r
    _t["tp_price"] = _new_tp_r
    _t["order_list_id"] = _new_list_id
    _t["stop_order_id"] = _new_sl_id
    _t["tp_order_id"] = _new_tp_id
    with open(f"{PROJECT_DIR}/state/trade_history.json", "w") as _f:
        json.dump(_history, _f, indent=2)

    _ts_updates.append(f"{_coin}: stop {_cur_stop:.4g}→{_new_stop_r:.4g} | TP {_cur_tp:.4g}→{_new_tp_r:.4g}")
    tg(f"📈 {_coin} trailing stop remonté\nStop : {_cur_stop:.4g} → {_new_stop_r:.4g}\nTP : {_cur_tp:.4g} → {_new_tp_r:.4g}\nPrix actuel : {_price:.4g}")

if _ts_updates:
    tg("🔄 Trailing stops mis à jour ce cycle :\n" + "\n".join(_ts_updates))
# --- FIN TRAILING STOP ---

Compte open_positions = nombre de trades status="open" dans trade_history.json
→ tg("📋 Phase 0 — Vérifications\\nPortfolio : {portfolio_total:.2f} USDC\\nBudget dispo : {budget_disponible:.2f} USDC\\nPositions ouvertes : {open_positions}/{max_open_positions}\\nPnL du jour : {daily_pnl:+.2f} USDC")
hb(0, summary=f"Portfolio {portfolio_total:.2f} USDC, {open_positions} positions, PnL jour {daily_pnl:+.2f} USDC")

PHASE 1 — SCAN MARCHÉ (tout en parallèle)
_hb_start(1)
Lance simultanément :
- mcp__tradingview__top_gainers (exchange: BINANCE) → top gainers
- mcp__tradingview__volume_breakout_scanner (exchange: BINANCE) → breakouts volume
- mcp__tradingview__market_sentiment → sentiment global
- mcp__tradingview__rating_filter (exchange: BINANCE, rating: BUY) → coins notés BUY

Construis l'univers de candidats :
1. Inclure systématiquement les portfolio_coins (BTC, STX, XRP, SOL, SUI)
2. Ajouter les coins qui apparaissent dans AU MOINS 2 des screeners ci-dessus
3. Filtrer : garder uniquement les paires {COIN}USDC disponibles sur Binance
4. Limiter à universe_scan_top_n (20) coins au total
5. Exclure les stablecoins (USDT, BUSD, FDUSD, etc.)

→ tg("📡 Phase 1 — Scan marché\\nSentiment : {sentiment}\\n{N} candidats identifiés : {liste}")
hb(1, summary=f"Sentiment {sentiment}, {N} candidats")

PHASE 2 — ANALYSE MULTI-TIMEFRAME (tout en parallèle)
_hb_start(2)
Pour chaque coin de l'univers, lance en parallèle :
- mcp__tradingview__coin_analysis (exchange: BINANCE, screener: crypto, timeframe: 4h)
- mcp__tradingview__coin_analysis (exchange: BINANCE, screener: crypto, timeframe: 1d)

→ tg("📊 Phase 2 — Analyse terminée\\n{1 ligne par coin : COIN — RSI_4h / signal_4h / signal_1d}")
hb(2, summary=f"{len(univers)} coins analysés multi-timeframe")

PHASE 3 — SCORING ET SÉLECTION
_hb_start(3)
Pour chaque coin, calcule un score sur 10 :

| Critère | Points |
|---------|--------|
| Signal TradingView 4h = BUY/STRONG_BUY | +2 |
| Signal TradingView 1d = BUY/STRONG_BUY | +2 |
| RSI 4h entre 30 et 55 (zone d'entrée optimale) | +1 |
| MACD bullish cross sur 4h | +1 |
| Coin dans volume_breakout_scanner | +1 |
| ADX 4h > min_adx (20) | +1 |
| Sentiment marché haussier (BULL) | +1 |
| Coin dans top_gainers avec momentum positif | +1 |

DÉCISION par coin :
- Score >= min_signal_score (6) ET signal_4h = BUY ou STRONG_BUY → BUY CANDIDATE
  * Le signal 1d haussier contribue déjà +2 pts au score (non bloqueur) — un 1d bearish réduit le score mais n'empêche pas le trade si le score total ≥ 6 et le 4h est haussier
  * Si coin déjà en portfolio → RENFORCER (si pas déjà une position open dans trade_history)
  * Si coin nouveau → NOUVELLE POSITION
- Score <= 3 ET coin en portfolio → évaluer si sortie est pertinente (SELL)
- Sinon → HOLD

FILTRES OBLIGATOIRES :
- Corrélation : SOL, SUI, STX, ETH sont corrélés (groupe L1-alts). Max max_correlated_positions (2) du même groupe.
- Positions max : si open_positions >= max_open_positions (5) → pas de nouvelle entrée
- Budget : montant_ordre >= min_order_usdc (11 USDC)
- Liquidité : ne pas trader des coins avec volume 24h < 5M USDC (estimé depuis les screeners)

→ tg("🧠 Phase 3 — Stratégie\\nScores : {coin: score pour les top 5}\\n{N_buy} BUY candidates : {liste}\\nFiltres appliqués : {résumé}")
hb(3, summary=f"{N_buy} BUY candidates, filtres appliqués")

PHASE 4 — SIZING ET PRÉPARATION DES ORDRES
_hb_start(4)
Pour chaque BUY candidate :

# Sizing basé sur le risque fixe
portfolio_total = (calculé en Phase 0)
risk_usdc = portfolio_total × risk_per_trade_pct        # ex: 152 × 0.01 = 1.52 USDC

# Estimation ATR comme proxy de volatilité (utilise la range des bougies 4h)
# ATR ≈ (high - low) moyen sur 14 bougies. Utilise les données TradingView.
# Si ATR non disponible, utilise 2% du prix comme approximation conservative.
atr_pct = atr_estimé / prix_actuel                      # ex: 0.02 = 2%
stop_distance_pct = atr_pct × atr_stop_multiplier       # ex: 0.02 × 2 = 4%

# Calcul des prix
prix_entry = prix_actuel × (1 - limit_offset_pct)
prix_stop = prix_entry × (1 - stop_distance_pct)
prix_tp = prix_entry × (1 + stop_distance_pct × reward_risk_ratio)

# Quantité
quantite = risk_usdc / (prix_entry × stop_distance_pct)
montant_ordre = quantite × prix_entry

# Arrondir la quantité selon la précision Binance du coin (utilise stepSize)
binance-cli spot get-exchange-info --symbol {COIN}USDC --profile agent-profile
→ extraire stepSize et minQty, arrondir quantite

Vérifications :
- montant_ordre < min_order_usdc → SKIP (trop petit)
- montant_ordre > budget_disponible × max_single_position_pct → réduire à la limite
- prix_stop < 0 → SKIP (erreur)
- Re-vérifier budget total de tous les ordres ≤ budget_disponible

→ tg("💰 Phase 4 — Ordres préparés\\n{pour chaque ordre : COIN qty @ entry | Stop: stop | TP: tp | Risque: risk_usdc USDC}")
hb(4, summary=f"{len(ordres_prepares)} ordres dimensionnés")

PHASE 5 — EXÉCUTION AUTOMATIQUE
_hb_start(5)
Pour chaque ordre préparé, dans l'ordre de score décroissant :

1. Re-fetch prix actuel :
   binance-cli spot get-symbol-price-ticker --symbol {COIN}USDC --profile agent-profile
   Si drift > price_deviation_max_pct (2%) → SKIP + tg("⚠️ {COIN} : prix dévié de {drift:.1f}%, ordre annulé")

2. Re-fetch solde USDC :
   binance-cli spot get-account --profile agent-profile
   Si USDC_free < montant_ordre → SKIP + tg("⚠️ Solde insuffisant pour {COIN}")

3. Placer un BUY MARKET immédiat (élimine le risque de fill tardif qui provoquerait protection_failed) :
   binance-cli spot order-market --symbol {COIN}USDC \\
     --side BUY --quantity {quantite} \\
     --profile agent-profile

   La réponse contient `orderId`, `executedQty`, `cummulativeQuoteQty`, `status`.
   Si status != "FILLED" ou orderId absent → SKIP + tg("⚠️ BUY MARKET {COIN} non rempli : {status}") + continuer au coin suivant.

   Calcule le prix de fill réel (gère les fills partiels en plusieurs lots) :
   actual_entry = cummulativeQuoteQty / executedQty   # prix moyen pondéré réel
   actual_qty = executedQty                            # quantité effectivement achetée
   entry_order_id = orderId

   Recalcule TP et SL sur le prix réel (pas sur le prix limit initial) :
   actual_stop = actual_entry × (1 - stop_distance_pct)
   actual_tp   = actual_entry × (1 + stop_distance_pct × reward_risk_ratio)

4. Vérifier que actual_tp est strictement au-dessus du prix marché courant avant de poser l'OCO :
   Re-fetch prix actuel juste après le fill :
   binance-cli spot get-symbol-price-ticker --symbol {COIN}USDC --profile agent-profile
   prix_post_fill = float(réponse["price"])

   Si prix_post_fill >= actual_tp :
     → Le marché est déjà au-dessus du TP recalculé (wick rapide) — fermer à market directement :
     binance-cli spot order-market --symbol {COIN}USDC --side SELL --quantity {actual_qty} --profile agent-profile
     → Calculer pnl_usdc = (prix_post_fill - actual_entry) × actual_qty
     → Enregistrer trade comme status="closed", close_reason="market_above_tp_at_fill"
     → tg("⚡ {COIN} : TP dépassé au fill, fermé à market immédiatement → {pnl_usdc:+.2f} USDC")
     → Passer au coin suivant.

5. Vérifier les filtres LOT_SIZE pour l'OCO SELL :
   binance-cli spot get-exchange-info --symbol {COIN}USDC --profile agent-profile
   → extraire stepSize du filtre LOT_SIZE
   actual_qty_oco = floor(actual_qty / stepSize) * stepSize   # quantité entière pour l'OCO

6. Placer l'OCO SELL standalone (TP + SL) sur le prix de fill réel :
   binance-cli spot order-list-oco --symbol {COIN}USDC \\
     --side SELL --quantity {actual_qty_oco} \\
     --above-type LIMIT_MAKER --above-price {actual_tp} \\
     --below-type STOP_LOSS_LIMIT --below-price {actual_stop} \\
     --below-stop-price {actual_stop * 1.002} --below-time-in-force GTC \\
     --profile agent-profile

   La réponse contient `orderListId` et `orderReports`. Récupère :
     tp_order_id   = orderReports[type=LIMIT_MAKER].orderId
     stop_order_id = orderReports[type=STOP_LOSS_LIMIT].orderId
     order_list_id = orderListId

   Si l'appel OCO échoue → marquer protection_failed=True dans le trade enregistré :
     tg("⚠️ {COIN} : BUY MARKET OK mais OCO échoué — position NON protégée ! {err_msg}")
     Enregistrer trade avec protection_failed=True (sera repris en Phase 0 du prochain cycle).

7. Enregistre dans state/trade_history.json (APPEND, ne pas écraser) :
import json, uuid
from datetime import datetime, timezone
with open("__PROJECT_DIR__/state/trade_history.json") as f:
    history = json.load(f)
history.append({
    "trade_id": str(uuid.uuid4())[:8],
    "date": datetime.now(timezone.utc).isoformat(),
    "coin": "{COIN}",
    "side": "BUY",
    "signal_score": {score},
    "entry_price": {actual_entry},
    "stop_price": {actual_stop},
    "tp_price": {actual_tp},
    "quantity": {actual_qty},
    "risk_usdc": {risk_usdc},
    "entry_order_id": {entry_order_id},
    "stop_order_id": {stop_order_id},
    "tp_order_id": {tp_order_id},
    "order_list_id": {order_list_id},
    "protection_failed": {True if oco_failed else False},
    "status": "open",
    "exit_price": None,
    "exit_date": None,
    "pnl_usdc": None,
    "pnl_pct": None
})
with open("__PROJECT_DIR__/state/trade_history.json", "w") as f:
    json.dump(history, f, indent=2)

8. Notification immédiate :
   tg("⚡ BUY MARKET {COIN}\\n{actual_qty} @ {actual_entry:.4g} USDC (fill réel)\\n🛑 Stop : {actual_stop:.4g}\\n🎯 TP : {actual_tp:.4g}\\nScore : {score}/10")

Après avoir traité tous les ordres :
hb(5, summary=f"{len(ordres_executes)} ordres exécutés, {orders_skipped_count} skippés")

PHASE 6 — RAPPORT FINAL
_hb_start(6)
- Génère reports/YYYY-MM-DD_HH-MM_trade.md avec :
  * Univers scanné (N coins), filtres appliqués, scores top 10
  * Ordres exécutés avec IDs et paramètres
  * Budget utilisé / disponible
  * Positions ouvertes totales (depuis trade_history.json)

- Calcule l'heure du prochain cycle automatique (slot 4h UTC + 5 min, affiché en heure locale) :
import datetime as _dt
_now = _dt.datetime.now(_dt.timezone.utc)
_slot_h = (_now.hour // 4) * 4
_next = _now.replace(hour=_slot_h, minute=5, second=0, microsecond=0)
if _next <= _now:
    _next += _dt.timedelta(hours=4)
_next_str = _next.astimezone().strftime("%d/%m %H:%M") + " (heure locale)"
hb(6, summary=f"Rapport généré, prochain cycle {_next_str}")

PHASE 7 — PERSISTANCE EN BASE (MongoDB)
_hb_start(7)

CYCLE_ID = "__CYCLE_ID__"   # déjà substitué par Python avant l'appel

Construis un document Python `doc` représentant ce cycle :

doc = {
  "_id": CYCLE_ID,
  "cycle_id": CYCLE_ID,
  "prompt_version": "__PROMPT_VERSION__",
  "timestamp": "{ISO UTC du début du cycle}",
  "status": "completed",
  "trigger": "manual",
  "portfolio": {
    "total_usdc": <portfolio_total>,
    "budget_disponible": <budget_disponible>,
    "positions_ouvertes": <open_positions>,
    "daily_pnl": <daily_pnl>
  },
  "market_context": {
    "sentiment": "<Strongly Bullish | Bullish | Neutral | Bearish | Strongly Bearish>",
    "universe_size": <N>,
    "coins_scanned": [<liste des coins analysés>]
  },
  "decisions": [
    {
      "coin": "BTC",
      "score": <0-10>,
      "signal_4h": "<BUY|SELL|NEUTRAL|STRONG_BUY|STRONG_SELL>",
      "signal_1d": "...",
      "rsi_4h": <number>,
      "decision": "<BUY|HOLD|SKIP|SELL>",
      "reason": "Phrase courte expliquant pourquoi cette décision"
    },
    ... un objet par coin analysé
  ],
  "orders_placed": [
    {"coin": "...", "score": ..., "entry_price": ..., "stop_price": ...,
     "tp_price": ..., "quantity": ..., "risk_usdc": ...}
  ],
  "orders_skipped_count": <N>,
  "log_files": {
    "stdout": f"logs/stdout/cycle_{CYCLE_ID}.log",
    "stderr": f"logs/stderr/cycle_{CYCLE_ID}.log"
  },
  "explanation_fr": "Paragraphe de 3 à 5 phrases en FRANÇAIS expliquant à un non-expert en crypto : (a) ce qu'on a fait ce cycle, (b) pourquoi on a (ou pas) placé des ordres, (c) la météo du marché. ÉVITE le jargon technique. Au lieu de 'RSI à 32', dis 'l'indicateur de pression vendeuse'. Au lieu de 'score 7/10', dis 'signal solide'. Au lieu de 'ATR×2', dis 'protection ajustée à la volatilité'."
}

Écris ce document en Mongo via Python :

import os
from pymongo import MongoClient
_uri = os.environ.get("MONGODB_URI", "").strip()
if _uri:
    try:
        _client = MongoClient(_uri, serverSelectionTimeoutMS=5000)
        _db = _client[os.environ.get("MONGODB_DB", "agent-binance")]
        _db.cycles.update_one({"_id": CYCLE_ID}, {"$set": doc}, upsert=True)
        _client.close()
    except Exception as _e:
        tg(f"⚠️ Mongo write failed : {_e}")

- Notification de synthèse (DOIT inclure le cycle_id) :
  tg(f"✅ Cycle {CYCLE_ID} terminé\\n{N} ordre(s) exécuté(s) | {M} skippés\\nBudget utilisé : {total:.2f} USDC\\nPositions actives : {open_positions}\\n⏰ Prochain cycle : {_next_str}\\n📊 /raisonnement pour les détails")

- Écris state/agent_lock.json : {"running": false, "started_at": null}
hb(7, summary=f"Cycle {CYCLE_ID} persisté en Mongo, {N} ordre(s)")"""

# Calculé sur le template BRUT, avant toute substitution — garantit la stabilité entre cycles
PROMPT_VERSION = hashlib.sha1(_TRADE_PROMPT_TEMPLATE.encode(), usedforsecurity=False).hexdigest()[:8]

TRADE_PROMPT = (
    _TRADE_PROMPT_TEMPLATE
    .replace("__BOT_TOKEN__", TOKEN)
    .replace("__CHAT_ID__", CHAT_ID)
    .replace("__PROJECT_DIR__", PROJECT_DIR)
)


def next_4h_slot():
    """Prochain slot 4h UTC + 5 min (aligné sur les clôtures TradingView : 00:05, 04:05, ..., 20:05)."""
    now = datetime.now(timezone.utc)
    slot_hour = (now.hour // 4) * 4
    nxt = now.replace(hour=slot_hour, minute=5, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(hours=4)
    return nxt


def fmt_local(dt_utc):
    """Convertit un datetime UTC en heure locale lisible, ex: '22:05 (heure locale)'."""
    local = dt_utc.astimezone()  # timezone locale du système
    return local.strftime("%d/%m %H:%M") + " (heure locale)"


NEXT_AUTO_TRADE = None  # initialisé dans main_loop


def tg_post(endpoint, body):
    payload = json.dumps(body)
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{BASE_URL}/{endpoint}",
             "-H", "Content-Type: application/json",
             "-d", payload, "--max-time", "15"],
            capture_output=True, text=True
        )
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except Exception as e:
        logger.error(f"[Telegram] {endpoint} erreur: {e}")
        return {}


def send_telegram(text, parse_mode=None):
    body = {"chat_id": CHAT_ID, "text": text}
    if parse_mode:
        body["parse_mode"] = parse_mode
    tg_post("sendMessage", body)


def is_locked():
    try:
        with open(f"{PROJECT_DIR}/state/agent_lock.json") as f:
            lock = json.load(f)
        if not lock.get("running"):
            return False
        started = lock.get("started_at")
        if started:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
            if age < 7200:
                return True
            with open(f"{PROJECT_DIR}/state/agent_lock.json", "w") as f:
                json.dump({"running": False, "started_at": None}, f)
    except:
        pass
    return False


def acquire_lock():
    with open(f"{PROJECT_DIR}/state/agent_lock.json", "w") as f:
        json.dump({"running": True, "started_at": datetime.now(timezone.utc).isoformat()}, f)


def release_lock():
    with open(f"{PROJECT_DIR}/state/agent_lock.json", "w") as f:
        json.dump({"running": False, "started_at": None}, f)


def fmt_next():
    """Retourne l'heure du prochain cycle en heure locale."""
    if NEXT_AUTO_TRADE:
        return fmt_local(NEXT_AUTO_TRADE)
    return "–"


def run_status():
    try:
        account = subprocess.run(
            ["binance-cli", "spot", "get-account", "--profile", "agent-profile"],
            capture_output=True, text=True, cwd=PROJECT_DIR
        )
        orders = subprocess.run(
            ["binance-cli", "spot", "get-open-orders", "--profile", "agent-profile"],
            capture_output=True, text=True, cwd=PROJECT_DIR
        )
        data = json.loads(account.stdout)
        balances = [b for b in data["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]
        usdc = next((b for b in balances if b["asset"] == "USDC"), {"free": "0", "locked": "0"})
        free = float(usdc["free"])
        budget = round(free * 0.40, 2)

        lines = ["📊 <b>Portfolio actuel</b>\n"]
        lines.append(f"💵 USDC libre : <code>{free:.2f}</code> (budget 40% = <code>{budget:.2f}</code>)")
        lines.append(f"🔒 USDC lockés : <code>{float(usdc['locked']):.2f}</code>\n")

        non_usdc = [b for b in balances if b["asset"] not in ("USDC", "LDUSDC") and not b["asset"].startswith("LD")]
        if non_usdc:
            lines.append("<b>Positions :</b>")
            for b in non_usdc:
                if float(b["locked"]) > 0:
                    lines.append(f"  <code>{b['asset']}</code> : {b['locked']} (locked)")

        open_orders = json.loads(orders.stdout) if orders.stdout.strip() else []
        if open_orders:
            lines.append(f"\n<b>Ordres ouverts ({len(open_orders)}) :</b>")
            for o in open_orders[:8]:
                side_emoji = "🟢" if o["side"] == "BUY" else "🔴"
                lines.append(f"  {side_emoji} {o['symbol']} {o['type']} @ {float(o['price']):.4g} × {float(o['origQty']):.4g}")

        try:
            with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
                history = json.load(f)
            open_trades = [t for t in history if t.get("status") == "open"]
            if open_trades:
                lines.append(f"\n<b>Trades agent actifs ({len(open_trades)}) :</b>")
                for t in open_trades:
                    lines.append(f"  🎯 {t['coin']} @ {t['entry_price']:.4g} | Stop: {t['stop_price']:.4g} | TP: {t['tp_price']:.4g}")
        except:
            pass

        lines.append(f"\n⏰ <b>Prochain cycle auto</b> : <code>{fmt_next()}</code>")

        send_telegram("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        send_telegram(f"❌ Erreur /status : {e}")


def run_perf():
    try:
        with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
            history = json.load(f)
    except:
        send_telegram("❌ Pas encore de données de trading.")
        return

    closed = [t for t in history if t.get("status") == "closed" and t.get("pnl_pct") is not None]

    if len(closed) < 2:
        open_count = len([t for t in history if t.get("status") == "open"])
        send_telegram(f"📈 Pas encore assez de trades fermés pour les stats.\n"
                      f"Trades fermés : {len(closed)}\nTrades ouverts : {open_count}\n"
                      f"(minimum 2 requis pour les statistiques)")
        return

    returns = [t["pnl_pct"] for t in closed]
    pnl_usdc = [t["pnl_usdc"] for t in closed]

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_rate = len(wins) / len(returns) * 100
    expectancy = sum(returns) / len(returns)
    total_pnl = sum(pnl_usdc)

    # Sharpe annualisé (6 cycles/jour = 2190 cycles/an)
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0001
        sharpe = (mean_r / std_r) * math.sqrt(2190) if std_r > 0 else 0
    else:
        sharpe = 0

    # Max drawdown
    cumulative = 0
    peak = 0
    max_dd = 0
    for r in pnl_usdc:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # t-test manuel (H0: mean = 0)
    n = len(returns)
    mean_r = sum(returns) / n
    if n > 1:
        variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_err = math.sqrt(variance / n)
        t_stat = mean_r / std_err if std_err > 0 else 0
        abs_t = abs(t_stat)
        if n >= 30:
            z = abs_t / math.sqrt(2)
            t_val = 1 / (1 + 0.3275911 * z)
            poly = t_val * (0.254829592 + t_val * (-0.284496736 + t_val * (1.421413741 + t_val * (-1.453152027 + t_val * 1.061405429))))
            p_approx = 2 * poly * math.exp(-z * z)
            p_approx = max(0.001, min(p_approx, 1.0))
        else:
            p_approx = None
    else:
        t_stat = 0
        p_approx = None

    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')

    lines = [f"📈 <b>Performance — {len(closed)} trades fermés</b>\n"]
    lines.append(f"Win rate    : <code>{win_rate:.1f}%</code>  ({len(wins)}W / {len(losses)}L)")
    lines.append(f"Expectancy  : <code>{expectancy:+.2f}%</code> / trade")
    lines.append(f"Profit factor : <code>{profit_factor:.2f}</code>")
    lines.append(f"Moy. gain   : <code>{avg_win:+.2f}%</code>  |  Moy. perte : <code>{avg_loss:.2f}%</code>")
    lines.append(f"Sharpe      : <code>{sharpe:.2f}</code> (annualisé)")
    lines.append(f"Max drawdown: <code>-{max_dd:.2f} USDC</code>")
    lines.append(f"PnL total   : <code>{total_pnl:+.2f} USDC</code>\n")

    lines.append("📊 <b>Significativité statistique</b>")
    lines.append(f"t-stat : <code>{t_stat:.2f}</code>  |  n = {n}")
    if p_approx is not None:
        sig = "✅ Edge significatif (p &lt; 0.05)" if p_approx < 0.05 else "⚠️ Pas encore significatif"
        lines.append(f"p-value ≈ <code>{p_approx:.3f}</code>  →  {sig}")
    else:
        lines.append("⚠️ p-value : besoin de 30+ trades pour estimation fiable")
        lines.append(f"Progress : {n}/30 trades")

    if open_trades := [t for t in history if t.get("status") == "open"]:
        lines.append(f"\n🔓 Positions ouvertes : {len(open_trades)}")

    send_telegram("\n".join(lines), parse_mode="HTML")


def _format_stream_event(line: str):
    """Transforme une ligne stream-json de Claude Code en log humain (ou None à ignorer)."""
    try:
        e = json.loads(line)
    except Exception:
        return None
    ts = datetime.now().strftime("%H:%M:%S")
    etype = e.get("type")

    if etype == "system" and e.get("subtype") == "init":
        return f"[{ts}] 🚀 init | model={e.get('model', '?')} | session={e.get('session_id', '?')[:8]}"

    if etype == "assistant":
        out = []
        for block in e.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text":
                text = (block.get("text") or "").strip().replace("\n", " ")
                if text:
                    out.append(f"[{ts}] 💬 {text[:500]}")
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = json.dumps(block.get("input") or {}, ensure_ascii=False)
                out.append(f"[{ts}] 🔧 {name} {inp[:300]}")
        return "\n".join(out) if out else None

    if etype == "user":
        out = []
        for block in e.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                txt = str(content or "").replace("\n", " ")
                out.append(f"[{ts}] ✅ tool_result → {txt[:300]}")
        return "\n".join(out) if out else None

    if etype == "result":
        dur = e.get("duration_ms", 0) / 1000.0
        cost = e.get("total_cost_usd")
        final = (e.get("result") or "").replace("\n", " ")[:500]
        cost_str = f" | cost=${cost:.4f}" if isinstance(cost, (int, float)) else ""
        return f"[{ts}] 🏁 done | {dur:.1f}s{cost_str}\n{final}"

    return None


_RESOURCE_ERROR_PATTERNS = [
    "Credit balance is too low",
    "rate_limit_error",
    "overloaded_error",
    "Your account has hit",
    "quota exceeded",
    "This model is currently overloaded",
]


def _is_resource_error(stdout_path):
    try:
        with open(stdout_path) as f:
            content = f.read()
        return any(p in content for p in _RESOURCE_ERROR_PATTERNS)
    except Exception:
        return False


def _read_last_jsonl_phase(jsonl_path):
    """Retourne le dernier objet JSON valide du fichier JSONL, ou None."""
    try:
        with open(jsonl_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return None
            # Remonte depuis la fin pour trouver la dernière ligne non vide
            buf_size = min(4096, size)
            f.seek(-buf_size, 2)
            tail = f.read().decode("utf-8", errors="replace")
        lines = [l.strip() for l in tail.splitlines() if l.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None


def _watchdog_thread(cycle_id, jsonl_path, stop_event):
    """Thread daemon : alerte Telegram si la mtime du JSONL de phases stalle > 15 min."""
    STALL_THRESHOLD = 900  # secondes
    POLL_INTERVAL = 60     # secondes
    already_warned = False
    last_mtime = None

    while not stop_event.is_set():
        stop_event.wait(timeout=POLL_INTERVAL)
        if stop_event.is_set():
            break

        try:
            mtime = os.path.getmtime(jsonl_path)
        except FileNotFoundError:
            # Le fichier n'existe pas encore — pas d'alerte, on attend
            continue
        except Exception:
            continue

        # Si la mtime a progressé depuis la dernière itération, reset le flag d'alerte
        if last_mtime is not None and mtime > last_mtime:
            already_warned = False
        last_mtime = mtime

        if already_warned:
            continue

        delta = time.time() - mtime
        if delta > STALL_THRESHOLD:
            last_phase = _read_last_jsonl_phase(jsonl_path)
            if last_phase is not None:
                phase_num = last_phase.get("phase", "?")
                elapsed_min = int(delta // 60)
                msg = f"⚠️ Cycle {cycle_id} bloqué en Phase {phase_num} depuis {elapsed_min} min"
            else:
                elapsed_min = int(delta // 60)
                msg = f"⚠️ Cycle {cycle_id} bloqué depuis {elapsed_min} min (aucune phase enregistrée)"
            send_telegram(msg)
            already_warned = True


def run_trade_workflow(trigger="manual"):
    global NEXT_AUTO_TRADE
    if is_locked():
        send_telegram("⏳ Un cycle est déjà en cours. Réessaie dans quelques minutes.")
        return

    acquire_lock()
    NEXT_AUTO_TRADE = next_4h_slot()

    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    started_at = datetime.now(timezone.utc)
    logger.info(f"[Cycle {cycle_id}] Démarrage (trigger={trigger})")

    if trigger == "auto":
        send_telegram(
            f"🤖 Cycle auto 4h démarré ({fmt_local(started_at)})\n"
            f"⏰ Prochain cycle auto : {fmt_next()}",
            parse_mode=None
        )
    else:
        send_telegram(
            f"🔧 Cycle manuel {cycle_id} démarré\n"
            f"⏰ Prochain cycle auto : {fmt_next()}",
            parse_mode=None
        )

    # Injecte le cycle_id, prompt_version + trigger dans le prompt
    prompt = (TRADE_PROMPT
              .replace("__CYCLE_ID__", cycle_id)
              .replace("__PROMPT_VERSION__", PROMPT_VERSION)
              .replace('"trigger": "manual"', f'"trigger": "{trigger}"'))

    stdout_path = f"{LOGS_DIR}/stdout/cycle_{cycle_id}.log"
    stderr_path = f"{LOGS_DIR}/stderr/cycle_{cycle_id}.log"
    phases_jsonl = f"{LOGS_DIR}/cycle_{cycle_id}_phases.jsonl"
    exit_code = -1

    stop_watchdog = threading.Event()
    watchdog = threading.Thread(
        target=_watchdog_thread,
        args=(cycle_id, phases_jsonl, stop_watchdog),
        daemon=True,
    )
    watchdog.start()

    try:
        # Streaming : Claude écrit en stream-json (1 event JSON par ligne) sur stdout. On parse
        # chaque ligne à la volée et on écrit une version humaine dans stdout_path → `tail -f`
        # montre les tool calls et résultats au fur et à mesure. Timer kill-after-3600s pour
        # protéger d'un cycle bloqué.
        sub_env = os.environ.copy()
        sub_env.pop("ANTHROPIC_API_KEY", None)

        with open(stdout_path, "w", buffering=1) as out_f, open(stderr_path, "w", buffering=1) as err_f:
            process = subprocess.Popen(
                ["claude", "--print", "--verbose", "--output-format", "stream-json",
                 "--dangerously-skip-permissions", prompt],
                stdout=subprocess.PIPE, stderr=err_f, text=True, cwd=PROJECT_DIR, bufsize=1,
                env=sub_env
            )
            timer = threading.Timer(3600, process.kill)
            timer.start()
            try:
                for raw_line in process.stdout:
                    formatted = _format_stream_event(raw_line.rstrip("\n"))
                    if formatted:
                        out_f.write(formatted + "\n")
                exit_code = process.wait()
            finally:
                timer.cancel()
                stop_watchdog.set()

        if exit_code != 0 and _is_resource_error(stdout_path) and os.environ.get("ANTHROPIC_API_KEY"):
            logger.info(f"[Cycle {cycle_id}] Ressource insuffisante — retry API Sonnet")
            send_telegram(f"⚠️ Abonnement insuffisant — retry via API Sonnet (cycle {cycle_id})...")
            with open(stdout_path, "w", buffering=1) as out_f, open(stderr_path, "w", buffering=1) as err_f:
                retry_process = subprocess.Popen(
                    ["claude", "--print", "--verbose", "--output-format", "stream-json",
                     "--dangerously-skip-permissions", "--model", "claude-sonnet-4-6", prompt],
                    stdout=subprocess.PIPE, stderr=err_f, text=True, cwd=PROJECT_DIR, bufsize=1,
                    env=os.environ.copy()
                )
                retry_timer = threading.Timer(3600, retry_process.kill)
                retry_timer.start()
                try:
                    for raw_line in retry_process.stdout:
                        formatted = _format_stream_event(raw_line.rstrip("\n"))
                        if formatted:
                            out_f.write(formatted + "\n")
                    exit_code = retry_process.wait()
                finally:
                    retry_timer.cancel()
            logger.info(f"[Cycle {cycle_id}] Mode fallback API Sonnet — exit={exit_code}")
        elif exit_code != 0 and _is_resource_error(stdout_path) and not os.environ.get("ANTHROPIC_API_KEY"):
            logger.warning(f"[Cycle {cycle_id}] Ressource insuffisante — pas de fallback possible (ANTHROPIC_API_KEY absent)")

        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        logger.info(f"[Cycle {cycle_id}] Terminé exit={exit_code} en {duration:.0f}s")

        # Extraction du coût API depuis le log stdout (ligne "🏁 done | Xs | cost=$X.XX")
        _cost_usd = None
        try:
            with open(stdout_path) as _f:
                for _line in _f:
                    _m = re.search(r'cost=\$([0-9]+\.[0-9]+)', _line)
                    if _m:
                        _cost_usd = float(_m.group(1))
        except Exception:
            pass

        # Mise à jour Mongo avec le coût (le document a déjà été créé par Phase 7)
        if _cost_usd is not None:
            try:
                db = get_mongo()
                if db is not None:
                    db.cycles.update_one(
                        {"_id": cycle_id},
                        {"$set": {"api_cost_usd": _cost_usd}}
                    )
            except Exception as e:
                logger.error(f"[Cycle {cycle_id}] Mongo cost update échec : {e}")

        if exit_code != 0:
            with open(stderr_path) as f:
                err_extract = (f.read()[:400] or "(vide)")
            send_telegram(
                f"❌ <b>Cycle {cycle_id}</b> — erreur (code {exit_code})\n"
                f"<code>{err_extract}</code>\n\n"
                f"📋 Logs : logs/stderr/cycle_{cycle_id}.log",
                parse_mode="HTML"
            )
            # Fallback Mongo : trace minimale en cas d'échec
            try:
                db = get_mongo()
                if db is not None:
                    db.cycles.update_one(
                        {"_id": cycle_id},
                        {"$set": {
                            "cycle_id": cycle_id,
                            "timestamp": started_at.isoformat(),
                            "status": "error",
                            "trigger": trigger,
                            "prompt_version": PROMPT_VERSION,
                            "exit_code": exit_code,
                            "duration_seconds": duration,
                            "api_cost_usd": _cost_usd,
                            "log_files": {"stdout": stdout_path, "stderr": stderr_path},
                            "explanation_fr": "Le cycle a échoué avant de produire un résultat exploitable. Voir les logs pour le détail."
                        }},
                        upsert=True
                    )
            except Exception as e:
                logger.error(f"[Cycle {cycle_id}] Mongo fallback échec : {e}")

    except subprocess.TimeoutExpired:
        send_telegram(f"⏰ Cycle {cycle_id} — timeout (>1h).")
        logger.error(f"[Cycle {cycle_id}] Timeout")
    except Exception as e:
        send_telegram(f"❌ Cycle {cycle_id} — erreur inattendue : {e}")
        logger.exception(f"[Cycle {cycle_id}] Exception")
    finally:
        stop_watchdog.set()
        release_lock()


def run_raisonnement():
    """Envoie l'explication vulgarisée du dernier cycle (lue depuis MongoDB)."""
    db = get_mongo()
    if db is None:
        send_telegram("⚠️ MongoDB non configuré (MONGODB_URI absent ou invalide dans .env).")
        return

    try:
        doc = db.cycles.find_one(sort=[("timestamp", -1)])
    except Exception as e:
        send_telegram(f"❌ Erreur Mongo : {e}")
        return

    if not doc:
        send_telegram("📭 Aucun cycle en base. Lance /trade pour générer le premier.")
        return

    cycle_id = doc.get("cycle_id", "?")
    lines = [f"🧠 <b>Raisonnement — cycle {cycle_id}</b>"]
    lines.append(f"<i>{doc.get('timestamp', '?')} · status: {doc.get('status', '?')}</i>\n")

    p = doc.get("portfolio") or {}
    if p:
        lines.append(f"💼 Portfolio : <code>{p.get('total_usdc', 0):.2f}</code> USDC")
        lines.append(f"   Budget dispo : <code>{p.get('budget_disponible', 0):.2f}</code>")
        lines.append(f"   Positions ouvertes : {p.get('positions_ouvertes', 0)}\n")

    m = doc.get("market_context") or {}
    if m:
        lines.append(f"📊 Sentiment : <b>{m.get('sentiment', '?')}</b>")
        lines.append(f"   Coins analysés : {m.get('universe_size', 0)}\n")

    explanation = doc.get("explanation_fr", "")
    if explanation:
        lines.append("💬 <b>Explication</b>")
        lines.append(explanation)

    orders = doc.get("orders_placed") or []
    if orders:
        lines.append(f"\n✅ <b>{len(orders)} ordre(s) placé(s)</b>")
        for o in orders[:5]:
            lines.append(f"  • {o.get('coin')} score {o.get('score', '?')}/10")
    else:
        lines.append("\n🚫 <b>Aucun ordre placé ce cycle</b>")

    send_telegram("\n".join(lines), parse_mode="HTML")


def handle_cout():
    """Affiche le coût API cumulé par cycle depuis MongoDB."""
    db = get_mongo()
    if db is None:
        send_telegram("⚠️ MongoDB non configuré (MONGODB_URI absent ou invalide dans .env).")
        return

    try:
        pipeline = [
            {"$match": {"api_cost_usd": {"$exists": True, "$ne": None}}},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$api_cost_usd"},
                "count": {"$sum": 1},
                "avg": {"$avg": "$api_cost_usd"}
            }}
        ]
        agg = list(db.cycles.aggregate(pipeline))
        if not agg:
            send_telegram("📭 Aucun cycle avec coût API enregistré pour l'instant. Lance /trade pour commencer.")
            return

        total = agg[0]["total"]
        count = agg[0]["count"]
        avg = agg[0]["avg"]

        # 5 cycles les plus chers
        top5 = list(db.cycles.find(
            {"api_cost_usd": {"$exists": True, "$ne": None}},
            {"cycle_id": 1, "api_cost_usd": 1, "orders_placed": 1}
        ).sort("api_cost_usd", -1).limit(5))

        # Dernier cycle avec coût
        last = db.cycles.find_one(
            {"api_cost_usd": {"$exists": True, "$ne": None}},
            sort=[("timestamp", -1)]
        )

        lines = [f"💸 Cout API Claude — {count} cycle(s)\n"]
        lines.append(f"Total cumule  : ${total:.4f}")
        lines.append(f"Cout moyen    : ${avg:.4f} / cycle")

        if last:
            last_cost = last.get("api_cost_usd", 0)
            lines.append(f"Dernier cycle : ${last_cost:.4f} ({last.get('cycle_id', '?')})")

        if top5:
            lines.append("\nTop 5 cycles les plus chers :")
            for doc in top5:
                nb_ordres = len(doc.get("orders_placed") or [])
                lines.append(f"  {doc.get('cycle_id', '?')} — ${doc.get('api_cost_usd', 0):.4f} ({nb_ordres} ordre(s))")

        send_telegram("\n".join(lines))
    except Exception as e:
        send_telegram(f"❌ Erreur /cout : {e}")


def handle_callback(cq):
    cq_chat_id = str(cq.get("from", {}).get("id", "") or
                     cq.get("message", {}).get("chat", {}).get("id", ""))
    if cq_chat_id != CHAT_ID:
        return
    action = cq.get("data", "")
    logger.info(f"[Bot] Callback: {action!r}")

    answer_text = "✅ Confirmé" if action == "CONFIRM" else "❌ Annulé."
    tg_post("answerCallbackQuery", {"callback_query_id": cq["id"], "text": answer_text})


def get_offset():
    try:
        with open(f"{PROJECT_DIR}/state/telegram_offset.json") as f:
            return json.load(f).get("offset", 0)
    except:
        return 0


def save_offset(offset):
    with open(f"{PROJECT_DIR}/state/telegram_offset.json", "w") as f:
        json.dump({"offset": offset}, f)


def main_loop():
    global NEXT_AUTO_TRADE

    tg_post("deleteWebhook", {})
    NEXT_AUTO_TRADE = next_4h_slot()
    offset = get_offset()

    if os.environ.get("ANTHROPIC_API_KEY"):
        claude_mode = "abonnement (fallback API Sonnet si ressource insuffisante)"
    else:
        claude_mode = "abonnement Claude Code"
    logger.info(f"Bot v2 démarre en mode polling (offset={offset})")
    logger.info(f"Chat ID autorisé : {CHAT_ID}")
    logger.info(f"Subprocess Claude : {claude_mode}")
    logger.info(f"Prochain cycle auto : {fmt_next()}")

    send_telegram(
        f"🤖 Bot v2 démarré\n"
        f"Commandes : /trade /status /perf /raisonnement /cout /reset\n"
        f"⏰ Prochain cycle auto : {fmt_next()}",
        parse_mode=None
    )

    while True:
        try:
            # Auto-scheduler : déclenche /trade au prochain slot 4h UTC
            if NEXT_AUTO_TRADE and datetime.now(timezone.utc) >= NEXT_AUTO_TRADE and not is_locked():
                logger.info(f"[Scheduler] Auto-trade -> prochain slot sera {next_4h_slot().strftime('%H:%M UTC')}")
                threading.Thread(target=run_trade_workflow, kwargs={"trigger": "auto"}, daemon=True).start()

            data = tg_post("getUpdates", {
                "offset": offset,
                "timeout": 10,
                "allowed_updates": ["message", "callback_query"]
            })
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                save_offset(offset)

                cq = update.get("callback_query")
                if cq:
                    handle_callback(cq)
                    continue

                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if chat_id != CHAT_ID:
                    logger.warning(f"[Security] Ignoré chat_id={chat_id}")
                    continue

                logger.info(f"[Bot] Commande: {text!r}")

                if text.startswith("/trade"):
                    threading.Thread(target=run_trade_workflow, kwargs={"trigger": "manual"}, daemon=True).start()
                elif text.startswith("/status"):
                    threading.Thread(target=run_status, daemon=True).start()
                elif text.startswith("/perf"):
                    threading.Thread(target=run_perf, daemon=True).start()
                elif text.startswith("/raisonnement"):
                    threading.Thread(target=run_raisonnement, daemon=True).start()
                elif text.startswith("/cout"):
                    threading.Thread(target=handle_cout, daemon=True).start()
                elif text.startswith("/reset"):
                    release_lock()
                    send_telegram(f"🔓 Lock réinitialisé.\n⏰ Prochain cycle auto : {fmt_next()}")
                elif text:
                    send_telegram(f"Commandes : /trade /status /perf /raisonnement /cout /reset\n⏰ Prochain cycle : {fmt_next()}")

        except Exception as e:
            logger.error(f"[Polling] Erreur: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main_loop()
