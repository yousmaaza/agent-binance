# Spécification technique — agent-binance

> **Généré par** : `binance-doc-tech` one-shot (mise à jour PR-mergée)
> **Dernière mise à jour** : 2026-07-21 (PR #362)
> **Commit** : <current>

---

## 1. Vue d'ensemble

`agent-binance` est un bot de trading Binance piloté par Telegram, fonctionnant en architecture polling-only (aucun port entrant, aucun tunnel). Un unique processus Python (`binance-bot/webhook_server.py`) poll Telegram en long-polling (timeout 30s) et déclenche un sous-processus Claude CLI via `binance-bot/orchestration/runner.py:run_trade_workflow()` à chaque commande `/trade` ou toutes les 4h via l'auto-scheduler intégré. Le sous-processus Claude orchestre 9 phases (0–8) d'analyse de marché et d'exécution d'ordres via `kraken-cli`, en lisant le prompt assemblé depuis 9 sous-fichiers (`prompts/trade_prompt.txt` + `prompts/shared/` + `prompts/phases/`) via `core/env.py:assemble_prompt()`, en important des helpers réutilisables depuis les modules `core/trade_helpers.py` et `core/heartbeat.py`, et appelant les scripts de phase depuis `binance-bot/core/phases/phase{N}*.py`, en utilisant les outils TradingView MCP pour les données marché et MongoDB Atlas pour la persistance des cycles. L'état persistant est stocké sous `state/` (JSON), les logs sous `logs/`, et toutes les notifications utilisateur sont envoyées en français via l'API Telegram (via `curl`).

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
└── Auto-scheduler 4h (slots 4h UTC : 00:05, 04:05, 08:05, 12:05, 16:05, 20:05)  [SUPPRESSION #260 : scheduler 1h]
    └── run_trade_workflow(trigger="auto")   [threading.Thread daemon]
        ├── acquire_lock()   [agent_lock.json]
        ├── sous-processus : claude --print --verbose --output-format stream-json
        │   --dangerously-skip-permissions --model claude-sonnet-4-6 <TRADE_PROMPT>
        │   ├── Phase 0 — Vérifications préalables + calibrage (solde, daily loss limit, trades ouverts, réalisation de profits)  [INTÉGRATION #260]
        │   ├── Phase 1 — Scan marché (top_gainers, volume_breakout, sentiment, rating_filter)
        │   ├── Phase 2 — Analyse multi-timeframe (A: coin_analysis 4h sur tous, B: filtrage BUY 4h, C: coin_analysis 1d filtrée)
        │   ├── Phase 3 — Scoring 0-10 et sélection des candidats
        │   ├── Phase 4 — Sizing et préparation des ordres (ATR, risk fixe 1%)
        │   ├── Phase 5 — Exécution BUY MARKET + OCO SELL standalone
        │   ├── Phase 6 — Rapport fichier (reports/YYYY-MM-DD_HH-MM_trade.md)
        │   ├── Phase 7 — Persistance MongoDB + notification Telegram de synthèse
        │   └── Phase 8 — Écriture cycle_log.jsonl + git push
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
      ├──► run_status() ──────────────────────────► kraken-cli spot get-account
      │                                              kraken-cli spot get-open-orders
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
                ├──► kraken-cli spot (Phases 0, 1, 4, 5)
                │     get-account, get-open-orders, get-exchange-info, pairs,
                │     ticker-price (filtre tradabilité USDC — Phase 1),
                │     get-symbol-price-ticker, order-market, order (stop-loss)
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
| Kraken CLI | Consultation portefeuille, passage ordres BUY MARKET + SL (stop-loss) spot | Détection : `shutil.which("kraken")` ou fallback `~/.cargo/bin/kraken` |
| MongoDB Atlas | Persistance des cycles de trading (collection `cycles`) | `MONGODB_URI`, `MONGODB_DB` dans `.env` |
| TradingView MCP | Données marché : gainers, breakouts, sentiment, analyse coin | `.mcp.json` (MCP server `mcp__tradingview__*`) |
| Claude CLI | Orchestration du cycle de trading (sous-processus) — mode abonnement uniquement via Claude Code CLI avec `--model claude-sonnet-4-6` forcé via `CLAUDE_CLI_FLAGS` (évite qu'Opus soit sélectionné par défaut sur Max) ; aucun fallback API ; en cas de dépassement de quota abonnement, le cycle s'arrête proprement avec notification Telegram | `ANTHROPIC_API_KEY` explicitement ignorée au chargement `.env` (jamais injectée dans le processus) ; `CLAUDE_CLI_FLAGS` et `RESOURCE_ERROR_PATTERNS` dans `binance-bot/config/llm.py` |

---

## 3. Fonctions clés

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
| `run_status()` | commands/status.py:149 | Handler `/status` : appelle `kraken-cli` pour solde + ordres ouverts, affiche positions avec prix courant + PnL/distance TP, état TP Watcher, format HTML Telegram |
| `_fetch_current_price(coin)` | commands/status.py:78 | Appelle `kraken-cli ticker {coin}USDC` et retourne prix courant (float) ou `None` si indisponible — silencieuse sur erreur, log debug |
| `_format_trades_section(fmt_next)` | commands/status.py:92 | Formate la section trades actifs : pour chaque position ouverte, appelle `_fetch_current_price()`, calcule PnL % et distance TP, affiche prix courant et métriques |
| `_parse_last_tick(raw: str)` | commands/status.py:121 | Parse timestamp ISO 8601 du dernier tick, gère le Z redondant `+00:00Z`, retourne `datetime` aware UTC ou `None` |
| `_tp_watcher_health(last_tick_dt)` | commands/status.py:133 | Classe le watcher en 3 états selon l'âge du tick : `✅ OK` (<5 min), `⚠️ Lent` (5-10 min), `🔴 Inactif` (>10 min) |
| `_count_tp_watcher_sales_24h()` | commands/status.py:144 | Compte les ventes TP depuis `trade_history.json` : filtre `close_reason` contient `"tp_watcher"` + `exit_date` dans les 24h UTC |
| `_format_watcher_section()` | commands/status.py:172 | Lit `state/tp_watcher_state.json`, retourne section formatée avec 4 infos : emoji santé + label OK/Lent/Inactif, heure dernier tick (local), nb positions surveillées, ventes TP 24h ; gestion robuste si state absent/corrompu → `"⚠️ État inconnu"` |
| `_write_watcher_state(status, last_error, positions_checked, sales_delta=0)` | core/tp_watcher.py:18 | Écrit atomiquement `state/tp_watcher_state.json` via tempfile + `os.replace()` avec timestamp UTC ISO+Z, status (`ok`/`warning`/`error`), erreur optionnelle, compteur positions, compteurs cumulatifs `total_ticks` (incrément 1 à chaque appel) et `total_sales` (ajout `sales_delta` — nombre ventes TP ce tick) ; lecture persistence des compteurs précédents, initialise `total_ticks=1` à froid |
| `run_perf()` | commands/perf.py:273 | Handler `/perf` : orchestre 4 blocs de KPIs (P&L réalisé, Cycles, Positions, TP Watcher) depuis `trade_history.json` et MongoDB/Mongo fallback `cycle_log.jsonl` ; format HTML Telegram ; troncature si > 4000 chars |
| `_bloc_pnl()` | commands/perf.py:22 | Bloc 1 — P&L réalisé : stats totales/7j/30j, win rate, meilleur/pire trade, top 3 coins par P&L, durée moyenne de détention |
| `_bloc_cycles()` | commands/perf.py:124 | Bloc 2 — Cycles : total cycles, avec BUY, répartition TYPE_A/B/C/D, durée moyenne, erreurs/quota. Source Mongo en priorité, fallback `cycle_log.jsonl` transparent |
| `_load_cycles_jsonl()` | commands/perf.py:84 | Charge `state/cycle_log.jsonl` (fallback si Mongo non disponible) |
| `_format_cycle_lines()` | commands/perf.py:100 | Helper formatage unifié Bloc 2 (réutilisé Mongo et JSONL) |
| `_bloc_positions()` | commands/perf.py:177 | Bloc 3 — Positions : ouvertes/fermées, décomposition SL / TP Watcher / Profit Phase 0, série consécutive en cours (Win/Loss streak) |
| `_bloc_watcher()` | commands/perf.py:231 | Bloc 4 — TP Watcher : total_ticks, total_sales, ventes 24h/7j, USDC réalisés. Fallback "État inconnu" si `tp_watcher_state.json` absent |
| `run_eval()` | commands/eval.py:11 | Handler `/eval` : rapport hebdomadaire synthétique (fiabilité cycles, performance, coût abonnement vs API, risque) — accepte `period_days` optionnel (défaut 7) |
| `_trades_section()` | commands/eval.py:32 | Analyse `trade_history.json` pour extraction win rate, PnL net, ratio gain/perte sur la période cutoff |
| `_cycles_and_cost_section()` | commands/eval.py:73 | Interroge MongoDB `cycles` pour taux complétude + ventilation coût abonnement proratisé vs surcoût API réel |
| `_risk_section()` | commands/eval.py:112 | Comptabilise les positions ouvertes sans stop-loss (`protection_failed`) dans `trade_history.json` |
| `_stat_note()` | commands/eval.py:124 | Génère avertissement si < 30 trades sur la période (échantillon trop petit) |
| `_parse_dt()` | commands/eval.py:133 | Utilitaire : parse ISO datetime string avec fallback UTC timezone |
| `_validate_trade_history(data)` | core/state_manager.py:12 | Valide la structure list + dicts de `trade_history.json` — lève `ValueError` si invalide |
| `load_trade_history(path)` | core/state_manager.py:24 | Charge et valide `trade_history.json` — lève `ValueError`/`FileNotFoundError` |
| `save_trade_history(data, path)` | core/state_manager.py:45 | Sauvegarde atomique via tempfile + os.replace() ; valide avant écriture |
| `validate_and_repair_boot()` | core/state_manager.py:79 | Vérifie l'intégrité de `trade_history.json` au démarrage ; crée backup daté en cas de corruption, réinitialise à `[]` ; retourne `(is_valid, error_msg)` |
| `_hb_start(phase)` | core/heartbeat.py:31 | Démarre le chronomètre d'une phase — mémorise le timestamp UTC dans `_phase_start[phase]` |
| `hb(phase, status, summary)` | core/heartbeat.py:36 | Clôture une phase avec **déduplication** : relit le JSONL, supprime l'ancienne entrée si la phase existe, append la nouvelle ligne JSON ; calcule la durée ; flux immédiat |
| `init(cycle_id, trigger, project_dir)` | core/heartbeat.py:19 | Initialise l'état module-level du heartbeat pour un cycle — doit être appelée une fois en tête de chaque script de phase |
| `CycleLogger.warning()` | botlogging/cycle_logger.py:34 | Nouvelle méthode pour logger les avertissements au niveau cycle avec préfixe structuré ; complète les méthodes `info()` et `error()` existantes |
| `CycleLogger.debug()` | botlogging/cycle_logger.py:37 | Méthode pour logger les messages de debug au niveau cycle avec préfixe structuré ; complète les méthodes `info()`, `error()`, `warning()` existantes |
| `tg(text)` | core/trade_helpers.py:15 | Envoie une notification Telegram via `curl` (jamais `urllib`, cf. CLAUDE.md) — importée par les scripts de phase |
| `binance(*args, _retries=3)` | core/trade_helpers.py:29 | Helper retry-backoff (x3, sleep 2s/4s/6s) pour appels binance-cli ; détecte "Invalid symbol" et "Request failed" ; lève `RuntimeError` si tous les retries échouent |
| `_load_config(project_dir="")` | core/trade_helpers.py:43 | Charge `config.json` et retourne un dict ; retourne `{}` en cas d'erreur |
| `_save_json_atomic(data, path)` | core/trade_helpers.py:53 | Écriture atomic générique via tempfile + os.replace() ; utilisée par les 3 fonctions *_atomic() |
| `_save_trade_history_atomic(data, path_override="")` | core/trade_helpers.py:70 | Wrapper pour écriture atomique de `trade_history.json` |
| `_save_config_atomic(data, project_dir="")` | core/trade_helpers.py:76 | Wrapper pour écriture atomique de `config.json` |
| `log_phase0_event(cycle_id, phase, coin, action, details)` | core/trade_helpers.py:83 | Écrit un événement structuré (JSON) dans `logs/phase0_events.jsonl` pour traçabilité Phase 0 — chaque ligne inclut timestamp ISO (UTC), cycle_id, phase (phase0_oco_retry/phase0_trailing_stop), coin, action (protection_recovery_start, sl_retry_success, ts_update_success, etc.), et dict `details` libre ; silencieuse en cas d'erreur |
| Bloc trailing stop _(Phase 0)_ | phase0_trailing_stop.py | Exécuté en Phase 0 du sous-processus Claude, après `protection_failed` : pour chaque position `open` avec SL (`sl_order_txid`) actif, récupère le prix courant, remonte le stop-loss si progression ≥ 20% de la distance originale et marge ≥ 2% du prix, annule le SL existant et place un nouveau SL avec TP réévalué ; met à jour `trade_history.json` et notifie Telegram |
| `_format_stream_event()` | :643 | Parse une ligne stream-json Claude CLI en log humain lisible (`init`, `assistant`, `tool_result`, `result`) |
| `_RESOURCE_ERROR_PATTERNS` _(constante module)_ | :934 | Liste des 8 patterns de chaîne indiquant une erreur de ressource Claude (credit insuffisant, rate_limit_error, overloaded_error, session limit, etc.) — utilisée par `_is_resource_error()` |
| `_is_resource_error()` | :946 | Lit le fichier `logs/stdout/cycle_*.log` et retourne `True` si un pattern de ressource y est détecté — gère silencieusement les erreurs de lecture |
| `_read_last_jsonl_phase()` | :690 | Lit la dernière ligne valide du fichier `cycle_<id>_phases.jsonl` — utilisé par le watchdog pour connaître la dernière phase complétée |
| `_watchdog_thread()` | :710 | Thread daemon qui surveille le cycle actif via le JSONL des heartbeats : alerte Telegram si aucune phase ne progresse pendant > 15 min |
| `assemble_prompt(prompts_dir="")` | core/env.py:70 | Assemble le prompt de trading depuis 9 sous-fichiers dans l'ordre : header + api_reference + phase0..phase5 + phases6_8 ; retourne la chaîne concaténée |
| `get_cycle_phases_log_path(cycle_id)` | core/env.py:39 | Retourne le chemin du fichier heartbeat JSONL pour un cycle : `logs/cycle_{cycle_id}_phases.jsonl` |
| `PROMPT_VERSION` _(constante module)_ | core/env.py:102 | Hash SHA-1 (8 chars hex) du `_TRADE_PROMPT_TEMPLATE` assemblé, calculé au boot — injecté dans le document Mongo comme `prompt_version` pour tracer la version du prompt par cycle |
| `POSITION_PROMPT` _(constante module)_ | core/env.py:113–119 | Prompt pour cycle horaire de gestion des positions : template chargé depuis `prompts/position_prompt.txt` avec substitutions statiques (TOKEN, CHAT_ID, PROJECT_DIR, BINANCE_CLI_PATH) |
| `next_1h_slot()` | timing.py:16 | Calcule le prochain slot horaire `:05 UTC` en sautant les slots 4h (00:05, 04:05, ..., 20:05) pour éviter collision avec `next_4h_slot()` — retourne un datetime UTC |
| `parse_dt()` | timing.py:33 | Parse un timestamp ISO 8601 en datetime aware UTC, gère le suffixe redondant `+00:00Z` généralement par Phase 8 — utilisé par perf.py et status.py pour parsing robuste des champs `exit_date` |
| `run_trade_workflow()` | runner.py:23 | Orchestre un cycle complet de trading : appelle `_run_workflow_cycle()` avec callbacks spécialisés pour trade (watchdog=True, post-processing avec gestion quota abonnement) |
| `run_position_check_workflow()` | runner.py:46 | Orchestre un cycle horaire de gestion des positions : appelle `_run_workflow_cycle()` avec cycle_type="position", watchdog=False (cycle léger), post-processing minimaliste |
| `_run_workflow_cycle()` | runner.py:64 | Fonction commune d'orchestration pour tous les cycles : gère lock, cycle_id, logging, fichier helpers, invocation Claude, watchdog conditionnel, callbacks (on_lock_busy, on_start, on_post_run), cleanup. Permet la réutilisation entre cycles trade et position sans duplication |
| `_handle_trade_post_run()` | runner.py:170 | Post-processing du cycle trade : calcule `duration_s` (entier, en secondes) et classe `error_type` (null/"quota"/"crash"), met à jour Mongo (api_cost_usd, billing_mode, duration_s, error_type), gère erreur avec notification Telegram explicite |
| `_handle_position_post_run()` | runner.py:207 | Post-processing du cycle position : erreur détectée → notification Telegram minimaliste (max 400 chars, HTML) pour éviter spam en arrière-plan |
| `_update_perf_in_mongo()` | runner.py:422 | Persiste `duration_s` (int, durée du cycle en secondes) et `error_type` (null/‟quota"/‟crash") dans MongoDB via `update_one()` avec `$set` — appelée après chaque cycle de trade pour traçabilité performance et debugging des erreurs |
| `_check_and_run_scheduled()` | webhook_server.py:34 | Utilitaire de scheduling unifié : vérifie si c'est l'heure, calcule prochain slot, lance workflow en thread daemon, retourne le prochain slot — utilisé pour scheduler 1h (position) et 4h (trade) |
| `_write_helpers_file()` | runner.py:116 | Génère le fichier temporaire des helpers (tg, binance, hb, _hb_start, _save_trade_history_atomic) via `tempfile.mkstemp()` : permissions 0o600 garanties, secrets lus depuis `os.environ` au runtime (jamais substitués en dur), injectables dans le TRADE_PROMPT |
| `_send_start_notification()` | runner.py:99 | Envoie la notification Telegram de démarrage d'un cycle : affiche le modèle Claude utilisé (extrait depuis `CLAUDE_CLI_FLAGS`), le mode de facturation (abonnement), et l'heure du prochain cycle auto en heure locale ; différencie cycles manuels vs auto |
| `_run_claude()` | runner.py:336 | Lance le sous-processus Claude CLI avec flags configurables : nettoie d'abord l'env en supprimant les 5 variables `CLAUDE_CODE_*` héritées du daemon parent (évite que l'enfant réutilise une session parente expirée) ; streame les événements stream-json depuis stdout, parse chaque ligne via `parse_stream_event()`, écrit les lignes formatées dans le fichier log stdout. Exécution en mode abonnement uniquement (pas de retry fallback API). Timeout 3600s (CLAUDE_PROCESS_TIMEOUT_S) avec timer. |
| `parse_stream_event()` | stream_parser.py:8 | Parse une ligne stream-json de Claude CLI en log humain lisible, sans paramètre `session_cb` (mécanisme supprimé avec le fallback API). Transforme : `system/init` → log d'init, `assistant` → blocs texte + tool_use, `user` → tool_result, `result` → résumé + durée + coût. |
| `_update_billing_mode_in_mongo()` | runner.py:156 | Enregistre le mode de facturation (`"abonnement"` ou `"api"`) dans Mongo après chaque cycle (distinction primaire vs fallback API) |
| `tp_watcher_loop()` | core/tp_watcher.py:14 | Boucle principale du thread daemon TP watcher : exécute `_tp_watcher_tick()` toutes les 2 min en capturant les exceptions |
| `_tp_watcher_tick()` | core/tp_watcher.py:24 | Cœur de la surveillance TP : charge `trade_history.json`, itère sur positions ouvertes, compare prix courant vs `tp_price`, déclenche vente MARKET + annulation SL si TP atteint, met à jour position avec `exit_price`/`pnl_usdc`/`pnl_pct`/`close_reason="tp_watcher"` |
| Bloc Tâche 3 — Recalibrage TP _(cycle position)_ | prompts/position_prompt.txt | Exécuté par le sous-processus Claude dans le cycle `/calibrage` : pour chaque position ouverte, appelle MCP `mcp__tradingview__combined_analysis()` en 4h pour récupérer `resistance_2`, calcule `tp_smart = min(tp_mécanique, r2_4h × 0.98)`, met à jour `tp_price` si écart absolu > 0.5%, sauvegarde atomique via `_save_trade_history_atomic()`, notification Telegram si recalibrage ; gestion d'erreur silencieuse (continue au coin suivant si MCP échoue) |
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
| `/trade` | `run_trade_workflow(trigger="manual")` | Déclenche immédiatement un cycle complet d'analyse et de trading (9 phases, avec calibrage en Phase 0) dans un thread daemon |
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
| `trade_history.json` | JSON array | Source de vérité des trades : chaque entrée contient `trade_id`, `coin`, `side`, `signal_score`, `entry_price` (prix de fill réel), `stop_price`, `tp_price`, `quantity`, `risk_usdc`, `entry_order_id` (BUY MARKET), `sl_order_txid` (SELL STOP-LOSS Kraken), `protection_failed`, `status` (open/closed), `pnl_usdc`, `pnl_pct`, `close_reason`, dates |
| `agent_lock.json` | JSON object | Mutex de cycle : `{"running": bool, "started_at": ISO-UTC}` — expire automatiquement après 2h |
| `telegram_offset.json` | JSON object | Dernier `update_id + 1` des updates Telegram — permet de reprendre sans re-traiter les anciens messages après redémarrage |
| `pending_callback.json` | JSON object | Dernière réponse inline keyboard : `{"action": "CONFIRM"/"CANCEL", "timestamp": float}` — lu par le sous-processus Claude pour les confirmations |
| `pending_trades.json` | JSON array | Trades en attente de confirmation utilisateur (pré-exécution) |
| `webhook_pids.json` | JSON object | PIDs du processus webhook (usage legacy v1 / monitoring externe) |
| `daemon.log` | Log texte | Journal loguru du process principal (rotation à 10 MB, rétention 5 fichiers rotatifs) — premier fichier à consulter en cas d'anomalie |
| `cycle_log.jsonl` | JSONL | Historique append-only des cycles : une ligne JSON par cycle avec `date`, `cycle_id`, `top_score`, `executed`, `skipped`, `skip_type`, `skip_detail`, `portfolio`, `sentiment`, `open_positions` — rotation à 90 lignes max ; commité+pushé sur main après Phase 7 |

**Logs de cycle** (`logs/`) :

| Fichier | Type | Rôle |
|---|---|---|
| `logs/stdout/cycle_<id>.log` | Log brut | Sortie stdout du sous-processus Claude (stream-json) — toujours écrit, même en cas d'erreur |
| `logs/stderr/cycle_<id>.log` | Log brut | Sortie stderr du sous-processus Claude — toujours écrit, même en cas d'erreur |
| `logs/cycle_<id>_phases.jsonl` | JSONL | Heartbeats par phase : une ligne JSON par phase terminée (0–7), avec `ts`, `phase`, `status`, `duration_s`, `summary`, `trigger` (`"manual"`\|`"auto"`) — base pour le watchdog ticket #7, qui peut filtrer par type de cycle |

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
| `usdc_allocation_pct` | `0.70` | Fraction du USDC libre allouée au trading (70%) |
| `portfolio_coins` | `["XBT", "XRP", "SOL"]` | Coins systématiquement inclus dans l'univers de scan (coins Kraken avec paires USDC tradables : XBTUSDC, XRPUSDC, SOLUSDC) |
| `quote_asset` | `"USDC"` | Asset de cotation pour toutes les paires tradées |
| `min_volume_usdc` | `1000000` | Seuil volume 24h (USDC) pour inclure un coin dans l'univers Phase 1 — coins sous ce seuil ignorés sauf s'ils figurent dans `portfolio_coins` (fallback garanti). Baissé de 5M à 1M via PR #312 pour couvrir alt-coins de taille moyenne (SOL, XRP) |
| `order_type` | `"LIMIT"` | Type d'ordre d'entrée (ordre working de l'OTOCO) |
| `limit_offset_pct` | `0.005` | Décalage du prix limite par rapport au prix actuel (−0.5%) |
| `min_order_usdc` | `9` | Montant minimum d'un ordre en USDC (contrainte Binance) — abaissé de 11 à 9 via PR #268 pour couvrir dimensionnements ATR légitimes (8–11 USDC) |
| `max_single_position_pct` | `0.65` | Part maximale du budget allouable à une seule position (65%) |
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
| `min_profit_pct_take` | `5.0` | Seuil de profit (%) pour réaliser les gains via SELL MARKET en cycle position (NEW #241, augmentation #342) |
| `max_hold_days` | `14` | Durée maximale (jours) de détention d'une position en perte avant évaluation de cut-loss en cycle position (NEW #241) |

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
| [#361](pr-361-phase8-trade-history-git-add.md) | 2026-07-20 | [BUG] Phase 8 : staging explicite de `state/trade_history.json` — ajout `git add state/trade_history.json` dans le script bash généré par `phase8_cycle_log.py`, garantissant que les deux fichiers d'état (`cycle_log.jsonl` + `trade_history.json`) sont committés ensemble à chaque cycle, éliminant le drift silencieux |
| [#356](pr-356-fiabilite-cycles.md) | 2026-07-05 | [FIX] Fiabilité cycles — autostash push + détection quota stdout : ajout du flag `--autostash` à `git pull --rebase` dans Phase 8 pour éviter les conflits silencieux avec `state/trade_history.json` ; extension détection erreur quota en vérifiée aussi stdout via `is_resource_error(stdout_path)` pour capturer "You've hit your session limit" qui apparaît en stdout, pas stderr |
| [#353](pr-353-perf-kpis.md) | 2026-07-04 | [M349] Enrichir `/perf` avec KPIs P&L, cycles, positions et watcher : réorganisation en 4 blocs (P&L réalisé/7j/30j + win rate + top coins, Cycles + répartition TYPE_A/B/C/D + fallback Mongo/JSONL, Positions ouvertes/fermées/SL/TP/streak, TP Watcher totaux + ventes 24h/7j) ; nouvelles fonctions `_bloc_pnl()`, `_bloc_cycles()`, `_bloc_positions()`, `_bloc_watcher()`, `_load_cycles_jsonl()`, `_format_cycle_lines()` ; ajout `parse_dt()` de timing.py pour parsing ISO 8601 robuste ; format HTML Telegram |
| [#351](pr-351-ajouter-duration-error-type-mongo.md) | 2026-07-04 | [M347] Traçabilité cycles : nouvelle fonction `_update_perf_in_mongo()` persiste `duration_s` (entier, secondes) et `error_type` (null/"quota"/"crash") dans MongoDB après chaque cycle — classification automatique des erreurs par analyse stderr (rate limit/credit/quota/overloaded → "quota", sinon → "crash") ; débogue et optimise performance stratégie |
| [#350](pr-350-watcher-cumulative-counters.md) | 2026-07-04 | [M348] Compteurs cumulatifs TP Watcher : ajout `total_ticks` (incrément chaque tick, ~2 min) et `total_sales` (ventes TP réussies cumulées) dans `state/tp_watcher_state.json` ; persistence inter-redémarrages bot via lecture atomique en début de chaque tick ; gestion démarrage à froid (fichier absent/corrompu → compteurs initialisés 1/0) ; signature `_write_watcher_state()` étendue `sales_delta` param |
| [#346](pr-346-enrichir-status-tp-watcher.md) | 2026-07-04 | [M345] Enrichir `/status` avec les infos du TP Watcher : 3 nouvelles fonctions (`_parse_last_tick()`, `_tp_watcher_health()`, `_count_tp_watcher_sales_24h()`) + refonte `_format_watcher_section()` pour exposer 4 infos (santé OK/Lent/Inactif, dernier tick locale, positions surveillées, ventes TP 24h) ; gestion robuste si `tp_watcher_state.json` absent |
| [#344](pr-344-recalibrage-tp-phase0.md) | 2026-07-04 | [M343] Recalibrage TP automatique en Phase 0 : intègre `mcp__tradingview__combined_analysis()` 4h pour chaque position ouverte, calcule `tp_smart = min(tp_mécanique, R2 × 0.98)`, met à jour `tp_price` si écart > 0.5%, fallback silencieux si MCP échoue, notification Telegram par coin recalibré |
| [#342](pr-342-config-augmenter-min-profit-pct-5.md) | 2026-07-04 | [CONFIG] Augmenter `min_profit_pct_take` de 2% à 5% : supprime la clôture prématurée en Phase 0 ; seuil plus restrictif pour réaliser les profits cohérent avec la stratégie reward/risk (ratio 3:2 ATR stop) |
| [#340](pr-340-trailing-stop-no-tp-override.md) | 2026-07-04 | [FIX] Trailing stop ne modifie plus le TP (Phase 0) : supprime le recalcul `new_tp = max(cur_tp, price + trail_dist × 3)` qui écrasait le TP intelligent ; Phase 0 recentrée sur SL uniquement, TP maintenu exclusivement par Phase 4 + `/calibrage` |
| [#331](pr-331-calibrage-tp-recalibration.md) | 2026-07-04 | [FEAT] Recalibrage TP via résistances TradingView dans `/calibrage` : tâche 3 appelle MCP `combined_analysis()` 4h, calcule `tp_smart = min(tp_mécanique, r2_4h × 0.98)`, met à jour `tp_price` si écart > 0.5% ; renumérotation tâches 3→4, 4→5, 5→6 ; validation robustesse positions long (assertion `stop < entry`) ; test unitaire `reward_risk_ratio` default 2.0 |
| [#327](pr-327-tp-intelligent-base-sur-les-resistances.md) | 2026-07-04 | [M1] Phase 4 TP intelligent : remplace TP mécanique par un TP plafonné à la résistance TradingView la plus proche au-dessus du prix entry (`nearest_resistance × 0.98`) ; fallback vers TP mécanique si résistance indisponible (Phase 2 échoue ou aucune candidate > entry) ; notification Telegram affiche source TP : `(R X × 0.98)` ou `(mécanique)` |
| [#326](pr-326-phase2-combined-analysis.md) | 2026-07-04 | [M1] Phase 2 : migration `coin_analysis` 4h → `combined_analysis` 4h + extraction ADX (`adx_4h`, `adx_trend_4h`) + niveaux de résistance (`resistance_1_4h`, `resistance_2_4h`, `nearest_resistance_4h`, `distance_to_resistance_4h_pct`) ; fallback automatique sur `coin_analysis` si `combined_analysis` échoue (nouveaux champs = None) ; `resistance_1_1d = None` en attente migration 1D future |
| [#323](pr-323-enrichir-status-tp-watcher.md) | 2026-07-04 | [FEAT] Enrichir `/status` avec prix courant et état TP Watcher : nouvelles fonctions `_fetch_current_price()`, `_format_watcher_section()`, `_write_watcher_state()` + état persistant `state/tp_watcher_state.json` + affichage PnL%/distance TP par position |
| [#321](pr-321-ajouter-thread-watcher-tp-temps-reel.md) | 2026-07-03 | [FEAT] Thread daemon TP watcher : surveillance continu du take-profit toutes les 2 min, vente MARKET automatique dès TP atteint, coordination via lock avec cycle 4h, notification Telegram immédiate |
| [#317](pr-317-score-par-coin-phase-3.md) | 2026-07-03 | [FEAT] Afficher le score par coin dans le rapport Phase 3 : enrichit la notification Telegram Phase 3 avec le détail par coin (score /10, décision BUY/HOLD/SKIP/SELL, raisons) ; ajoute champ `scores_detail` en output JSON ; heartbeat Phase 3 inclut résumé des scores (max 300 chars) |
| [#312](pr-312-refactor-phase1-kraken-usdc.md) | 2026-07-03 | [M1] Refactorer Phase 1 : univers de candidats défini par les paires USDC réellement disponibles sur Kraken (`kraken pairs`) au lieu de TradingView/Binance; seuil volume baissé de 5M à 1M USDC (configurable `min_volume_usdc`); `portfolio_coins` inclus systématiquement même sous seuil (fallback garanti); appels ticker par batch de 10 paires; prompts Phase 1 et Phase 2 mis à jour pour cohérence |
| [#310](pr-310-mettre-a-jour-config-kraken.md) | 2026-07-03 | [M291] Mettre à jour `config.json` pour Kraken : suppression clé obsolète `binance_profile` (Kraken utilise credentials globaux via `kraken setup`, pas de profil par commande), migration `portfolio_coins` vers paires USDC disponibles sur Kraken (`["XBT", "XRP", "SOL"]` — remplace `["BTC", "STX", "SUI", "XRP", "SOL"]`), retrait STX et SUI dont STXUSDC/SUIUSDC introuvables sur Kraken, utilisation XBT (pas BTC) pour construction paire correcte XBTUSDC |
| [#305](pr-305-mettre-jour-prompts-api-reference-kraken.md) | 2026-07-03 | [M5] Mettre à jour prompts et api_reference pour Kraken : migration complète Binance CLI → Kraken CLI dans phases 0 (balance, SL verification, trailing stop), 1 (tradabilité USDC), 4 (sizing, filtres lot_decimals), position_prompt (open-orders, ticker, cancel par txid) ; api_reference.txt rédaction complète avec pièges Kraken (BTCUSDC→XBTUSDC, volume asset base, pas OCO natif) — débloque phases 0-4 pour kraken-cli |
| [#304](pr-304-ajouter-unittests-fonctions.md) | 2026-07-03 | [M0] Ajouter unittests pour fonctions utilitaires : 17 tests unitaires pour `_round_price()` et `_round_qty()` (arrondi déterministe, sans I/O) — validant comportement critique du dimensionnement ordres ; pas de dépendances externes ajoutées |
| [#303](pr-303-phase0-structured-logs.md) | 2026-07-03 | Ajouter logs structurés pour traçabilité Phase 0 : nouvelle fonction `log_phase0_event()` écrit chaque événement (protection_recovery_start, sl_retry_success, ts_update_success, etc.) en JSON dans `logs/phase0_events.jsonl` — brique pour audit et debugging des retries OCO + trailing stops |
| [#298](pr-298-kraken-json-parsing.md) | 2026-07-03 | [M4] Migrer parsing réponses JSON Binance → Kraken (phase0_profit) : remplace `executedQty`, `cummulativeQuoteQty` par `vol_exec`, `cost` via `order sell` + `query-orders <txid>`, ajoute `time.sleep(1)` pour stabilisation fill ; rétro-compatible (anciens trades Binance conservés) |
| [#296](pr-296-kraken-bracket-orders.md) | 2026-07-03 | [M3] Migrer OCO Binance → SL Kraken : supprime ordres OCO (TP+SL liés), remplace par BUY MARKET + SELL STOP-LOSS uniquement ; TP détecté cycliquement par `phase0_profit.py` ; schéma trade_history : supprime `order_list_id`, `stop_order_id`, `tp_order_id`, ajoute `sl_order_txid` ; rétro-compatible (trades Binance ignorés) |
| [#295](pr-295-kraken-market-filters.md) | 2026-07-03 | [M3] Adapter les filtres de marché Kraken : remplace appels `exchange-info` Binance par `pairs` Kraken dans phases 0 (OCO retry, trailing stop) et phase 4 (sizing) ; ajoute vérification `costmin` native Kraken ; ajuste quantités via `lot_decimals` dynamique |
| [#294](pr-294-adapter-cli-kraken.md) | 2026-07-03 | [M286] Adapter les appels CLI de **lecture** vers Kraken : ticker unifié (remplace deux appels Binance), balance et open-orders via `kraken-cli` dans `status.py`, phase0_snapshot, phase0_profit, phase1_scan ; logique d'annulation d'ordres adaptée au format Kraken `descr.pair` |
| [#293](pr-293-remplacer-binance-cli-par-kraken.md) | 2026-07-03 | [M285] Migration CLI : remplace `binance-cli` par `kraken-cli`, détection via `shutil.which("kraken")` avec fallback `~/.cargo/bin/kraken` (env.py:33), renommage variable interne `_BINANCE_CLI` → `_EXCHANGE_CLI`, substitution template `__KRAKEN_CLI_PATH__` dans TRADE_PROMPT et POSITION_PROMPT — architecturally isolated, pas d'impact logique |
| [#270](pr-270-refacto-externaliser-helpers-python-modules.md) | 2026-07-03 | [REFACTO] Externaliser helpers Python en modules (`core/trade_helpers.py`, `core/heartbeat.py`, `core/position_helpers.py`), découper `trade_prompt.txt` en 9 sous-fichiers (`prompts/shared/` + `prompts/phases/`), déplacer 12 scripts de phase vers `binance-bot/core/phases/` (package Python), implémenter `core/env.py:assemble_prompt()` pour assemblage dynamique, refactoriser `runner.py` via dataclass `WorkflowConfig` — élimine ~70% de duplication d'helpers, maintenabilité +++ |
| [#267](pr-267-fix-phase0-bugs.md) | 2026-06-28 | [M1] Phase 0 : comptage open_positions inclut protection_failed=True, retry OCO avec fallback SELL MARKET après max_oco_retry (défaut 3), standardisation close_reason (market_above_tp, profit_target_phase0, protection_exhausted) |
| [#263](pr-263-position-prompt-binance-cli-fix.md) | 2026-06-28 | [BUG #261] position_prompt.txt : corrections syntaxe binance-cli (`open-orders` → `get-open-orders`, `get-price` → `spot ticker-price`) et noms de champs trade_history.json (`status` minuscule, `coin`, `quantity`, `date`) |
| [#260](pr-260-refactor-phase0-calibrage.md) | 2026-06-23 | [M259] Refactoriser : supprimer cycle horaire position (scheduler 1h), intégrer calibrage directement en Phase 0 du cycle 4h — réalisation de profits pour positions P&L ≥ `min_profit_pct_take`, simplification architecture (un seul scheduler) |
| [#257](pr-257-position-oco-manuels.md) | 2026-06-22 | [M255] Étendre cycle position : fusion ordres bot + OCO manuels Binance via `binance-cli spot open-orders`, évaluation P&L manuel, annulation OCO au profit + SELL MARKET |
| [#241](pr-241-cycle-position-horaire.md) | 2026-06-22 | [M239] Cycle horaire de gestion des positions ouvertes : `next_1h_slot()` scheduler 1h (sautant les 4h slots), `POSITION_PROMPT` dédiée, refactor `_run_workflow_cycle()` commune, watchdog optionnel, post-processing séparé — réalise profits dès `min_profit_pct_take` (2%), évalue cut-loss > `max_hold_days` (14j) |
| [#235](pr-235-augmente-max-single-position.md) | 2026-06-15 | Configuration : augmente `max_single_position_pct` de 0.40 à 0.65 pour permettre des ordres au seuil minimum sur portefeuilles en drawdown |
| [#234](pr-234-fix-tradingview-mcp-tools-v2.md) | 2026-06-14 | MCP TradingView : remplace outils tradesdontlie inexistants par atilaahmettaner (top_gainers, volume_breakout_scanner, market_sentiment, coin_analysis) — Phase 1 screeners + Phase 2 multi-timeframe + Phase 3 scoring mis à jour |
| [#201](pr-201-enrichir-claude-md.md) | 2026-06-03 | Documentation : ajout section « Principes généraux de développement » (Think/Simplicity/Surgical) dans CLAUDE.md |
| Initial release | 2025-xx-xx | Architecture polling-only v1, scripts shell legacy |
| v2 — 790b83a | 2025-xx-xx | Ajout capture raisonnement : loguru + MongoDB + commande `/raisonnement` |
| v2 — 2bf48c0 | 2025-xx-xx | Mise à jour README et ajout CLAUDE.md (contraintes non négociables) |
| Spec initiale | 2026-05-21 | Génération initiale de SPEC.md via `binance-doc-tech` one-shot |
| [#166](pr-166-consolidation-145-146-147-148-149.md) | 2026-05-29 | [CONSOLIDATION] Atomic writes `trade_history.json` (state_manager.py) + dédup heartbeats JSONL + retry-backoff binance-cli + auto-détection BINANCE_CLI_PATH + doc binance-cli commands |
| [#130](pr-130-workflow-dispatch.md) | 2026-05-28 | CI/infra : migrer trigger GitHub Actions de `projects_v2_item` (orga only) vers `workflow_dispatch` pour support des comptes personnels |
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
| [#131](pr-131-post-review-auto-tag.md) | 2026-05-28 | Workflow post-review automation : nouveau `.github/workflows/claude-post-review.yml` avec job `fix-bloquants` (correction automatique issues review), job `create-recommendation-tickets` (tickétisation recommandations avec label `tech-lead-review`), step idempotent de création label avant usage |
| [#133](pr-133-test-workflow-binance-dev.md) | 2026-05-28 | Test de recette du workflow `binance-dev-auto` : validation du pipeline entier (issue → branche → commit → PR → changement statut ticket) via `workflow_dispatch` |
| [#134](pr-134-qualifier-les-except-generiques.md) | 2026-05-28 | Refactoring gestion d'erreurs : remplacement bare `except Exception` par types spécifiques (`OSError`, `json.JSONDecodeError`, `ValueError`) dans `core/lock.py`, `core/telegram.py`, `orchestration/runner.py` ; ajout journalisation des erreurs capturées |
| [#135](pr-135-add-trigger-heartbeat.md) | 2026-05-28 | Injection du champ `trigger` dans les logs JSONL (Phase 7) et le document MongoDB : valeur `"manual"` ou `"auto"` — permet au watchdog (#7) de filtrer et distinguer les cycles manuels vs auto pour logiques de gestion différenciées |
| [#140](pr-140-post-review-trigger-binance-dev-auto.md) | 2026-05-28 | CI/workflow automation : post-review déclenche automatiquement `binance-dev-auto` sur tickets [REC] créés (labels AUTO, tech-lead-review) ; scripts utilitaires `dispatch_rec_tickets.sh` et `label_rec_auto.sh` pour migration tickets historiques |
| [#141](pr-141-documenter-skip-types.md) | 2026-05-28 | Documentation : nouvelle section CLAUDE.md « Cycles de trading : skip_type et skip_detail » — classement des skips par type (TYPE_A/B/C/D), déclencheurs par phase, utilité pour le debug et l'optimisation stratégique |
| [#142](pr-142-clarify-date-format.md) | 2026-05-28 | Clarification CLAUDE.md : format date des heartbeat logs JSONL utilise `%Y-%m-%dT%H:%M:%SZ` **avec secondes** pour garantir l'unicité chronologique des 7 phases exécutées en <60s (sinon agrégation %H:%M serait insuffisante) |
| [#144](pr-144-verify-variable-definitions.md) | 2026-05-28 | TRADE_PROMPT : initialisation explicite des variables de synthèse + fallbacks en Phase 7 (top_score, executed, skipped, skip_type, skip_detail, sentiment, portfolio_total, open_positions) + clarification des points d'assignation par phase → prévention UnboundLocalError, meilleure traçabilité |
| [#122](pr-122-cycle-log-jsonl.md) | 2026-05-28 | Ajout Phase 8 : écriture `state/cycle_log.jsonl` (append-only) avec synthèse cycle (top_score, executed, skipped, skip_type, portfolio, sentiment) ; rotation à 90 lignes max ; commit+push automatique sur main après Phase 7 |
| [#187](pr-187-consolidate-helpers-security-recs.md) | 2026-05-30 | [CONSOLIDÉ] Helpers partagés par cycle via `tempfile.mkstemp()` (Bandit B108 résolu) + extraction `_write_helpers_file()` + `_send_start_notification()` + constante `CLAUDE_PROCESS_TIMEOUT_S` + ajout méthode `CycleLogger.warning()` + lint script `check_cycle_logger_methods.sh` |
| [#194](pr-194-phase-2-1d-rate-limit-handling.md) | 2026-05-31 | Phase 2 : délai de récupération 15s post-batch 4h + appels 1D séquentiels 5s + gestion silencieuse erreur 1D (rate limit TradingView) + seuil adaptatif Phase 3 |
| [#217](pr-217-consolidation-rec-auto.md) | 2026-06-13 | [CONSOLIDÉ] Ajout méthode `CycleLogger.debug()` + refactoring `open()` avec context manager + commentaires clarifiés (Bandit B603, Bandit B324, Mypy type guards) + logs MongoDB debug pour coût et mode facturation |
| [#219](pr-219-consolidation-auto.md) | 2026-06-13 | [CONSOLIDATION] Refonte architecture : séparation logique orchestration cycle dans `binance-bot/orchestration/runner.py` (modules core, storage, botlogging, commands, models) ; classe `runner.run_trade_workflow()` remplace la logique monolithique dans webhook_server.py ; helpers via tempfile sécurisé (Bandit B108) |
| [#231](pr-231-consolidation-rec-auto.md) | 2026-06-14 | [CONSOLIDATION MAJEURE] Refactoring complet v2 → modularisation (orchestration, commands, core, storage, botlogging, models) + extraction TRADE_PROMPT dans `prompts/trade_prompt.txt` + injection helpers via tempfile + création agents CI/CD (binance-dev, doc-tech, tech-lead-reviewer, ticket-manager) + workflows GitHub Actions (binance-dev-auto, claude-code-review, claude-doc-tech, claude-post-review) + intégration 14 skills Binance/Finance + documentation technique complète (PRs historiques) |
| [#238](pr-238-trade-prompt-disallow-skills.md) | 2026-06-22 | Disallow skill invocation en TRADE_PROMPT : bloc "RÈGLES D'EXÉCUTION CRITIQUES" placé au début du prompt interdisant explicitement tous les skills (start-agent, start-trading, Workflow, Agent, etc.) et clarifiiant que seuls Bash/Read/Write/Edit/Grep sont autorisés → prévient invocation involontaire de skill au lieu d'exécution des phases |
| [#256](pr-256-calibrage-command.md) | 2026-06-22 | feat: commande Telegram `/calibrage` pour déclencher manuellement le cycle de gestion des positions (ajout handler dispatcher + mise à jour message aide) |
| [#242](pr-242-rec-auto-workflow.md) | 2026-06-22 | Workflow [REC] automation : refactoring complet post-review CI/CD — job `create-rec-tickets` détecte 3 formats recommandations + crée issues avec étiquettes `<!-- pr_branch -->` / `<!-- pr_number -->`; `auto-dispatch-on-auto-label` extrait métadonnées du body issue ; `binance-dev-auto` accepte mode REC-AUTO (implémente sur branche existante, ferme issue après commit) → recommandations tech lead intégrées au workflow PR existant |
| [#268](pr-268-config-min-order-usdc.md) | 2026-06-29 | Configuration : abaissement de `min_order_usdc` de 11 à 9 USDC pour réduire les rejets TYPE_B dus aux dimensionnements ATR légitimes (8–11 USDC) — résout 4 skips/7j observés |
| [#265](pr-265-supprimer-vars-claude-code.md) | 2026-06-24 | Fix : supprime les 5 variables `CLAUDE_CODE_*` du sous-processus Claude (`_run_claude()`) — empêche la réutilisation d'une session parent expirée en nettoyant l'env avant le lancement du CLI enfant (issue #264) |
| [#323](pr-323-enrichir-status-tp-watcher.md) | 2026-07-04 | [FEAT] Enrichir `/status` avec prix courant et état TP Watcher : nouvelles fonctions `_fetch_current_price()`, `_format_watcher_section()`, `_write_watcher_state()` + état persistant `state/tp_watcher_state.json` + affichage PnL%/distance TP par position |
| [#316](pr-316-fix-phase5-nonetype-guard.md) | 2026-07-03 | [BUG] Fix phase5_execution.py crash `TypeError: 'NoneType' object is not subscriptable` quand `trade=null` (0 ordres exécutés en Phase 4) — ajout garde `if not trade:` + sortie propre `PHASE5_DONE\|executed=0\|skipped=0` + `sys.exit(0)` |
| [#302](pr-302-migrer-helpers-position.md) | 2026-07-03 | Refactoring : élimination de la duplication complète entre `trade_helpers.py` et `position_helpers.py` en faisant du second un ré-export symétrique du premier (réduction 89 → 16 lignes) — fonte unique `trade_helpers.py` pour `tg`, `binance`, `_load_config`, `_save_trade_history_atomic`, `_save_config_atomic` → gains maintenabilité ticket #274 |
