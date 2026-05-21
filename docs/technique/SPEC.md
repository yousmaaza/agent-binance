# Spécification technique — agent-binance

> **Généré par** : `binance-doc-tech` one-shot
> **Dernière mise à jour** : 2026-05-21
> **Commit** : 054dc1f311198b3509599c088ff853efc79adeb7

---

## 1. Vue d'ensemble

`agent-binance` est un bot de trading Binance piloté par Telegram, fonctionnant en architecture polling-only (aucun port entrant, aucun tunnel). Un unique processus Python (`scripts/webhook_server.py`) poll Telegram en long-polling (timeout 30s) et déclenche un sous-processus Claude CLI (`claude --print --dangerously-skip-permissions`) à chaque commande `/trade` ou toutes les 4h via l'auto-scheduler intégré. Le sous-processus Claude orchestre 7 phases d'analyse de marché et d'exécution d'ordres via `binance-cli`, en utilisant les outils TradingView MCP pour les données marché et MongoDB Atlas pour la persistance des cycles. L'état persistant est stocké sous `state/` (JSON), les logs sous `logs/`, et toutes les notifications utilisateur sont envoyées en français via l'API Telegram (via `curl`).

---

## 2. Architecture

### 2.1 Process principal

```
main_loop()
├── Polling Telegram (long-poll 30s, via tg_post("getUpdates"))
│   ├── Filtre sécurité : chat_id == CHAT_ID uniquement
│   ├── dispatch callback_query → handle_callback()
│   └── dispatch commande texte → threading.Thread(target=handle_*)
│       ├── /trade    → run_trade_workflow(trigger="manual")
│       ├── /status   → run_status()
│       ├── /perf     → run_perf()
│       ├── /raisonnement → run_raisonnement()
│       └── /reset    → release_lock()
└── Auto-scheduler (slots 4h UTC : 00:05, 04:05, 08:05, 12:05, 16:05, 20:05)
    └── run_trade_workflow(trigger="auto")   [threading.Thread daemon]
        ├── acquire_lock()   [agent_lock.json]
        ├── sous-processus : claude --print --verbose --output-format stream-json
        │   --dangerously-skip-permissions <TRADE_PROMPT>
        │   ├── Phase 0 — Vérifications préalables (solde, daily loss limit, trades ouverts)
        │   ├── Phase 1 — Scan marché (top_gainers, volume_breakout, sentiment, rating_filter)
        │   ├── Phase 2 — Analyse multi-timeframe (coin_analysis 4h + 1d)
        │   ├── Phase 3 — Scoring 0-10 et sélection des candidats
        │   ├── Phase 4 — Sizing et préparation des ordres (ATR, risk fixe 1%)
        │   ├── Phase 5 — Exécution OTOCO sur Binance Spot
        │   ├── Phase 6 — Rapport fichier (reports/YYYY-MM-DD_HH-MM_trade.md)
        │   └── Phase 7 — Persistance MongoDB + notification Telegram de synthèse
        ├── stdout streamé → logs/stdout/cycle_{cycle_id}.log  (toujours)
        ├── stderr capturé → logs/stderr/cycle_{cycle_id}.log  (toujours)
        └── release_lock()   [finally]
```

### 2.2 Flux de données

```
Utilisateur Telegram
      │
      ▼  long-poll (curl, timeout 30s)
webhook_server.py (process principal)
      │
      ├──► tg_post() → curl → Telegram Bot API
      │                       (sendMessage, getUpdates, answerCallbackQuery)
      │
      ├──► run_status() ──────────────────────────► binance-cli spot get-account
      │                                              binance-cli spot get-open-orders
      │
      ├──► run_perf() ───────────────────────────► state/trade_history.json (lecture)
      │                                             (stats internes : Sharpe, t-test, drawdown)
      │
      ├──► run_raisonnement() ───────────────────► MongoDB Atlas (db.cycles.find_one)
      │
      └──► run_trade_workflow()
                │
                ▼  subprocess (stream-json)
           Claude CLI
                │
                ├──► mcp__tradingview__* (Phase 1 & 2)
                │     top_gainers, volume_breakout_scanner, market_sentiment,
                │     rating_filter, coin_analysis (4h, 1d)
                │
                ├──► binance-cli spot (Phases 0, 4, 5)
                │     get-account, get-open-orders, get-exchange-info,
                │     get-symbol-price-ticker, order-list-otoco
                │
                ├──► state/trade_history.json  (lecture Phase 0, écriture Phase 5)
                ├──► state/agent_lock.json     (release Phase 7)
                ├──► reports/*.md              (écriture Phase 6)
                │
                └──► MongoDB Atlas db.cycles   (upsert Phase 7)
                     + curl → Telegram         (notifications à chaque phase)
```

