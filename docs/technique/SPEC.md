# Spécification technique — agent-binance

> **Généré par** : `binance-doc-tech` one-shot
> **Dernière mise à jour** : 2026-05-25
> **Commit** : 640af44

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
│       ├── /cout     → handle_cout()
│       └── /reset    → release_lock()
└── Auto-scheduler (slots 4h UTC : 00:05, 04:05, 08:05, 12:05, 16:05, 20:05)
    └── run_trade_workflow(trigger="auto")   [threading.Thread daemon]
        ├── acquire_lock()   [agent_lock.json]
        ├── sous-processus : claude --print --verbose --output-format stream-json
        │   --dangerously-skip-permissions --model claude-sonnet-4-6 <TRADE_PROMPT>
        │   ├── Phase 0 — Vérifications préalables (solde, daily loss limit, trades ouverts)
        │   ├── Phase 1 — Scan marché (top_gainers, volume_breakout, sentiment, rating_filter)
        │   ├── Phase 2 — Analyse multi-timeframe (A: coin_analysis 4h sur tous, B: filtrage BUY 4h, C: coin_analysis 1d filtrée)
        │   ├── Phase 3 — Scoring 0-10 et sélection des candidats
        │   ├── Phase 4 — Sizing et préparation des ordres (ATR, risk fixe 1%)
        │   ├── Phase 5 — Exécution BUY MARKET + OCO SELL standalone
        │   ├── Phase 6 — Rapport fichier (reports/YYYY-MM-DD_HH-MM_trade.md)
        │   └── Phase 7 — Persistance MongoDB + notification Telegram de synthèse
        ├── stdout streamé → logs/stdout/cycle_{cycle_id}.log  (toujours)
        ├── stderr capturé → logs/stderr/cycle_{cycle_id}.log  (toujours)
        └── release_lock()   [finally]
```

![Phases du cycle de trading](../visuals/trade-phases.svg)

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
                │     get-symbol-price-ticker, order-market, order-list-oco
                │
                ├──► state/trade_history.json  (lecture Phase 0, écriture Phase 5)
                ├──► state/agent_lock.json     (release Phase 7)
                ├──► reports/*.md              (écriture Phase 6)
                │
                └──► MongoDB Atlas db.cycles   (upsert Phase 7)
                     + curl → Telegram         (notifications à chaque phase)
```

![Flux de données](../visuals/data-flow.svg)

### 2.3 Diagrammes

> Générés par le skill `/generate-diagrams` (D2 + Kroki.io). Sources versionnables dans `docs/visuals/*.d2`.

| Diagramme | Fichier source | Rendu SVG |
|---|---|---|
| Architecture globale | [`docs/visuals/architecture.d2`](../visuals/architecture.d2) | [`architecture.svg`](../visuals/architecture.svg) |
| Flux de données | [`docs/visuals/data-flow.d2`](../visuals/data-flow.d2) | [`data-flow.svg`](../visuals/data-flow.svg) |
| Commandes Telegram | [`docs/visuals/commands.d2`](../visuals/commands.d2) | [`commands.svg`](../visuals/commands.svg) |
| Phases du cycle | [`docs/visuals/trade-phases.d2`](../visuals/trade-phases.d2) | [`trade-phases.svg`](../visuals/trade-phases.svg) |
| Séquence /trade | [`docs/visuals/trade.d2`](../visuals/trade.d2) | [`trade.svg`](../visuals/trade.svg) |
| Auto-scheduler | [`docs/visuals/auto-scheduler.d2`](../visuals/auto-scheduler.d2) | [`auto-scheduler.svg`](../visuals/auto-scheduler.svg) |

![Architecture agent-binance](../visuals/architecture.svg)

---

### 2.4 Composants externes

