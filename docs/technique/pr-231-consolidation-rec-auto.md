# PR #231 — Consolidation [REC] AUTO

> **Mergée le** : 2026-06-14
> **Branche** : `feat/consolidate-rec-20260614_191332`
> **Issues** : #156, #172, #228
> **PRs consolidées** : #227, #226, #230

## Contexte

Cette PR regroupe 3 PRs [REC] (Recommended automatic consolidations) générées automatiquement. L'objectif principal est un **refactoring architectural majeur du système de trading** :
- Extraction du monolithe `webhook_server.py` en modules spécialisés (orchestration, logging, configuration, état, stockage)
- Création du nouveau orchestrateur `binance-bot/orchestration/runner.py` dédié au cycle de trading
- Externalization du **TRADE_PROMPT** dans `prompts/trade_prompt.txt` (fichier versionné séparément)
- Injection dynamique des helpers partagés via `tempfile.mkstemp()` plutôt que substitution statique
- Refactoring complet de l'infrastructure CI/CD, des agents développeurs, et des workflows GitHub

## Changements clés

### Fichiers modifiés dans le codebase applicatif

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Création | Nouveau module : orchestre le cycle de trading, streaming Claude, capture logs, mise à jour Mongo, gestion erreurs |
| `config.json` | Modification (±3/-1 lignes) | Ajout paramètres de configuration (allocation USDC, scoring, sizing, risk) |
| `prompts/trade_prompt.txt` | Création | Externalization du TRADE_PROMPT : 9 phases (0–8) d'analyse et d'exécution |
| `binance-bot/` (modules) | Création | Modularisation complète : `commands/`, `core/`, `models/`, `botlogging/`, `storage/`, `orchestration/` |
| `webhooks_server.py` | Refactor | Simplification : dispatch vers les handlers, appels à `run_trade_workflow()` |

### Infrastructure et tooling

| Domaine | Changements |
|---|---|
| **Agents développeurs** | Ajout 6 agents dans `.claude/agents/` : `binance-dev.md`, `binance-doc-fonc.md`, `binance-doc-tech.md`, `medium-articles-manager.md`, `tech-lead-reviewer.md`, `ticket-manager.md` |
| **Workflows GitHub** | Ajout 6 workflows CI/CD : `auto-dispatch-on-auto-label.yml`, `binance-dev-auto.yml`, `claude-code-review.yml`, `claude-doc-tech.yml`, `claude-post-review.yml`, `claude.yml` |
| **MCP et skills** | Intégration 14 skills Binance/Fiat/Meme/Trading : `binance`, `binance-agentic-wallet`, `binance-sports-ai-analyzer`, `binance-tokenized-securities-info`, `crypto-market-rank`, `fiat`, `meme-rush`, `onchain-pay-open-api`, `p2p`, `payment-assistant`, `query-*`, `square-post`, `trading-signal` |
| **Documentation** | Docs techniques (PRs historiques), docs fonctionnelles (commandes Telegram), docs Medium (articles) |
| **Visuals** | Diagrammes D2 + SVG (architecture, flux, phases, commandes, auto-scheduler, trade) |

### Nouvelles dépendances

- `pymongo>=4.6.0` — client MongoDB pour persistance cycles
- `loguru>=0.7.0` — logging structuré avec rotation
- `ruff`, `radon`, `bandit`, `mypy` — tooling dev/review

## Décisions techniques notables

1. **Extraction du TRADE_PROMPT dans un fichier versionné** (`prompts/trade_prompt.txt`)
   - Raison : faciliter la lecture/maintenance, versionner le prompt indépendamment du code
   - Comment appliqué : substitutions `__CYCLE_ID__`, `__HELPERS_PATH__`, `__PROJECT_DIR__` intégrées dans `runner.py:50-56`

2. **Injection dynamique des helpers via tempfile au lieu de substitution statique**
   - Raison : isoler les secrets (MONGODB_URI, TELEGRAM_TOKEN) dans un fichier temporaire avec permissions 0o600, jamais baked en dur
   - Comment appliqué : `_write_helpers_file()` (runner.py:116-227) génère le fichier, `exec(open(...).read())` dans chaque phase du TRADE_PROMPT

3. **Modularisation complète du codebase**
   - Raison : séparation des responsabilités (commands, core, orchestration, storage) → testabilité, maintenabilité
   - Modules : `binance-bot/{botlogging, commands, config, core, models, orchestration, storage}`

4. **Streaming Claude CLI avec parsing stream-json**
   - Raison : suivi en temps réel du cycle, visibilité des phases, détection rapide des erreurs
   - Implémentation : `parse_stream_event()` (stream_parser.py) + `WatchdogThread` (watchdog.py:10-60) qui alerte si blocage > 15 min

5. **Heartbeats par phase en JSONL avec dédup**
   - Raison : traçabilité fine des 9 phases, durée d'exécution, statut, base pour l'auto-détection de blocage
   - Implémentation : `hb(phase, status, summary)` dans les helpers, écrit dans `logs/cycle_<id>_phases.jsonl` avec remplacement en place