### 2.3 Composants externes

| Composant | Rôle | Config |
|---|---|---|
| Telegram Bot API | Interface utilisateur (commandes + notifications) | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` dans `.env` |
| Binance CLI | Consultation portefeuille, passage ordres OTOCO spot | profil `agent-profile` dans `~/.binance-cli/` |
| MongoDB Atlas | Persistance des cycles de trading (collection `cycles`) | `MONGODB_URI`, `MONGODB_DB` dans `.env` |
| TradingView MCP | Données marché : gainers, breakouts, sentiment, analyse coin | `.mcp.json` (MCP server `mcp__tradingview__*`) |
| Claude CLI | Orchestration du cycle de trading (sous-processus) | `ANTHROPIC_API_KEY` (pay-per-use) ou abonnement Claude Code |

---

## 3. Fonctions clés (`scripts/webhook_server.py`)

| Fonction | Ligne | Rôle |
|---|---|---|
| `_load_env()` | :23 | Charge le fichier `.env` dans `os.environ` au démarrage (parse manuel, sans dépendance python-dotenv) |
| `get_mongo()` | :61 | Connexion lazy à MongoDB Atlas — retourne la DB ou `None` si `MONGODB_URI` absent/injoignable |
| `next_4h_slot()` | :365 | Calcule le prochain slot 4h UTC aligné sur les clôtures TradingView (00:05, 04:05, ..., 20:05) |
| `fmt_local()` | :375 | Convertit un datetime UTC en chaîne heure locale lisible pour les notifications Telegram |
| `fmt_next()` | :434 | Retourne l'heure du prochain cycle auto en heure locale (via `NEXT_AUTO_TRADE` global) |
| `tg_post()` | :384 | Appel bas niveau vers l'API Telegram via `curl` subprocess — retourne le JSON parsé |
| `send_telegram()` | :399 | Envoie un message Telegram avec `chat_id` et `parse_mode` optionnel |
| `is_locked()` | :406 | Vérifie si un cycle est en cours (lit `agent_lock.json`) — expire automatiquement après 2h |
| `acquire_lock()` | :424 | Pose le mutex dans `agent_lock.json` avec timestamp UTC |
| `release_lock()` | :429 | Libère le mutex dans `agent_lock.json` |
| `run_status()` | :441 | Handler `/status` : appelle `binance-cli` pour solde + ordres ouverts, format HTML Telegram |
| `run_perf()` | :493 | Handler `/perf` : stats avancées depuis `trade_history.json` (win rate, Sharpe annualisé, max drawdown, t-test, p-value) — tout calculé à la main sans scipy |
| `_format_stream_event()` | :588 | Parse une ligne stream-json Claude CLI en log humain lisible (`init`, `assistant`, `tool_result`, `result`) |
| `run_trade_workflow()` | :635 | Orchestre un cycle complet : lock → subprocess Claude stream-json → capture logs → fallback Mongo en cas d'erreur → unlock |
| `run_raisonnement()` | :726 | Handler `/raisonnement` : lit le dernier cycle depuis MongoDB et renvoie l'explication vulgarisée en français |
| `handle_callback()` | :774 | Gère les réponses aux inline keyboards Telegram (CONFIRM/CANCEL → `pending_callback.json`) |
| `get_offset()` | :789 | Lit le dernier offset Telegram depuis `telegram_offset.json` (persistance entre redémarrages) |
| `save_offset()` | :796 | Persiste le nouvel offset Telegram dans `telegram_offset.json` |
| `main_loop()` | :802 | Boucle principale : supprime le webhook Telegram, initialise l'offset, poll en continu, déclenche l'auto-scheduler |

---

## 4. Commandes Telegram

| Commande | Fonction handler | Description |
|---|---|---|
| `/trade` | `run_trade_workflow(trigger="manual")` | Déclenche immédiatement un cycle complet d'analyse et de trading (7 phases) dans un thread daemon |
| `/status` | `run_status()` | Affiche le portefeuille Binance actuel (soldes, positions lockées, ordres ouverts, trades agent actifs) et l'heure du prochain cycle |
| `/perf` | `run_perf()` | Affiche les statistiques de performance sur les trades fermés : win rate, expectancy, profit factor, Sharpe annualisé, max drawdown, p-value (t-test) |
| `/raisonnement` | `run_raisonnement()` | Affiche l'explication vulgarisée en français du dernier cycle (lue depuis MongoDB, champ `explanation_fr`) |
| `/reset` | `release_lock()` (inline) | Réinitialise le mutex `agent_lock.json` si un cycle est resté bloqué (`running: true`) |
| _(toute autre commande)_ | `send_telegram()` (inline) | Renvoie la liste des commandes disponibles |

---

## 5. État persistant (`state/`)

| Fichier | Type | Rôle |
|---|---|---|
| `trade_history.json` | JSON array | Source de vérité des trades : chaque entrée contient `trade_id`, `coin`, `side`, `signal_score`, `entry_price`, `stop_price`, `tp_price`, `quantity`, `risk_usdc`, IDs des ordres OTOCO, `status` (open/closed), `pnl_usdc`, `pnl_pct`, dates |
| `agent_lock.json` | JSON object | Mutex de cycle : `{"running": bool, "started_at": ISO-UTC}` — expire automatiquement après 2h |
| `telegram_offset.json` | JSON object | Dernier `update_id + 1` des updates Telegram — permet de reprendre sans re-traiter les anciens messages après redémarrage |
| `pending_callback.json` | JSON object | Dernière réponse inline keyboard : `{"action": "CONFIRM"/"CANCEL", "timestamp": float}` — lu par le sous-processus Claude pour les confirmations |
| `pending_trades.json` | JSON array | Trades en attente de confirmation utilisateur (pré-exécution) |
| `webhook_pids.json` | JSON object | PIDs du processus webhook (usage legacy v1 / monitoring externe) |
| `daemon.log` | Log texte | Journal loguru du process principal (rotation à 10 MB, rétention 5 fichiers rotatifs) — premier fichier à consulter en cas d'anomalie |

---

## 6. Contraintes techniques (`CLAUDE.md`)

| Règle | Raison |
|---|---|
| Telegram via `curl` uniquement (jamais `urllib`) | `urllib.request` échoue avec `[Errno 8] nodename nor servname provided` en contexte `nohup` sur Mac (résolution DNS IPv6 sans connectivité IPv6) |
| Secrets uniquement via `.env` (jamais hardcodés) | Sécurité — `.env` est gitignoré ; `.env.example` documente les clés attendues |
| `PROJECT_DIR` calculé dynamiquement (`os.path.dirname(os.path.abspath(__file__))`) | Portabilité Mac → VPS Linux sans modification de code |
| Stdout et stderr du sous-processus Claude toujours capturés | Seul moyen de débugger un cycle qui plante avant la Phase 7 (qui écrit en Mongo) |
| UTC en interne, heure locale à l'affichage | Cohérence avec les slots TradingView 4h (00:05, 04:05... UTC) ; `fmt_local()` pour l'affichage |
| Auto-scheduler dans `main_loop()` (pas cron/systemd) | Mutualisation avec le polling Telegram déjà actif en permanence |
| Venv `.venv` Python 3.11 obligatoire | Isolation des dépendances, portabilité, divergence évitée avec le Python global Anaconda |
| `git-perso` avant tout `git`/`gh` remote | Configure l'identité git perso + l'index pip perso pour éviter attributions/résolutions incorrectes |
| Pas de tunnel Cloudflare/ngrok | Réseau corporate bloque QUIC (UDP 7844), TCP 7844, et les DNS trycloudflare.com |
| Pas de dépendances lourdes (scipy, pandas) | Le bot doit rester un script Python standalone ; les stats (Sharpe, t-test) sont implémentées à la main |

---

## 7. Configuration (`config.json`)

| Paramètre | Valeur par défaut | Rôle |
|---|---|---|
| `binance_profile` | `"agent-profile"` | Nom du profil `binance-cli` utilisé pour tous les appels API Binance |
| `usdc_allocation_pct` | `0.50` | Fraction du USDC libre allouée au trading (50%) |
| `portfolio_coins` | `["BTC", "STX", "XRP", "SOL", "SUI"]` | Coins systématiquement inclus dans l'univers de scan |
| `quote_asset` | `"USDC"` | Asset de cotation pour toutes les paires tradées |
| `order_type` | `"LIMIT"` | Type d'ordre d'entrée (ordre working de l'OTOCO) |
| `limit_offset_pct` | `0.005` | Décalage du prix limite par rapport au prix actuel (−0.5%) |
| `min_order_usdc` | `11` | Montant minimum d'un ordre en USDC (contrainte Binance) |
| `max_single_position_pct` | `0.35` | Part maximale du budget allouable à une seule position (35%) |
| `price_deviation_max_pct` | `0.02` | Drift maximum toléré entre pré-calcul et exécution (2%) — sinon ordre annulé |
| `approval_timeout_minutes` | `30` | Timeout (minutes) pour une confirmation utilisateur via inline keyboard (legacy) |
| `risk_per_trade_pct` | `0.01` | Risque fixe par trade en % du portefeuille total (1%) |
| `reward_risk_ratio` | `3.0` | Ratio reward/risk : le TP est posé à 3× la distance du stop |
| `min_signal_score` | `6` | Score minimum (sur 10) pour qu'un coin devienne candidat BUY |
| `max_correlated_positions` | `2` | Nombre maximum de positions simultanées dans le groupe corrélé L1-alts (SOL, SUI, STX, ETH) |
| `daily_loss_limit_pct` | `0.05` | Perte journalière maximum en % du portefeuille total (5%) — trading pausé si dépassé |
| `atr_stop_multiplier` | `2.0` | Multiplicateur ATR pour le calcul de la distance du stop-loss |
| `timeframes_required` | `["4h"]` | Timeframe(s) obligatoire(s) pour l'analyse (signal 4h = critère primaire) |
| `min_adx` | `20` | ADX minimum sur 4h pour valider la tendance (critère de score) |
| `max_open_positions` | `5` | Nombre maximum de positions ouvertes simultanément |
| `universe_scan_top_n` | `20` | Nombre maximum de coins dans l'univers de scan par cycle |

---

## 8. Dépendances

**Runtime** (`requirements.txt`) :
- `pymongo>=4.6.0` — client MongoDB pour la persistance des cycles (collection `cycles`)
- `loguru>=0.7.0` — logging structuré avec rotation automatique des fichiers

**Dev/Review** (`requirements-dev.txt`) :
- `ruff>=0.6.0` — linter et formateur Python (rapide, remplace flake8 + isort)
- `radon>=6.0.0` — métriques de complexité cyclomatique (utilisé par l'agent `review`)
- `bandit>=1.7.0` — analyse de sécurité statique Python
- `mypy>=1.11.0` — vérification de types statique

---

## 9. Changelog technique

| PR | Date | Changement clé |
|---|---|---|
| Initial release | 2025-xx-xx | Architecture polling-only v1, scripts shell legacy |
| v2 — 790b83a | 2025-xx-xx | Ajout capture raisonnement : loguru + MongoDB + commande `/raisonnement` |
| v2 — 2bf48c0 | 2025-xx-xx | Mise à jour README et ajout CLAUDE.md (contraintes non négociables) |
| Spec initiale | 2026-05-21 | Génération initiale de SPEC.md via `binance-doc-tech` one-shot |
| [#17](pr-17-rotation-loguru-daemon-log.md) | 2026-05-21 | Rotation loguru activée sur `state/daemon.log` (10 MB, 5 fichiers) ; remplacement des `print()` par loguru ; suppression du handler stderr par défaut (id=0) |