| Composant | Rôle | Config |
|---|---|---|
| Telegram Bot API | Interface utilisateur (commandes + notifications) | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` dans `.env` |
| Binance CLI | Consultation portefeuille, passage ordres BUY MARKET + OCO spot | profil `agent-profile` dans `~/.binance-cli/` |
| MongoDB Atlas | Persistance des cycles de trading (collection `cycles`) | `MONGODB_URI`, `MONGODB_DB` dans `.env` |
| TradingView MCP | Données marché : gainers, breakouts, sentiment, analyse coin | `.mcp.json` (MCP server `mcp__tradingview__*`) |
| Claude CLI | Orchestration du cycle de trading (sous-processus) — mode abonnement uniquement via Claude Code CLI avec `--model claude-sonnet-4-6` forcé via `CLAUDE_CLI_FLAGS` (évite qu'Opus soit sélectionné par défaut sur Max) ; aucun fallback API ; en cas de dépassement de quota abonnement, le cycle s'arrête proprement avec notification Telegram | `ANTHROPIC_API_KEY` explicitement ignorée au chargement `.env` (jamais injectée dans le processus) ; `CLAUDE_CLI_FLAGS` et `RESOURCE_ERROR_PATTERNS` dans `binance-bot/config/llm.py` |

---

## 3. Fonctions clés (`scripts/webhook_server.py`)

| Fonction | Ligne | Rôle |
|---|---|---|
| `_load_env()` | :26 | Charge le fichier `.env` dans `os.environ` au démarrage (parse manuel, sans dépendance python-dotenv) |
| `get_mongo()` | :73 | Connexion lazy à MongoDB Atlas — retourne la DB ou `None` si `MONGODB_URI` absent/injoignable |
| `next_4h_slot()` | :420 | Calcule le prochain slot 4h UTC aligné sur les clôtures TradingView (00:05, 04:05, ..., 20:05) |
| `fmt_local()` | :430 | Convertit un datetime UTC en chaîne heure locale lisible pour les notifications Telegram |
| `fmt_next()` | :489 | Retourne l'heure du prochain cycle auto en heure locale (via `NEXT_AUTO_TRADE` global) |
| `tg_post()` | :439 | Appel bas niveau vers l'API Telegram via `curl` subprocess — retourne le JSON parsé |
| `send_telegram()` | :454 | Envoie un message Telegram avec `chat_id` et `parse_mode` optionnel |
| `is_locked()` | :461 | Vérifie si un cycle est en cours (lit `agent_lock.json`) — expire automatiquement après 2h |
| `acquire_lock()` | :479 | Pose le mutex dans `agent_lock.json` avec timestamp UTC |
| `release_lock()` | :484 | Libère le mutex dans `agent_lock.json` |
| `run_status()` | :496 | Handler `/status` : appelle `binance-cli` pour solde + ordres ouverts, format HTML Telegram |
| `run_perf()` | :548 | Handler `/perf` : stats avancées depuis `trade_history.json` (win rate, Sharpe annualisé, max drawdown, t-test, p-value) — tout calculé à la main sans scipy |
| `run_eval()` | commands/eval.py:11 | Handler `/eval` : rapport hebdomadaire synthétique (fiabilité cycles, performance, coût abonnement vs API, risque) — accepte `period_days` optionnel (défaut 7) |
| `_trades_section()` | commands/eval.py:32 | Analyse `trade_history.json` pour extraction win rate, PnL net, ratio gain/perte sur la période cutoff |
| `_cycles_and_cost_section()` | commands/eval.py:73 | Interroge MongoDB `cycles` pour taux complétude + ventilation coût abonnement proratisé vs surcoût API réel |
| `_risk_section()` | commands/eval.py:112 | Comptabilise les positions ouvertes sans stop-loss (`protection_failed`) dans `trade_history.json` |
| `_stat_note()` | commands/eval.py:124 | Génère avertissement si < 30 trades sur la période (échantillon trop petit) |
| `_parse_dt()` | commands/eval.py:133 | Utilitaire : parse ISO datetime string avec fallback UTC timezone |
| `_hb_start(phase)` | TRADE_PROMPT:111 | Démarre le chronomètre d'une phase (dans le sous-processus Claude) — mémorise le timestamp UTC dans `_hb_phase_start[phase]` |
| `hb(phase, status, summary)` | TRADE_PROMPT:114 | Clôture une phase (dans le sous-processus Claude) — calcule la durée, écrit une ligne JSON dans `logs/cycle_<id>_phases.jsonl`, flush immédiat |
| Bloc trailing stop _(Phase 0)_ | TRADE_PROMPT:264–365 | Exécuté en Phase 0 du sous-processus Claude, après `protection_failed` : pour chaque position `open` avec OCO actif, récupère le prix courant, remonte le stop-loss si progression ≥ 20% de la distance originale et marge ≥ 2% du prix, annule l'OCO existant et replace un nouvel OCO avec TP réévalué ; met à jour `trade_history.json` et notifie Telegram |
| `_format_stream_event()` | :643 | Parse une ligne stream-json Claude CLI en log humain lisible (`init`, `assistant`, `tool_result`, `result`) |
| `_RESOURCE_ERROR_PATTERNS` _(constante module)_ | :934 | Liste des 8 patterns de chaîne indiquant une erreur de ressource Claude (credit insuffisant, rate_limit_error, overloaded_error, session limit, etc.) — utilisée par `_is_resource_error()` |
| `_is_resource_error()` | :946 | Lit le fichier `logs/stdout/cycle_*.log` et retourne `True` si un pattern de ressource y est détecté — gère silencieusement les erreurs de lecture |
| `_read_last_jsonl_phase()` | :690 | Lit la dernière ligne valide du fichier `cycle_<id>_phases.jsonl` — utilisé par le watchdog pour connaître la dernière phase complétée |
| `_watchdog_thread()` | :710 | Thread daemon qui surveille le cycle actif via le JSONL des heartbeats : alerte Telegram si aucune phase ne progresse pendant > 15 min |
| `PROMPT_VERSION` _(constante module)_ | :410 | Hash SHA-1 (8 chars hex) du `_TRADE_PROMPT_TEMPLATE` brut, calculé au boot — injecté dans le document Mongo comme `prompt_version` pour tracer la version du prompt par cycle |
| `run_trade_workflow()` | runner.py:21 | Orchestre un cycle complet : lock → extraction du modèle depuis `CLAUDE_CLI_FLAGS` → notifications Telegram de démarrage (modèle + mode abonnement affiché) → subprocess Claude (sans `ANTHROPIC_API_KEY` — mode abonnement uniquement) → capture logs stdout/stderr → extraction coût API → update Mongo `api_cost_usd` et `billing_mode: "abonnement"` → si erreur ressource détectée, envoie message Telegram explicite et marque le cycle en erreur → fallback Mongo en cas d'erreur → unlock |
| `_run_claude()` | runner.py:110 | Lance le sous-processus Claude CLI avec flags configurables : streame les événements stream-json depuis stdout, parse chaque ligne via `parse_stream_event()`, écrit les lignes formatées dans le fichier log stdout. Exécution en mode abonnement uniquement (pas de retry fallback API). Timeout 3600s avec timer. |
| `parse_stream_event()` | stream_parser.py:8 | Parse une ligne stream-json de Claude CLI en log humain lisible, sans paramètre `session_cb` (mécanisme supprimé avec le fallback API). Transforme : `system/init` → log d'init, `assistant` → blocs texte + tool_use, `user` → tool_result, `result` → résumé + durée + coût. |
| `_update_billing_mode_in_mongo()` | runner.py:156 | Enregistre le mode de facturation (`"abonnement"` ou `"api"`) dans Mongo après chaque cycle (distinction primaire vs fallback API) |
| `run_raisonnement()` | :864 | Handler `/raisonnement` : lit le dernier cycle depuis MongoDB et renvoie l'explication vulgarisée en français |
| `handle_cout()` | :1078 | Handler `/cout` : pipeline d'agrégation MongoDB (total cumulé, moyenne, dernier cycle, top 5 des cycles les plus chers) — silencieux si MongoDB absent |
| `handle_callback()` | :912 | Gère les réponses aux inline keyboards Telegram (CONFIRM/CANCEL → `pending_callback.json`) |
| `get_offset()` | :927 | Lit le dernier offset Telegram depuis `telegram_offset.json` (persistance entre redémarrages) |
| `save_offset()` | :935 | Persiste le nouvel offset Telegram dans `telegram_offset.json` |
| `main_loop()` | :940 | Boucle principale : supprime le webhook Telegram, initialise l'offset, poll en continu, déclenche l'auto-scheduler |

---

## 4. Commandes Telegram

| Commande | Fonction handler | Description |
|---|---|---|
| `/trade` | `run_trade_workflow(trigger="manual")` | Déclenche immédiatement un cycle complet d'analyse et de trading (7 phases) dans un thread daemon |
| `/status` | `run_status()` | Affiche le portefeuille Binance actuel (soldes, positions lockées, ordres ouverts, trades agent actifs) et l'heure du prochain cycle |
| `/perf` | `run_perf()` | Affiche les statistiques de performance sur les trades fermés : win rate, expectancy, profit factor, Sharpe annualisé, max drawdown, p-value (t-test) |
| `/raisonnement` | `run_raisonnement()` | Affiche l'explication vulgarisée en français du dernier cycle (lue depuis MongoDB, champ `explanation_fr`) |
| `/cout` | `handle_cout()` | Affiche les métriques de coût API Claude : total cumulé, coût moyen par cycle, dernier cycle, top 5 des cycles les plus chers — nécessite MongoDB |
| `/eval` | `run_eval(period_days=7)` | Affiche un rapport synthétique hebdomadaire : fiabilité des cycles (taux complétude), performance commerciale (win rate, PnL, ratio G/P), coût réel (abonnement proratisé vs surcoût API), et risque (positions sans stop-loss) — support paramètre `--days N` en CLI uniquement |
| `/reset` | `release_lock()` (inline) | Réinitialise le mutex `agent_lock.json` si un cycle est resté bloqué (`running: true`) |
| _(toute autre commande)_ | `send_telegram()` (inline) | Renvoie la liste des commandes disponibles |

---

## 5. État persistant (`state/`)

| Fichier | Type | Rôle |
|---|---|---|
| `trade_history.json` | JSON array | Source de vérité des trades : chaque entrée contient `trade_id`, `coin`, `side`, `signal_score`, `entry_price` (prix de fill réel), `stop_price`, `tp_price`, `quantity`, `risk_usdc`, `entry_order_id` (BUY MARKET), `tp_order_id`, `stop_order_id`, `order_list_id`, `protection_failed`, `status` (open/closed), `pnl_usdc`, `pnl_pct`, `close_reason`, dates |
| `agent_lock.json` | JSON object | Mutex de cycle : `{"running": bool, "started_at": ISO-UTC}` — expire automatiquement après 2h |
| `telegram_offset.json` | JSON object | Dernier `update_id + 1` des updates Telegram — permet de reprendre sans re-traiter les anciens messages après redémarrage |
| `pending_callback.json` | JSON object | Dernière réponse inline keyboard : `{"action": "CONFIRM"/"CANCEL", "timestamp": float}` — lu par le sous-processus Claude pour les confirmations |
| `pending_trades.json` | JSON array | Trades en attente de confirmation utilisateur (pré-exécution) |
| `webhook_pids.json` | JSON object | PIDs du processus webhook (usage legacy v1 / monitoring externe) |
| `daemon.log` | Log texte | Journal loguru du process principal (rotation à 10 MB, rétention 5 fichiers rotatifs) — premier fichier à consulter en cas d'anomalie |

**Logs de cycle** (`logs/`) :

| Fichier | Type | Rôle |
|---|---|---|
| `logs/stdout/cycle_<id>.log` | Log brut | Sortie stdout du sous-processus Claude (stream-json) — toujours écrit, même en cas d'erreur |
| `logs/stderr/cycle_<id>.log` | Log brut | Sortie stderr du sous-processus Claude — toujours écrit, même en cas d'erreur |
| `logs/cycle_<id>_phases.jsonl` | JSONL | Heartbeats par phase : une ligne JSON par phase terminée (0–7), avec `ts`, `phase`, `status`, `duration_s`, `summary` — base pour le watchdog ticket #7 |

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
| [#56](pr-56-trailing-stop-remonter-stop-loss.md) | 2026-05-22 | Ajout trailing stop dans Phase 0 du TRADE_PROMPT : remonte le stop-loss et recalcule le TP si le prix a progressé de plus de 20% de la distance originale, avec annulation/replacement de l'OCO |
| [#17](pr-17-rotation-loguru-daemon-log.md) | 2026-05-21 | Rotation loguru activée sur `state/daemon.log` (10 MB, 5 fichiers) ; remplacement des `print()` par loguru ; suppression du handler stderr par défaut (id=0) |
| [#21](pr-21-differencer-notif-telegram-manual-vs-auto.md) | 2026-05-21 | Notification de démarrage de cycle différenciée : `🤖 Cycle auto 4h démarré (heure locale)` vs `🔧 Cycle manuel {cycle_id} démarré` ; suppression de `parse_mode="HTML"` sur ces messages |
| [#22](pr-22-ajout-prompt-version-sha1-mongo.md) | 2026-05-21 | Ajout de `PROMPT_VERSION` (SHA-1 8 chars sur le template brut) injecté dans chaque document Mongo `cycles` sous le champ `prompt_version` |
| [#23](pr-23-heartbeats-par-phase-jsonl.md) | 2026-05-21 | Injection de `_hb_start()`/`hb()` dans le TRADE_PROMPT : écrit `logs/cycle_<id>_phases.jsonl` avec timestamp, durée et résumé à la fin de chaque phase 0–7 |
| [#28](pr-28-supprimer-double-handler-loguru-daemon.md) | 2026-05-21 | `logger.remove(0)` déplacé avant tout `logger.add()` (ligne :23, juste après l'import) ; suppression du guard `_DAEMON_LOG_ADDED` devenu inutile — corrige la double écriture résiduelle dans `daemon.log` |
| [#36](pr-36-uniformiser-accents-logger-boot.md) | 2026-05-21 | Correction orthographique de 3 messages `logger.*()` dans `main_loop()` : `demarre` → `démarre`, `autorise` → `autorisé`, `Ignore` → `Ignoré` — aucun impact fonctionnel |
| [#39](pr-39-phase5-buy-market-oco-protection.md) | 2026-05-22 | Phase 5 : suppression `order-list-otoco`, remplacement par `order-market` BUY + `order-list-oco` SELL calculé sur le prix de fill réel (`cummulativeQuoteQty/executedQty`) ; Phase 0 : routine idempotente de rattrapage `protection_failed` (fermeture market ou OCO selon position du prix vs TP) |
| [#46](pr-46-prompt-version-fallback-mongo-erreur.md) | 2026-05-22 | Ajout de `prompt_version` dans le `$set` du fallback Mongo `status: "error"` de `run_trade_workflow()` — tous les documents `cycles` sont désormais filtrables par version de prompt, y compris les cycles échoués |
| [#48](pr-48-suivre-le-cout-api-par-cycle.md) | 2026-05-22 | Extraction du coût API Claude par cycle (regex sur stdout) → champ `api_cost_usd` dans Mongo ; nouvelle commande `/cout` (total, moyenne, top 5) |
| [#50](pr-50-fallback-abonnement-api-sonnet.md) | 2026-05-22 | Subprocess primaire lancé sans `ANTHROPIC_API_KEY` (mode abonnement) ; fallback automatique sur `claude-sonnet-4-6` via API si erreur de ressource (credit/rate_limit/overloaded) et clé disponible dans `.env` ; nouvelle fonction `_is_resource_error()` |
| [#65](pr-65-session-limit-fallback-pattern.md) | 2026-05-22 | Ajout de `"You've hit your session limit"` et `"session limit"` dans `_RESOURCE_ERROR_PATTERNS` (hotfix cycle 20260522_140354) — le fallback Sonnet API se déclenche désormais sur les erreurs de limite de session |
| [#80](pr-80-config-llm-sonnet-abonnement-api.md) | 2026-05-23 | Ajout de `--model claude-sonnet-4-6` dans `CLAUDE_CLI_FLAGS` (`binance-bot/config/llm.py`) — le subprocess primaire force Sonnet sur l'abonnement Max au lieu de laisser le CLI choisir Opus par défaut ; les deux chemins (abonnement et API fallback) utilisent désormais le même modèle |
| [#82](pr-82-afficher-modele-mode-notif-cycle.md) | 2026-05-23 | Affichage dynamique du modèle Claude et du mode (abonnement/API) dans les notifications Telegram de démarrage de cycle et de fallback — extrait depuis `CLAUDE_CLI_FLAGS` / `CLAUDE_MODEL_FALLBACK` (`binance-bot/orchestration/runner.py`) |
| [#87](pr-87-migrer-agents-workflows-haiku.md) | 2026-05-23 | Migration des agents CI/CD vers `claude-haiku-4-5-20251001` (binance-dev, doc-fonc, doc-tech, tech-lead-reviewer, ticket-manager) et des workflows GitHub Actions correspondants ; le bot de trading reste en Sonnet pour stratégie complexe |
| [#91](pr-91-commande-eval.md) | 2026-05-23 | Ajout commande `/eval` : rapport hebdomadaire synthétique (fiabilité cycles, performance trades, coût réel, risque) ; nouveau champ Mongo `billing_mode` ("abonnement"\|"api") pour distinguer les coûts primaires vs fallback API |
| [#98](pr-98-fallback-api-reprendre-session.md) | 2026-05-23 | Fallback API avec session resumption : capture du `session_id` dès l'init du subprocess Claude, puis retry fallback avec `--resume <session_id>` pour reprendre la conversation au lieu de relancer du début → coût API divisé par 5-10x, temps réduit de ~5min à ~1-2min |
| [#100](pr-100-supprimer-fallback-api.md) | 2026-05-24 | Suppression du fallback API : mode abonnement uniquement, `ANTHROPIC_API_KEY` explicitement ignorée au chargement `.env`, message d'erreur clair en cas de quota épuisé, simplification de `run_trade_workflow()` et `_update_billing_mode_in_mongo()` |
| [#104](pr-104-phase2-1d-filtre-buy.md) | 2026-05-24 | Phase 2 optimisée : restructuration en 3 étapes (A: analyse 4h sur tous, B: filtrage signal_4h BUY/STRONG_BUY, C: analyse 1d filtrée) ; réduction appels TradingView ~14 → ~8–10 par cycle |
| [#106](pr-106-filtre-usdc-couplage-1d.md) | 2026-05-25 | Phase 1 : filtre tradabilité USDC explicite (via `binance-cli spot ticker-price`) — éliminer coins non tradables avant TradingView ; Phase 2 : couplage 1D par groupe de 4 coins (appels 1D immédiatement après résultat 4h BUY) au lieu de batch séparé global |
| [#117](pr-117-ci-skip-doc-medium-report.md) | 2026-05-25 | CI/workflow : skip des jobs `tech-lead-review` et `doc-tech` sur la branche `doc/medium-report` (accumulation journal Medium, pas de code à reviewer) → économie quota agents |
| [#118](pr-118-medium-articles-workflow.md) | 2026-05-25 | Infrastructure Medium : agent `medium-articles-manager` (new/publish/update-index) + slash command `/medium` + branche `docs/medium-articles` + skip CI sur article/* et docs/medium-* → organisation documentaire des articles issus du projet |
