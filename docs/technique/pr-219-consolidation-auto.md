# PR #219 — Consolidation [REC] AUTO

> **Mergée le** : 2026-06-13
> **Branche** : `feat/consolidate-rec-20260613_091111`
> **Issues** : #138, #139
> **Consolide** : PR #206, PR #208

## Contexte

Cette PR est une consolidation automatique de deux PRs [REC] (Recommendation) générées par l'agent `binance-dev-auto`. Elle restructure l'architecture du bot de trading en séparant la logique d'orchestration des cycles dans un module Python dédié (`binance-bot/orchestration/`), améliorant ainsi la maintenabilité, la testabilité et la séparation des responsabilités.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Création | Nouveau module principal : orchestre les cycles complets de trading (lock → helpers → subprocess Claude → persistance → notifications) |

### Structure architecturale créée

La consolidation introduit une architecture multi-module pour `binance-bot/` :

| Module | Fichier | Rôle |
|---|---|---|
| **orchestration** | `runner.py` | Orchestration des cycles de trading (lancement, capture logs, erreurs, Mongo) |
| | `stream_parser.py` | Parsing des événements stream-json de Claude CLI en logs lisibles |
| | `watchdog.py` | Monitoring des phases en cours via les heartbeats JSONL |
| **core** | `env.py` | Chargement variables d'environnement et fichier `.env` |
| | `lock.py` | Gestion du mutex `agent_lock.json` (acquire/release) |
| | `telegram.py` | Appels bas niveau Telegram API via `curl` |
| | `timing.py` | Utilitaires horaires (format local, slots UTC) |
| | `state_manager.py` | Persistance atomique de `trade_history.json` |
| **storage** | `mongo.py` | Client MongoDB (lazy init, CRUD cycles) |
| **botlogging** | `cycle_logger.py` | Logger structuré pour les heartbeats JSONL (nouvelles méthodes `info()`, `error()`, `warning()`) |
| **models** | `cycle.py` | Schéma Cycle (TypedDict-like) |
| | `trade.py` | Schéma Trade (TypedDict-like) |
| **commands** | `status.py` | Handler `/status` |
| | `perf.py` | Handler `/perf` |
| | `raisonnement.py` | Handler `/raisonnement` |
| | `cout.py` | Handler `/cout` |
| | `eval.py` | Handler `/eval` (nouveau) |

### Fonctions clés créées / impactées

| Fonction | Action | Description |
|---|---|---|
| `run_trade_workflow(trigger, fmt_next_fn)` | Créée | Orchestre un cycle complet : acquire lock → génère helpers → lance subprocess Claude → capture logs stdout/stderr → extrait coût API → update Mongo (coût + mode facturation) → libère lock. Timeout 3600s (CLAUDE_PROCESS_TIMEOUT_S). |
| `_send_start_notification(cycle_id, trigger, started_at, fmt_next)` | Créée | Envoie notification Telegram de démarrage du cycle : affiche le modèle Claude utilisé (extrait depuis `CLAUDE_CLI_FLAGS`), le mode facturation (abonnement), l'heure locale du démarrage et du prochain cycle auto. Différencie cycles manuels (`🔧`) vs auto (`🤖`). |
| `_write_helpers_file(fd, helpers_path, cycle_id, trigger)` | Créée | Génère le fichier temporaire des helpers Python (8 helper functions + constantes) injectables dans TRADE_PROMPT : `tg()`, `binance()`, `hb()`, `_hb_start()`, `_save_trade_history_atomic()`, etc. Permissions 0o600 garanties par `tempfile.mkstemp()`. Secrets lus depuis `os.environ` au runtime (jamais substitués). |
| `_run_claude(prompt, stdout_path, stderr_path, cycle_log)` | Créée | Lance le subprocess Claude CLI avec flags configurables (`CLAUDE_CLI_FLAGS`) : stream stdout via `subprocess.Popen(..., stdout=PIPE, text=True)`, parse chaque ligne JSON via `parse_stream_event()`, écrit les logs formatés dans `stdout_path`. Timeout 3600s via `threading.Timer()`. |
| `_update_cost_in_mongo(cycle_id, stdout_path, cycle_log)` | Créée | Extrait le coût API Claude depuis le log stdout via regex (`cost=\$X.XX`) et met à jour le document Mongo `cycles` avec le champ `api_cost_usd`. Silencieux en cas d'erreur (log warning). |
| `_update_billing_mode_in_mongo(cycle_id, billing_mode, cycle_log)` | Créée | Enregistre le mode de facturation (`"abonnement"` ou `"api"`) dans Mongo après chaque cycle — permettant au `/eval` de ventiler les coûts par type. |
| `_handle_error(cycle_id, trigger, started_at, duration, stderr_path, stdout_path, cycle_log)` | Créée | Gère les erreurs de cycle : extrait les 400 premiers chars du stderr, envoie notification Telegram avec HTML formatting, fallback Mongo `status: "error"` avec timestamp, durée et explication générique. |