6. **Mode abonnement Claude uniquement (pas de fallback API)**
   - Raison : budget prévisible, coût stable via Claude Code CLI
   - Vérification : `ANTHROPIC_API_KEY` explicitement ignorée au boot (core/env.py:86)

## Impact sur l'architecture

### Avant (v1 monolithique)

```
webhook_server.py (800+ lignes)
├── _load_env()
├── dispatch_command()
├── handlers (status, perf, raisonnement, etc.)
├── run_trade_workflow()  ← brique principale mais imbriquée
├── subprocess claude (TRADE_PROMPT baked in)
└── tg_post(), locks, crypto utils
```

**Problème** : code volumineux, difficile à naviguer, prompt invisible, secrets à risque dans les globals.

### Après (v2 modulaire)

```
webhook_server.py (143 lignes → dispatcher uniquement)
├── import orchestration.runner
├── main_loop() → dispatch_command()
└── handle_* → run_trade_workflow(trigger, fmt_next_fn)

binance-bot/
├── orchestration/runner.py (338 lignes)
│   └── run_trade_workflow() → _run_claude() → subprocess
├── config/ (llm.py, app.py)
├── core/ (env.py, lock.py, telegram.py, timing.py, state_manager.py)
├── commands/ (eval.py, status.py, perf.py, raisonnement.py, cout.py)
├── storage/ (mongo.py)
├── botlogging/ (cycle_logger.py)
└── models/ (cycle.py, trade.py)

prompts/trade_prompt.txt (9 phases, 891 lignes)
```

**Bénéfice** : 
- **Clarté** : chaque module a une responsabilité unique
- **Testabilité** : aisé de mocker `mongo_repo`, `CycleLogger`, helpers
- **Sécurité** : secrets injectés dynamiquement via tempfile, jamais hardcodés
- **Maintenabilité** : prompt externalisé, versionable, commenté en détail

### Flux d'exécution inchangé

L'architecture polling-only demeure :
1. `main_loop()` poll Telegram en long-polling 30s
2. Au trigger (`/trade` ou slot 4h), appel `run_trade_workflow(trigger, fmt_next_fn)`
3. `runner.py:run_trade_workflow()` → `_write_helpers_file()` → `_run_claude()`
4. Claude exécute les 9 phases, stdout streamé vers logs, heartbeats en JSONL
5. Phase 7 : upsert MongoDB, notif Telegram finale
6. Phase 8 : cleanup, git push (dans le prompt)

## Références CLAUDE.md respectées

- ✅ **Règle 1** : Venv `.venv` Python 3.11 — utilisation cohérente dans les imports et la structure
- ✅ **Règle 2** : `PROJECT_DIR` dynamique — appliqué via `core/env.py:PROJECT_DIR` calculé dans `orchestration/runner.py:_write_helpers_file()` ligne 126
- ✅ **Règle 3** : Secrets via `.env` uniquement — `_write_helpers_file()` injecte `os.environ.get()` dans le fichier temporaire helpers, jamais substitués en dur
- ✅ **Règle 4** : Telegram via `curl` — helpers définissent `tg()` qui appelle curl, toujours utilisé dans le TRADE_PROMPT
- ✅ **Règle 5** : Capture stdout/stderr systématique — `runner.py:60-61` : `logs/stdout/cycle_{cycle_id}.log` et `logs/stderr/cycle_{cycle_id}.log` toujours écrits
- ✅ **Règle 6** : UTC interne, local à l'affichage — `_send_start_notification()` utilise `fmt_local()`, `_write_helpers_file()` injuste le helper sur timestamps ISO-UTC
- ✅ **Règle 7** : Auto-scheduler dans `main_loop()` — toujours en place dans `webhook_server.py:main_loop()`, pas de cron
- ✅ **Règle 9** : Commandes via Claude CLI (non-API) — vérification explicite à boot dans `config/llm.py:get_configured_model()`, utilisation exclusive de `CLAUDE_CLI_FLAGS` dans `runner.py:237`

## Fichiers supprimés

- `scripts/webhook_server.py` (ancien monolithe) → remplacé par `binance-bot/webhook_server.py` (dispatcher mince) + `orchestration/runner.py`
- Legacy shell scripts (`bot_daemon.sh`, `start_webhook.sh`, `run_trade.sh`) → remplacés par des commandes Python

## Prochaines étapes

1. **Démarrage du bot** : `python -m binance_bot.cli` ou nohup du webhook_server.py
2. **Test cycle complet** : `/trade` depuis Telegram → vérifier logs/stdout/cycle_*.log et MongoDB
3. **Monitoring** : checker `logs/cycle_<id>_phases.jsonl` pour voir progression des phases
4. **Debugging** : voir CLAUDE.md § "Debug d'un cycle qui plante" — les logs sont la source de vérité

