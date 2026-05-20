# Agent Binance — Bot de trading automatique

Bot de trading crypto Binance piloté par Telegram et Claude AI.

- Scan marché Binance via TradingView (top gainers, breakouts, sentiment, rating)
- Scoring multi-timeframe 4h + 1D (0-10 points)
- Exécution automatique BUY + Stop-Loss + Take-Profit
- Auto-scheduler : toutes les 4h alignées sur les clôtures TradingView (00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC)
- Journal de trades + commande `/perf` avec p-value (t-test)
- Capture complète du raisonnement Claude (logs locaux + MongoDB Atlas)
- Commande `/raisonnement` : explication vulgarisée du dernier cycle

---

## Prérequis

| Outil | Version | Usage |
|-------|---------|-------|
| Python | 3.10+ | Runtime du bot |
| [Claude CLI](https://docs.anthropic.com/claude-code) | latest | Agent IA (workflow de trading) |
| [binance-cli](https://github.com/binance/binance-cli) | latest | API Binance |
| curl | system | Appels Telegram API |
| MongoDB Atlas | tier M0 gratuit | Persistance des cycles |

---

## Installation

### 1. Cloner le projet

```bash
git clone https://github.com/yousmaaza/agent-binance.git
cd agent-binance
```

### 2. Installer les dépendances Python

```bash
pip3 install -r requirements.txt
```

### 3. Créer le cluster MongoDB Atlas

1. https://cloud.mongodb.com → créer un compte
2. Créer un cluster gratuit M0 (région la plus proche : Frankfurt ou Paris)
3. Database Access → ajouter un utilisateur (login/password)
4. Network Access → autoriser ton IP (ou `0.0.0.0/0` pour tester)
5. Connect → Drivers → copier l'URI Python

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

### Mode simple (foreground)

```bash
python3 -u scripts/webhook_server.py
```

### Mode daemon (background avec logs)

```bash
nohup python3 -u scripts/webhook_server.py >> state/daemon.log 2>&1 &
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
| `/reset` | Débloque le bot si un cycle est coincé |

> Le bot tourne aussi **automatiquement** toutes les 4h (00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC). Chaque notification Telegram affiche un `cycle_id` au format `YYYYMMDD_HHMMSS` pour retrouver les logs.

---

## Configuration (`config.json`)

```json
{
  "usdc_allocation_pct": 0.40,        // % du solde USDC alloué au trading
  "portfolio_coins": ["BTC", "STX", "XRP", "SOL", "SUI"],
  "min_signal_score": 6,              // score minimum sur 10 pour trader
  "risk_per_trade_pct": 0.01,         // risque max 1% du portfolio par trade
  "reward_risk_ratio": 3.0,           // objectif gain = 3× le risque
  "atr_stop_multiplier": 2.0,         // stop-loss à 2× ATR
  "max_open_positions": 5,            // positions simultanées max
  "max_correlated_positions": 2,      // max 2 positions sur des L1-alts corrélés
  "daily_loss_limit_pct": 0.05,       // pause si perte journalière > 5%
  "universe_scan_top_n": 20           // nombre de coins scannés à chaque cycle
}
```

---

## Architecture

```
agent-binance/
├── scripts/
│   └── webhook_server.py     ← bot principal (polling Telegram + auto-scheduler)
├── state/
│   ├── trade_history.json    ← journal de tous les trades (open/closed)
│   ├── agent_lock.json       ← mutex anti-double-exécution
│   └── daemon.log            ← logs runtime (gitignore)
├── logs/                     ← gitignore
│   ├── stdout/cycle_xxx.log  ← sortie brute Claude par cycle
│   ├── stderr/cycle_xxx.log  ← erreurs Claude par cycle
│   └── bot_YYYY-MM-DD.log    ← log interne loguru (rotation 1 jour, rétention 30j)
├── reports/                  ← rapports Markdown par cycle (gitignore)
├── config.json               ← paramètres de stratégie
├── requirements.txt          ← pymongo, loguru
├── .env                      ← secrets (gitignore)
└── .env.example              ← template secrets

MongoDB Atlas (cloud)
└── agent-binance (DB)
    └── cycles (collection)   ← un document par cycle avec décisions + explanation_fr
```

### Workflow d'un cycle (7 phases)

```
Phase 0 — Vérifications (daily loss limit, trades fermés auto)
Phase 1 — Scan marché (top gainers + volume breakouts + sentiment + rating)
Phase 2 — Analyse multi-timeframe 4h + 1D pour chaque candidat
Phase 3 — Scoring 0-10 + filtres (corrélation, liquidité, positions max)
Phase 4 — Sizing dynamique (risk 1% portfolio, stop ATR×2, TP 3:1)
Phase 5 — Exécution BUY LIMIT + STOP-LOSS + TAKE-PROFIT automatique
Phase 6 — Rapport Markdown dans reports/
Phase 7 — Persistance MongoDB (décisions + explanation_fr vulgarisée)
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

Un score ≥ 6 **ET** les deux timeframes haussiers → ordre placé.

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

## Review d'un cycle (`/raisonnement`)

Chaque cycle est persisté en MongoDB avec :
- **Décisions par coin** : score, signaux 4h/1D, RSI, décision (BUY/HOLD/SKIP), raison
- **Ordres placés** : entry, stop, TP, quantité, risque
- **Contexte marché** : sentiment, taille de l'univers, coins scannés
- **explanation_fr** : paragraphe vulgarisé (sans jargon crypto) pour relire facilement

La commande `/raisonnement` envoie sur Telegram le résumé du dernier cycle.

Pour debug d'erreur, lire directement les logs locaux :
```bash
ls -lt logs/stdout/ | head -5    # 5 derniers cycles
less logs/stdout/cycle_20260520_220500.log
```

---

## Sécurité

- Le bot n'accepte que les messages du `TELEGRAM_CHAT_ID` configuré
- Les clés API Binance ne sont **jamais** dans ce repo (profil `binance-cli` local)
- Le token Telegram et l'URI Mongo sont dans `.env` (gitignore)
- Aucun port entrant requis (mode polling uniquement)
- MongoDB Atlas : restreindre Network Access à ton IP en prod (pas `0.0.0.0/0`)
