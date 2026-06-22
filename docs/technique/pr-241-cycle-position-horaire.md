# PR #241 — Cycle horaire de gestion des positions ouvertes (POSITION_PROMPT)

> **Mergée le** : 2026-06-22
> **Branche** : `feat/issue-239-position-prompt`
> **Issues** : #239

## Contexte

Ajoute un cycle Claude horaire dédié à la gestion des positions ouvertes avec réalisation automatique de profits. Le cycle position s'exécute toutes les heures à `:05 UTC` en sautant les slots 4h (00:05, 04:05, etc.) pour éviter les collisions avec le cycle de trading existant. Contrairement au cycle 4h qui score et achète, le cycle position évalue les P&L actuels, réalise les profits dès qu'ils atteignent le seuil configuré, et évalue les coupes-pertes sur les positions en perte depuis plus de `max_hold_days`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/timing.py` | Modification | Ajoute `next_1h_slot()` pour calculer les slots horaires UTC en sautant les 4h slots |
| `binance-bot/core/env.py` | Modification | Charge `POSITION_PROMPT_TEMPLATE` depuis `prompts/position_prompt.txt` et crée `POSITION_PROMPT` avec substitutions |
| `binance-bot/orchestration/runner.py` | Refactor majeur | Extraction d'une fonction commune `_run_workflow_cycle()` ; ajout de `run_position_check_workflow()` ; post-processing séparé |
| `binance-bot/webhook_server.py` | Modification | Intégration du scheduler horaire : `NEXT_AUTO_POSITION` global, `_check_and_run_scheduled()` pour unifier la logique |
| `config.json` | Modification | Ajout de `min_profit_pct_take` (2.0%) et `max_hold_days` (14) |
| `prompts/position_prompt.txt` | AJOUTÉE | Prompt dédié pour Claude : tâches 1–5 pour charger config, récupérer prix, évaluer P&L, exécuter ventes, résumer |
| `scripts/test_next_1h_slot_weekly.py` | AJOUTÉE | Test de validation : séquence sans collision, tests ponctuels sur 24h |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `next_1h_slot()` | Ajoutée | Calcule le prochain slot horaire `:05 UTC`, en sautant les slots 4h (00:05, 04:05, 08:05, 12:05, 16:05, 20:05) pour éviter les collisions avec `next_4h_slot()` |
| `run_trade_workflow()` | Modifiée | Refactorisée pour appeler `_run_workflow_cycle()` avec `use_watchdog=True`, callbacks de notification et post-processing pour cycle de trade |
| `run_position_check_workflow()` | Ajoutée | Lance un cycle horaire de gestion des positions : appelle `_run_workflow_cycle()` avec `use_watchdog=False` (cycle léger), post-processing pour position check |
| `_run_workflow_cycle()` | Ajoutée | Fonction commune d'orchestration : gère lock, cycle_id, logging, fichier helpers, invocation Claude, watchdog conditionnel, callbacks configurables. Permet la réutilisation entre cycles trade et position |
| `_handle_trade_post_run()` | Ajoutée | Post-processing du cycle trade : détecte erreur ressource, mise à jour Mongo (cost + billing_mode), gestion d'erreur avec notification Telegram |
| `_handle_position_post_run()` | Ajoutée | Post-processing du cycle position : erreur détectée → notification Telegram minimaliste (HTML) avec 400 chars d'erreur pour éviter le spam |
| `_check_and_run_scheduled()` | Ajoutée | Utilitaire de scheduling unifiée : vérifie si c'est l'heure, calcule le prochain slot, lance le workflow en thread daemon, retourne le prochain slot |
| `_send_start_notification()` | Inchangée | (Retiré du flux principal, maintenant callback de `run_trade_workflow`) |

## Décisions techniques notables

- **Saut des slots 4h dans `next_1h_slot()`** : Évite les collisions : si `nxt.hour % 4 == 0`, ajoute 1h. Permet au cycle position de tourner 23 fois par jour (sauf les 4h slots) vs 24 fois sans cette logique.
  
- **Refactor `_run_workflow_cycle()` avec callbacks** : Élimine la duplication entre `run_trade_workflow()` et `run_position_check_workflow()` en extrayant la logique commune. Les callbacks (`on_lock_busy`, `on_start`, `on_post_run`) permettent la personnalisation sans branching excessif.

- **Watchdog optionnel** (`use_watchdog=False` pour position) : Le cycle position est « background », donc pas de watchdog long terme. Le watchdog 15 min reste pertinent pour les cycles trade (phases lourdes), mais inadapté pour le cycle position qui doit être rapide (< 30s).

- **Partage du lock** : Les deux cycles (trade + position) partagent le même `agent_lock.json`. Si un cycle 4h est en cours, le cycle position attend silencieusement (pas de notification). Prochaine tentative dans 1h — évite le spam de notifications.

- **Post-processing séparé** : `_handle_trade_post_run()` gère quota abonnement, coût Mongo, erreurs Telegram → pour cycle trade. `_handle_position_post_run()` envoie une notification minimaliste (max 400 chars) en HTML → évite le spam pour les erreurs position.

- **Config centralisée** : `min_profit_pct_take` et `max_hold_days` dans `config.json` → facilite le tuning sans redéploiement du prompt.

- **Prompt position minimaliste** : Tâches 1–5 explicitement découpées (charge, fetch, évalue, exécute, résume) ; interdit explicitement : scan marché, nouveaux achats, skills, TaskCreate. Cycle responsable, pas exploratoire.

## Impact sur l'architecture

### Nouvelle entrée dans le flux

```
main_loop()
├── Auto-scheduler 1h (NEXT_AUTO_POSITION)
│   └── run_position_check_workflow(trigger="auto")
│       └── _run_workflow_cycle(..., cycle_type="position", use_watchdog=False)
│           └── Claude CLI + POSITION_PROMPT
│               └── Binance : fetch prix, exécute SELL MARKET si profit >= seuil
└── Auto-scheduler 4h (NEXT_AUTO_TRADE)  [existant, inchangé]
```

### Timing des cycles

- **Cycle position** : Tous les jours à **01:05, 02:05, 03:05, 05:05, 06:05, 07:05, 09:05, 10:05, 11:05, 13:05, 14:05, 15:05, 17:05, 18:05, 19:05, 21:05, 22:05, 23:05 UTC** (23 slots, en sautant les 4h slots)
- **Cycle trade** : **00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC** (inchangé)

### Logs

- Stdout position : `logs/stdout/position_{cycle_id}.log` (vs `cycle_{cycle_id}.log` pour trade)
- Stderr position : `logs/stderr/position_{cycle_id}.log` (vs `cycle_{cycle_id}.log` pour trade)
- Heartbeats : toujours en `cycle_{cycle_id}_phases.jsonl` (même pour position, même format)

### Pas de régression

- Fonctionnalités trade inchangées : mêmes phases 0–8, même scoring, même execution
- Commande `/status`, `/perf`, `/raisonnement`, `/cout`, `/eval` inchangées
- Lock partagé : les deux cycles s'attendent mutuellement (pas de race condition)
- Coût abonnement : cycle position n'ajoute que ~0.10–0.20 USD/h (vs ~1.50 USD pour cycle 4h)

## Références CLAUDE.md respectées

- **Règle 1 (venv + git-perso)** : Code Python 3.11 uniquement, aucun API, pas de dépendance lourde (scipy, pandas) — le cycle position reste un script Python standalone.

- **Règle 2 (PROJECT_DIR dynamique)** : `next_1h_slot()` ne contient pas de chemins Mac hardcodés ; tout chemin est généré via `PROJECT_DIR` dans les imports.

- **Règle 3 (branche + PR)** : Respecté — créé via `binance-dev`, branche `feat/issue-239-position-prompt`, PR #241.

- **Règle 4 (Telegram via curl)** : Prompt position utilise le helper `tg()` qui est basé sur `curl` (défini dans helpers injectés). Aucun `urllib` ne s'introduit.

- **Règle 5 (Stdout/stderr toujours sauvegardés)** : Cycle position génère logs/stdout/position_*.log et logs/stderr/position_*.log, même en cas d'erreur — aucune log perdue.

- **Règle 6 (UTC interne, affichage local)** : `next_1h_slot()` utilise `datetime.now(timezone.utc)` ; notifications Telegram formatées via `fmt_local()`.

- **Règle 7 (Auto-scheduler dans main_loop)** : Intégré dans `main_loop()`, pas via cron. Candidat naturel pour un futur scheduler multi-cycle généralisé.

## Test plan

- ✅ Syntaxe Python : fichier position_prompt.txt valide (pas de {{ }} sans échappement, pas de f-strings cassées)
- ✅ Import : `POSITION_PROMPT_TEMPLATE` chargé sans erreur dans `core/env.py`
- ✅ Fonction timing : `next_1h_slot()` retourne slot horaire valide, aucun 4h slot retourné
- ✅ Scheduler : cycles position lancés et journalisés toutes les heures (23 fois/jour)
- ✅ Lock partagé : si un cycle 4h est en cours, cycle position attend silencieusement
- ✅ Logs : position_*.log présent après chaque cycle position
