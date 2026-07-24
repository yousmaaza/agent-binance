# Agent Binance — Bot de trading automatique

Bot de trading crypto **Kraken** piloté par Telegram et Claude AI (le nom du repo garde une référence historique à Binance, mais l'exchange utilisé aujourd'hui est Kraken via `kraken-cli`).

- Scan de l'univers USDC Kraken + enrichissement via TradingView (top gainers, breakouts, sentiment) — paires USDC uniquement
- Scoring multi-timeframe 4h + 1D (0-10 points)
- Exécution automatique BUY MARKET/LIMIT + Stop-Loss + Take-Profit, avec surveillance temps réel (TP Watcher)
- Auto-scheduler : toutes les 4h alignées sur les clôtures TradingView (00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC)
- Journal de trades + commande `/perf` avec p-value (t-test)
- Suivi du coût API Claude par cycle (`/cout`) et rapport ROI hebdomadaire (`/eval`)
- Capture complète du raisonnement Claude (logs locaux + MongoDB Atlas)
- Commande `/raisonnement` : explication vulgarisée du dernier cycle
- Tourne en autonomie sur une VPS (voir [`deploy/README.md`](deploy/README.md)) — aucune dépendance à une machine perso

---

## Prérequis

| Outil | Version | Usage |
|-------|---------|-------|
| Python | **3.11** | Runtime du bot (venv `.venv`) |
| [Claude Code CLI](https://docs.anthropic.com/claude-code) | latest | Agent IA (workflow de trading), authentifié via abonnement Pro/Max — pas de clé API |
| [kraken-cli](https://github.com/krakenfx/kraken-cli) | latest | API Kraken (spot) |
| `uv`/`uvx` | latest | Lance le serveur MCP `tradingview-mcp-server` |
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
claude auth login
```

> Le bot fonctionne uniquement en mode **abonnement Claude Pro/Max** — `ANTHROPIC_API_KEY` est intentionnellement ignorée par le code (voir `.env.example` et `binance-bot/core/env.py`), aucun fallback pay-per-use.

Le fichier `.mcp.json` à la racine du projet active automatiquement deux serveurs MCP dans Claude CLI :
- `tradingview` (via `uvx`, aucune config nécessaire au-delà d'installer `uv`)
- `telegram-assistant` (script Python local) — lit `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` depuis l'environnement :

```bash
export TELEGRAM_BOT_TOKEN=$(grep TELEGRAM_TOKEN .env | cut -d= -f2)
export TELEGRAM_CHAT_ID=$(grep TELEGRAM_CHAT_ID .env | cut -d= -f2)
```

### 6. Configurer kraken-cli

```bash
kraken auth set
# Renseigne ta clé API et secret Kraken
# Permissions requises : lecture compte + trading spot
```

> ⚠️ Les credentials Kraken sont stockés dans **un fichier séparé du `.env` du projet** (`~/.config/kraken/config.toml` sur Linux, `~/Library/Application Support/kraken/config.toml` sur macOS) — à sauvegarder/migrer indépendamment si tu changes de machine. Vérifier avec `kraken auth test`.

### 7. Créer les fichiers d'état initiaux

```bash
mkdir -p state reports logs/stdout logs/stderr
echo '[]' > state/trade_history.json
echo '{"running": false, "started_at": null}' > state/agent_lock.json
echo '{"action": null, "timestamp": 0}' > state/pending_callback.json
```

---

## Démarrage

### En production : VPS autonome (recommandé)

Le bot tourne en continu sur une VPS Linux via systemd (interactif Telegram + auto-scheduler, aucune dépendance à une machine perso). Voir le guide complet : [`deploy/README.md`](deploy/README.md).

```bash
systemctl status webhook-bot --no-pager   # sur la VPS
```

### En local (dev/test ponctuel)

```bash
source .venv/bin/activate

# Mode simple (foreground)
python -u binance-bot/webhook_server.py

# Mode daemon (background avec logs)
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
pkill -f webhook_server.py   # local
systemctl stop webhook-bot   # VPS (root)
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
  "usdc_allocation_pct": 0.70,             // % du solde USDC alloué au trading
  "portfolio_coins": ["XBT", "XRP", "SOL"], // toujours inclus dans l'univers, même sous le seuil de volume
  "quote_asset": "USDC",                   // asset de cotation (paires *USDC uniquement)
  "order_type": "LIMIT",                   // type d'ordre d'entrée
  "limit_offset_pct": 0.005,              // décalage du prix LIMIT vs marché (0.5%)
  "min_order_usdc": 9,                     // montant minimum d'un ordre en USDC
  "max_single_position_pct": 0.65,         // max 65% du capital sur une seule position
  "price_deviation_max_pct": 0.02,         // écart max prix accepté vs signal (2%)
  "approval_timeout_minutes": 30,          // timeout attente confirmation manuelle

  "risk_per_trade_pct": 0.02,             // risque max 2% du portfolio par trade
  "reward_risk_ratio": 2.0,               // objectif gain = 2× le risque
  "min_signal_score": 6,                  // score minimum sur 10 pour trader
  "min_signal_score_degraded": 4,         // seuil abaissé si TradingView rate-limite le 1D
  "atr_stop_multiplier": 3.5,             // stop-loss à 3.5× ATR
  "timeframes_required": ["4h"],          // timeframes obligatoires pour valider un signal
  "min_adx": 20,                          // ADX minimum (force de tendance)
  "max_open_positions": 4,                // positions simultanées max
  "max_correlated_positions": 2,          // max 2 positions sur des L1-alts corrélés (SOL/SUI/STX/ETH)
  "daily_loss_limit_pct": 0.05,           // pause si perte journalière > 5%
  "universe_scan_top_n": 20,             // nombre de coins scannés à chaque cycle
  "min_volume_usdc": 500000,             // volume 24h min pour qu'un coin Kraken entre dans l'univers
  "min_profit_pct_take": 5.0,            // clôture auto si profit latent > 5% (Phase 0)
  "max_hold_days": 14,                   // durée max de détention d'une position
  "max_oco_retry": 3                     // tentatives de re-pose d'un ordre OCO échoué
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
│   │   └── status.py             ← /status — état du portfolio (+ santé TP Watcher)
│   ├── core/
│   │   ├── env.py                ← chargement .env
│   │   ├── lock.py                ← mutex anti-double-exécution
│   │   ├── telegram.py           ← envoi messages via curl
│   │   ├── timing.py             ← calcul slots 4h UTC
│   │   ├── tp_watcher.py         ← surveillance temps réel des take-profits (thread, tick 2 min)
│   │   ├── trade_helpers.py      ← wrapper kraken-cli + helper Telegram (tg())
│   │   ├── state_manager.py      ← lecture/écriture trade_history.json
│   │   ├── heartbeat.py          ← heartbeats par phase (détection cycle bloqué)
│   │   ├── position_helpers.py   ← calculs stop/TP/sizing partagés
│   │   └── phases/               ← un script par phase du cycle (voir workflow ci-dessous)
│   ├── botlogging/
│   │   └── cycle_logger.py       ← logs structurés par cycle
│   ├── orchestration/
│   │   ├── runner.py             ← exécution d'un cycle complet (8 phases)
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
├── deploy/
│   ├── README.md                 ← guide de setup complet sur VPS
│   └── webhook-bot.service       ← unit systemd (interactif + auto-scheduler)
├── state/
│   ├── trade_history.json        ← journal de tous les trades (open/closed)
│   ├── cycle_log.jsonl           ← historique compact des 90 derniers cycles
│   ├── agent_lock.json           ← mutex anti-double-exécution (gitignore)
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

### Workflow d'un cycle (8 phases)

```
Phase 0 — Snapshot portefeuille, clôture des positions en profit (min_profit_pct_take),
          trailing stop, retry des ordres OCO échoués, recalibrage TP
Phase 1 — Scan de l'univers USDC Kraken (filtre min_volume_usdc) + enrichissement TradingView
          (top gainers, volume breakouts, sentiment)
Phase 2 — Analyse multi-timeframe 4h + 1D pour chaque candidat
Phase 3 — Scoring 0-10 + filtres (corrélation, liquidité, positions max) — voir tableau ci-dessous
Phase 4 — Sizing dynamique (risk_per_trade_pct, stop ATR×multiplier, reward_risk_ratio)
Phase 5 — Exécution BUY/SELL + STOP-LOSS automatique
Phase 6 — Rapport Markdown dans reports/
Phase 7 — Persistance MongoDB (décisions + explanation_fr vulgarisée + coût API) + vérif heartbeats
Phase 8 — Écriture state/cycle_log.jsonl + commit/push git (trade_history.json + cycle_log.jsonl)
```

En parallèle, le **TP Watcher** (thread indépendant, tick toutes les 2 min) surveille les positions ouvertes et déclenche une vente dès qu'un take-profit est atteint, sans attendre le prochain cycle 4h.

---

## Scoring des signaux

| Critère | Points |
|---------|--------|
| Signal TradingView 4h = BUY/STRONG_BUY | +2 |
| Signal TradingView 1D = BUY/STRONG_BUY | +2 |
| RSI 4h entre 30 et 55 | +1 |
| MACD bullish cross 4h | +1 |
| Coin dans top gainers | +1 |
| Coin en volume breakout | +1 |
| Sentiment marché global haussier | +1 |
| Volume 24h > 2× la médiane des candidats | +1 |

Décision BUY seulement si **score ≥ `min_signal_score`** (6/10 par défaut) **ET** signal 4h = BUY/STRONG_BUY — le score seul ne suffit jamais, le signal 4h est un filtre obligatoire indépendant. En mode dégradé (TradingView rate-limite le 1D sur tous les candidats 4h-BUY), le seuil descend à `min_signal_score_degraded` (4/10). Score ≤ 3 sur une position déjà ouverte → signal SELL. Filtres additionnels : `max_open_positions`, `max_correlated_positions` (groupe L1-alts : SOL/SUI/STX/ETH).

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
cat logs/stderr/cycle_YYYYMMDD_HHMMSS.log           # erreur Claude/MCP/Kraken
```

Si le lock est resté coincé (`agent_lock.json` avec `running: true`) : envoyer `/reset` depuis Telegram.

Voir aussi [`deploy/README.md`](deploy/README.md#débogage-rapide) pour les pièges spécifiques au déploiement VPS (utilisateur non-root, auth Kraken séparée, identité git).

---

## TP Watcher — surveillance temps réel

Un thread indépendant tourne en continu à côté du cycle 4h (tick toutes les 2 minutes, défini dans `binance-bot/core/tp_watcher.py`) : il vérifie le prix courant de chaque position ouverte contre son take-profit calculé, et déclenche une vente **immédiatement** dès que le seuil est atteint — sans attendre le prochain cycle programmé. Il respecte le même mutex (`agent_lock.json`) que le cycle principal pour éviter toute exécution concurrente. Son état (`tp_watcher_state.json` : dernier tick, nombre de ventes) est visible via `/status`.

---

## Skip types (classification des coins non tradés)

Chaque coin évalué à un cycle reçoit une décision (BUY/HOLD/SKIP/SELL) et, si skippé, un `skip_type` persisté en MongoDB (`cycles.skip_type`) et dans `state/cycle_log.jsonl` :

| Type | Phase | Déclencheur |
|------|-------|-------------|
| **TYPE_A** | 3 (Scoring) | Score < seuil OU positions max atteintes OU corrélation excessive |
| **TYPE_B** | 4 (Sizing) | Montant < `min_order_usdc` OU stop calculé invalide |
| **TYPE_C** | 5 (Exécution) | Drift de prix > `price_deviation_max_pct` OU solde insuffisant |
| **TYPE_D** | 1 (Scan) | Paire indisponible sur Kraken OU volume < `min_volume_usdc` |

Utile pour distinguer un skip stratégique (TYPE_A, le plus fréquent) d'un skip technique (TYPE_C/D), et pour ajuster la stratégie (ex: TYPE_B fréquent → volatilité trop haute pour `risk_per_trade_pct` actuel).

---

## Sécurité

- Le bot n'accepte que les messages du `TELEGRAM_CHAT_ID` configuré
- Les clés API Kraken ne sont **jamais** dans ce repo (store séparé `~/.config/kraken/config.toml`, hors `.env`)
- Le token Telegram et l'URI Mongo sont dans `.env` (gitignore)
- Aucun port entrant requis (mode polling uniquement) — vrai aussi bien en local que sur la VPS de production
- Le CLI Claude ne s'exécute jamais en root/sudo (`--dangerously-skip-permissions` le refuse explicitement) — le bot tourne sous un utilisateur dédié non-root sur la VPS
- MongoDB Atlas : restreindre Network Access à ton IP en prod (pas `0.0.0.0/0`)