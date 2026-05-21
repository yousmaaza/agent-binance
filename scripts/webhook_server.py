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

3. Placer l'ordre OTOCO (BUY LIMIT qui arme automatiquement TP+SL une fois rempli).
   Binance Spot interdit de poser un SELL avant de détenir l'actif : OTOCO résout ça en un seul
   appel atomique, le TP et le SL s'activent dès que le BUY est FILLED.

   binance-cli spot order-list-otoco --symbol {COIN}USDC \\
     --working-type LIMIT --working-side BUY --working-quantity {quantite} \\
     --working-price {prix_entry} --working-time-in-force GTC \\
     --pending-side SELL --pending-quantity {quantite} \\
     --pending-above-type LIMIT_MAKER --pending-above-price {prix_tp} \\
     --pending-below-type STOP_LOSS_LIMIT --pending-below-price {prix_stop} \\
       --pending-below-stop-price {prix_stop * 1.002} --pending-below-time-in-force GTC \\
     --profile agent-profile

   La réponse contient un `orderListId` et 3 `orderReports`. Récupère depuis ces reports :
     entry_order_id = orderReports[type=LIMIT].orderId         # le BUY working
     tp_order_id    = orderReports[type=LIMIT_MAKER].orderId   # le take-profit pending above
     stop_order_id  = orderReports[type=STOP_LOSS_LIMIT].orderId  # le stop-loss pending below
   Conserve aussi `order_list_id = orderListId` pour pouvoir annuler les 3 d'un coup si besoin
   via `binance-cli spot delete-order-list --symbol {COIN}USDC --orderListId {order_list_id}`.

   Si l'appel échoue (erreur Binance) → SKIP ce coin + tg("⚠️ OTOCO échec {COIN} : {err_msg}")

4. Enregistre dans state/trade_history.json (APPEND, ne pas écraser) :
import json, uuid
from datetime import datetime, timezone
with open("state/trade_history.json") as f:
    history = json.load(f)
history.append({
    "trade_id": str(uuid.uuid4())[:8],
    "date": datetime.now(timezone.utc).isoformat(),
    "coin": "{COIN}",
    "side": "BUY",
    "signal_score": {score},
    "entry_price": {prix_entry},
    "stop_price": {prix_stop},
    "tp_price": {prix_tp},
    "quantity": {quantite},
    "risk_usdc": {risk_usdc},
    "entry_order_id": {entry_order_id},
    "stop_order_id": {stop_order_id},
    "tp_order_id": {tp_order_id},
    "order_list_id": {order_list_id},
    "status": "open",
    "exit_price": None,
    "exit_date": None,
    "pnl_usdc": None,
    "pnl_pct": None
})
with open("state/trade_history.json", "w") as f:
    json.dump(history, f, indent=2)

5. Notification immédiate :
   tg("⚡ BUY {COIN}\\n{quantite} @ {prix_entry:.4g} USDC\\n🛑 Stop : {prix_stop:.4g} (-{risk_usdc:.2f} USDC)\\n🎯 TP : {prix_tp:.4g} (+{risk_usdc*reward_risk_ratio:.2f} USDC)\\nScore : {score}/10")

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
        with open(stdout_path, "w", buffering=1) as out_f, open(stderr_path, "w", buffering=1) as err_f:
            process = subprocess.Popen(
                ["claude", "--print", "--verbose", "--output-format", "stream-json",
                 "--dangerously-skip-permissions", prompt],
                stdout=subprocess.PIPE, stderr=err_f, text=True, cwd=PROJECT_DIR, bufsize=1
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

        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        logger.info(f"[Cycle {cycle_id}] Terminé exit={exit_code} en {duration:.0f}s")

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
                            "exit_code": exit_code,
                            "duration_seconds": duration,
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


def handle_callback(cq):
    cq_chat_id = str(cq.get("from", {}).get("id", "") or
                     cq.get("message", {}).get("chat", {}).get("id", ""))
    if cq_chat_id != CHAT_ID:
        return
    action = cq.get("data", "")
    logger.info(f"[Bot] Callback: {action!r}")

    with open(f"{PROJECT_DIR}/state/pending_callback.json", "w") as f:
        json.dump({"action": action, "timestamp": time.time()}, f)

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

    claude_mode = "API (pay-per-use)" if os.environ.get("ANTHROPIC_API_KEY") else "abonnement Claude Code"
    logger.info(f"Bot v2 demarre en mode polling (offset={offset})")
    logger.info(f"Chat ID autorise : {CHAT_ID}")
    logger.info(f"Subprocess Claude : {claude_mode}")
    logger.info(f"Prochain cycle auto : {fmt_next()}")

    send_telegram(
        f"🤖 Bot v2 démarré\n"
        f"Commandes : /trade /status /perf /raisonnement /reset\n"
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
                "timeout": 30,
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
                    logger.warning(f"[Security] Ignore chat_id={chat_id}")
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
                elif text.startswith("/reset"):
                    release_lock()
                    send_telegram(f"🔓 Lock réinitialisé.\n⏰ Prochain cycle auto : {fmt_next()}")
                elif text:
                    send_telegram(f"Commandes : /trade /status /perf /raisonnement /reset\n⏰ Prochain cycle : {fmt_next()}")

        except Exception as e:
            logger.error(f"[Polling] Erreur: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main_loop()