## Décisions techniques notables

- **Tempfile pour les helpers** : utilisation de `tempfile.mkstemp()` avec permissions 0o600 au lieu de hardcoder des fichiers dans `state/` ou `/tmp` → réduit la surface d'exposition secrets (Bandit B108), fichiers auto-nettoyés en `finally`
- **Secrets depuis os.environ au runtime** : les variables sensibles (`TELEGRAM_TOKEN`, `MONGODB_URI`) sont lues depuis `os.environ` lors de la génération du fichier helpers, jamais substitués d'avance → mitigation attaques sur le fichier si temporairement lu/loggé
- **Timeout threading** : `threading.Timer(CLAUDE_PROCESS_TIMEOUT_S)` au lieu de `subprocess.timeout` directement → permet le cancel propre du timer et la gestion du cleanup dans le bloc `finally`
- **Mode abonnement uniquement** : `ANTHROPIC_API_KEY` ne figure PAS dans les variables injectées → aucun fallback API, simplifie l'erreur handling et la facturation (champ `billing_mode: "abonnement"` uniquement)
- **Parsing stream-json découplé** : la fonction `parse_stream_event()` est dans `stream_parser.py` (séparation des responsabilités) → plus facile à tester, réutilisable ailleurs si besoin

## Impact sur l'architecture

**Avant (v1)** : logique monolithique dans `scripts/webhook_server.py` (~1500 lignes), difficult à naviguer et tester.

**Après (v2 refonte)** : architecture multi-module avec séparation claire :
- **Orchestration** : `runner.py` = cœur du trading, indépendant des handlers Telegram
- **Core infrastructure** : env, lock, telegram, timing, state = utilitaires partagés
- **Storage/Models** : mongo, cycle, trade = persistance et schémas
- **Commands** : status, perf, etc. = interface utilisateur
- **Logging** : cycle_logger, stream_parser, watchdog = observabilité

**Avantages** :
- Chaque module responsable d'une seule chose (SRP)
- Facilite les tests unitaires (mocking des dépendances externes)
- Améliore la maintenabilité : pour modifier le flow d'un cycle, tu regardes `runner.py` seulement
- Permet d'ajouter des phases ou des comportements sans modifier `webhook_server.py`

## Références CLAUDE.md respectées

- ✅ **Secrets via .env** (règle 3) : variables sensibles lues depuis `os.environ`, jamais hardcodées dans le code
- ✅ **Tempfile sécurisé** (Bandit B108) : utilisation de `tempfile.mkstemp()` au lieu de chemins prévisibles pour les helpers
- ✅ **Capture logs stdout/stderr** (règle 5) : toujours écrite même en cas d'erreur, via open files et `subprocess.Popen(..., stdout=PIPE, stderr=file)`
- ✅ **PROJECT_DIR dynamique** (règle 2) : injectée dans helpers via `sys.executable` et `os.path.dirname(os.path.abspath(__file__))`
- ✅ **Telegram via curl uniquement** (règle 4) : la fonction `tg()` des helpers utilise `subprocess.run(["curl", ...])`, jamais `urllib`
- ✅ **UTC interne** (règle 6) : tous les timestamps Mongo utilisent `datetime.now(timezone.utc)`, affichage local via `fmt_local()` côté notification
- ✅ **Auto-scheduler dans main_loop** (règle 7) : `run_trade_workflow()` est déclenché par `main_loop()` (via threading.Thread daemon), pas de cron
- ✅ **Python 3.11 venv** : module utilise uniquement stdlib + `pymongo`, `loguru` (listées dans `requirements.txt`)

## Notes

- Les PRs consolidées (#206, #208) contenaient les fragments de cette refonte — cette PR regroupe l'intégration complète
- La signature de `run_trade_workflow()` inclut `fmt_next_fn=None` optionnel pour permettre à `main_loop()` d'injecter l'heure du prochain cycle sans couplage fort
- Les helpers sont générés à chaque cycle (pas réutilisés) pour isolation + traçabilité (chaque cycle a un timestamp unique dans le nom du fichier temporaire)
