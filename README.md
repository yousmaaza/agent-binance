# Agent Binance — Bot de trading automatique

Bot de trading crypto Binance piloté par Telegram et Claude AI.

- Scan marché Binance via TradingView (top gainers, breakouts, sentiment, rating) — paires USDC uniquement
- Scoring multi-timeframe 4h + 1D (0-10 points)
- Exécution automatique BUY LIMIT + Stop-Loss + Take-Profit
- Auto-scheduler : toutes les 4h alignées sur les clôtures TradingView (00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC)
- Journal de trades + commande `/perf` avec p-value (t-test)
- Suivi du coût API Claude par cycle (`/cout`) et rapport ROI hebdomadaire (`/eval`)
- Capture complète du raisonnement Claude (logs locaux + MongoDB Atlas)
- Commande `/raisonnement` : explication vulgarisée du dernier cycle

---

## Prérequis

| Outil | Version | Usage |
|-------|---------|-------|
| Python | **3.11** | Runtime du bot (venv `.venv`) |
| [Claude CLI](https://docs.anthropic.com/claude-code) | latest | Agent IA (workflow de trading) |
| [binance-cli](https://github.com/binance/binance-cli) | latest | API Binance |
| curl | system | Appels Telegram API |
| MongoDB Atlas | tier M0 gratuit | Persistance des cycles (optionnel) |

---

## Installation

### 1. Cloner le projet

```bash
git clone https://github.com/yousmaaza/agent-binance.git
cd agent-binance
```

### 2. Créer le venv Python 3.11

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

> Le venv est gitignoré — chaque machine recrée le sien. Toujours activer `.venv` avant de lancer le bot.

### 3. Créer le cluster MongoDB Atlas *(optionnel mais recommandé)*

1. https://cloud.mongodb.com → créer un compte
2. Créer un cluster gratuit M0 (région la plus proche : Frankfurt ou Paris)
3. Database Access → ajouter un utilisateur (login/password)
4. Network Access → autoriser ton IP (ou `0.0.0.0/0` pour tester)
5. Connect → Drivers → copier l'URI Python

> Sans MongoDB, le bot tourne mais `/raisonnement`, `/cout` et `/eval` retournent un warning.

### 4. Configurer `.env`

```bash
cp .env.example .env
```

Édite `.env` :

```env
TELEGRAM_TOKEN=ton_token_ici              # @BotFather → /newbot
TELEGRAM_CHAT_ID=ton_chat_id_ici          # @userinfobot pour l'obtenir
MONGODB_URI=mongodb+srv://...             # URI copié depuis Atlas
MONGODB_DB=agent-binance
```

> ⚠️ Ne commite jamais `.env` — il est dans `.gitignore`.

### 5. Configurer Claude CLI

```bash
claude login    # ou exporter ANTHROPIC_API_KEY
```

Le fichier `.mcp.json` à la racine du projet active automatiquement le MCP TradingView dans Claude CLI.

Pour que le MCP lise les variables Telegram, exporte-les dans ton shell :

```bash
export TELEGRAM_BOT_TOKEN=$(grep TELEGRAM_TOKEN .env | cut -d= -f2)
export TELEGRAM_CHAT_ID=$(grep TELEGRAM_CHAT_ID .env | cut -d= -f2)
```

### 6. Configurer binance-cli

```bash
binance-cli configure --profile agent-profile
# Renseigne ta clé API et secret Binance
# Permissions requises : lecture compte + trading spot
```

### 7. Créer les fichiers d'état initiaux

```bash
mkdir -p state reports logs/stdout logs/stderr
echo '[]' > state/trade_history.json
echo '{"running": false, "started_at": null}' > state/agent_lock.json
echo '{"action": null, "timestamp": 0}' > state/pending_callback.json
```

---

## Démarrage

### Activer le venv (à chaque session shell)

```bash
source .venv/bin/activate
```

### Mode simple (foreground)

```bash
python -u binance-bot/webhook_server.py
```

### Mode daemon (background avec logs)

```bash
nohup .venv/bin/python -u binance-bot/webhook_server.py >> state/daemon.log 2>&1 &
echo "Bot démarré (PID: $!)"
```

### Suivre les logs en direct

```bash
tail -f state/daemon.log              # log principal du serveur
tail -f logs/bot_$(date +%Y-%m-%d).log # log interne loguru
```

### Arrêter le bot

```bash
pkill -f webhook_server.py
```

---

## Commandes Telegram

| Commande | Description |
|----------|-------------|
| `/trade` | Lance un cycle d'analyse et d'exécution immédiatement |
| `/status` | Affiche portfolio, ordres ouverts, heure du prochain cycle |
| `/perf` | Statistiques : win rate, Sharpe, max drawdown, p-value |
| `/raisonnement` | Explication vulgarisée du dernier cycle (depuis MongoDB) |
| `/cout` | Coût API Claude cumulé : total, moyenne, top 5 cycles (MongoDB requis) |
| `/eval` | Rapport ROI hebdomadaire : fiabilité, performance, coût abonnement vs API |
| `/reset` | Débloque le bot si un cycle est coincé |

> Le bot tourne aussi **automatiquement** toutes les 4h (00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC). Chaque notification Telegram affiche un `cycle_id` au format `YYYYMMDD_HHMMSS` pour retrouver les logs.

---

## Configuration (`config.json`)

```json
{
  "binance_profile": "agent-profile",      // profil binance-cli configuré localement
  "usdc_allocation_pct": 0.70,             // % du solde USDC alloué au trading
  "portfolio_coins": ["BTC", "STX", "XRP", "SOL", "SUI"],
  "quote_asset": "USDC",                   // asset de cotation (paires *USDC uniquement)
  "order_type": "LIMIT",                   // type d'ordre d'entrée
  "limit_offset_pct": 0.005,              // décalage du prix LIMIT vs marché (0.5%)
  "min_order_usdc": 11,                    // montant minimum d'un ordre en USDC
  "max_single_position_pct": 0.40,         // max 40% du capital sur une seule position
  "price_deviation_max_pct": 0.02,         // écart max prix accepté vs signal (2%)
  "approval_timeout_minutes": 30,          // timeout attente confirmation manuelle

  "risk_per_trade_pct": 0.02,             // risque max 2% du portfolio par trade
  "reward_risk_ratio": 3.0,               // objectif gain = 3× le risque
  "min_signal_score": 7,                  // score minimum sur 10 pour trader
  "atr_stop_multiplier": 2.5,             // stop-loss à 2.5× ATR
  "timeframes_required": ["4h"],          // timeframes obligatoires pour valider un signal
  "min_adx": 20,                          // ADX minimum (force de tendance)
  "max_open_positions": 3,                // positions simultanées max
  "max_correlated_positions": 2,          // max 2 positions sur des L1-alts corrélés
  "daily_loss_limit_pct": 0.05,           // pause si perte journalière > 5%
  "universe_scan_top_n": 20              // nombre de coins scannés à chaque cycle
}
```

---

## Architecture

```
agent-binance/
├── binance-bot/
│   ├── webhook_server.py         ← bot principal (polling Telegram + auto-scheduler)
│   ├── cli.py                    ← interface CLI (commandes manuelles)
│   ├── commands/
│   │   ├── cout.py               ← /cout — coût API par cycle
│   │   ├── eval.py               ← /eval — rapport ROI hebdomadaire
│   │   ├── perf.py               ← /perf — statistiques de performance
│   │   ├── raisonnement.py       ← /raisonnement — explication du dernier cycle
│   │   └── status.py             ← /status — état du portfolio
│   ├── core/
│   │   ├── env.py                ← chargement .env
│   │   ├── lock.py               ← mutex anti-double-exécution
│   │   ├── telegram.py           ← envoi messages via curl
│   │   └── timing.py             ← calcul slots 4h UTC
│   ├── orchestration/
│   │   ├── runner.py             ← exécution d'un cycle complet (7 phases)
│   │   ├── stream_parser.py      ← parsing stdout Claude (coût, statut)
│   │   └── watchdog.py           ← surveillance heartbeats
│   ├── storage/
│   │   └── mongo.py              ← persistance MongoDB Atlas
│   ├── models/
│   │   ├── cycle.py              ← modèle de données cycle
│   │   └── trade.py              ← modèle de données trade
│   └── config/
│       ├── app.py                ← lecture config.json
│       └── llm.py                ← paramètres modèle Claude
├── state/
│   ├── trade_history.json        ← journal de tous les trades (open/closed)
│   ├── agent_lock.json           ← mutex anti-double-exécution
│   └── daemon.log                ← logs runtime (gitignore)
├── logs/                         ← gitignore
│   ├── stdout/cycle_xxx.log      ← sortie brute Claude par cycle
│   ├── stderr/cycle_xxx.log      ← erreurs Claude par cycle
│   └── bot_YYYY-MM-DD.log        ← log interne loguru (rotation 1 jour, rétention 30j)
├── reports/                      ← rapports Markdown par cycle (gitignore)
├── config.json                   ← paramètres de stratégie
├── requirements.txt              ← pymongo, loguru, ...
├── .env                          ← secrets (gitignore)
└── .env.example                  ← template secrets

MongoDB Atlas (cloud)
└── agent-binance (DB)
    └── cycles (collection)       ← un document par cycle avec décisions + explanation_fr + coût API
```

### Workflow d'un cycle (7 phases)

```
Phase 0 — Vérifications (daily loss limit, trades fermés auto)
Phase 1 — Scan marché (top gainers + volume breakouts + sentiment + rating) — filtre paires USDC
Phase 2 — Analyse multi-timeframe 4h + 1D pour chaque candidat 4h BUY
Phase 3 — Scoring 0-10 + filtres (corrélation, liquidité, positions max)
Phase 4 — Sizing dynamique (risk 2% portfolio, stop ATR×2.5, TP 3:1)
Phase 5 — Exécution BUY LIMIT + STOP-LOSS + TAKE-PROFIT automatique
Phase 6 — Rapport Markdown dans reports/
Phase 7 — Persistance MongoDB (décisions + explanation_fr vulgarisée + coût API)
```

---

## Scoring des signaux

| Critère | Points |
|---------|--------|
| Signal TradingView 4h = BUY/STRONG_BUY | +2 |
| Signal TradingView 1D = BUY/STRONG_BUY | +2 |
| RSI 4h entre 30 et 55 | +1 |
| MACD bullish cross 4h | +1 |
| Volume breakout détecté | +1 |
| ADX 4h > 20 (tendance forte) | +1 |
| Sentiment marché haussier | +1 |
| Coin dans top gainers | +1 |

Un score ≥ 7 **ET** les deux timeframes haussiers → ordre placé.

---

## Tracking de performance (`/perf`)

```
📈 Performance — 30 trades fermés

Win rate      : 62%
Expectancy    : +0.43% / trade
Profit factor : 1.9
Sharpe        : 1.82 (annualisé)
Max drawdown  : -3.2 USDC
PnL total     : +12.40 USDC

📊 Significativité statistique
t-stat : 2.41 | n = 30
p-value ≈ 0.023 → ✅ Edge significatif (p < 0.05)
```

---

## Rapport ROI hebdomadaire (`/eval`)

La commande `/eval` fournit un rapport synthétique sur 7 jours (configurable) combinant :

- **Fiabilité** : cycles complétés vs erreurs, taux de complétion
- **Performance** : win rate, PnL net, ratio gain/perte
- **Coût** : dépense API Claude réelle vs coût abonnement proratisé, mode de facturation par cycle
- **Risque** : positions ouvertes sans stop-loss actif

---

## Review d'un cycle (`/raisonnement`)

Chaque cycle est persisté en MongoDB avec :
- **Décisions par coin** : score, signaux 4h/1D, RSI, décision (BUY/HOLD/SKIP), raison
- **Ordres placés** : entry, stop, TP, quantité, risque
- **Contexte marché** : sentiment, taille de l'univers, coins scannés
- **explanation_fr** : paragraphe vulgarisé (sans jargon crypto) pour relire facilement
- **api_cost_usd** : coût du cycle en dollars (extrait du stdout Claude)

La commande `/raisonnement` envoie sur Telegram le résumé du dernier cycle.

Pour debug d'erreur, lire directement les logs locaux :
```bash
ls -lt logs/stdout/ | head -5    # 5 derniers cycles
less logs/stdout/cycle_20260520_220500.log
```

---

## Debug d'un cycle qui plante

```bash
tail -20 state/daemon.log                           # erreur côté webhook_server
ls -lt logs/stderr/ | head -5                       # identifier le dernier cycle en erreur
cat logs/stderr/cycle_YYYYMMDD_HHMMSS.log           # erreur Claude/MCP/Binance
```

Si le lock est resté coincé (`agent_lock.json` avec `running: true`) : envoyer `/reset` depuis Telegram.

---

## Sécurité

- Le bot n'accepte que les messages du `TELEGRAM_CHAT_ID` configuré
- Les clés API Binance ne sont **jamais** dans ce repo (profil `binance-cli` local)
- Le token Telegram et l'URI Mongo sont dans `.env` (gitignore)
- Aucun port entrant requis (mode polling uniquement)
- MongoDB Atlas : restreindre Network Access à ton IP en prod (pas `0.0.0.0/0`)