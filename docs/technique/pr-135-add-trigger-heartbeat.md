# PR #135 — Add trigger field to JSONL heartbeat logs

> **Mergée le** : 2026-05-28
> **Branche** : `feat/issue-31-ajouter-trigger-heartbeat`
> **Issue** : #31

## Contexte

Le système de watchdog (issue #7) a besoin de pouvoir distinguer les cycles manuels (`/trade`) des cycles automatiques (scheduler 4h) pour des logiques de gestion différentes. Cette PR injecte le type de trigger dans les logs JSONL des phases (`logs/cycle_<id>_phases.jsonl`) et dans le document MongoDB, permettant une corrélation et un filtrage granulaire par type de cycle.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Modification | Ajout du placeholder `__TRIGGER__` et variable `_trigger`, inclusion du champ `trigger` dans la fonction `hb()` |
| `binance-bot/orchestration/runner.py` | Modification | Substitution de `__TRIGGER__` lors de chaque cycle |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `hb()` (prompt) | Modifiée | Ajout du champ `"trigger": _trigger` à chaque ligne JSONL heartbeat |
| `_trigger` (variable prompt) | Ajoutée | Variable globale captant le type de trigger injouée : `"manual"` ou `"auto"` |
| `run_trade_workflow()` (runner.py) | Modifiée | Accepte le paramètre `trigger: str` et le substitue dans le prompt |

## Décisions techniques notables

- **Substitution de placeholder** : Le pattern `__TRIGGER__` est consistant avec les autres substitutions (`__PROJECT_DIR__`, `__CYCLE_ID__`, `__CHAT_ID__`) — centralisé dans `runner.py` qui gère toutes les injections de contexte.
- **Variable globale dans le prompt** : `_trigger` est stockée comme variable module au début du prompt (avant les phases), permettant à la fonction `hb()` de l'accéder sans parameter passing.
- **Inclusion JSONL et MongoDB** : Le champ est inclus dans (1) chaque ligne JSONL pour le watchdog et (2) le document MongoDB Phase 7 (dans le champ `trigger` du doc complet) pour la persistance.

## Impact sur l'architecture

- **Flux de données** : Aucun changement dans le flux principal, simple ajout d'un champ traçabilité.
- **Contrats API** : Le format JSONL `logs/cycle_<id>_phases.jsonl` inclut désormais un champ `trigger` à chaque ligne.
- **Persistance MongoDB** : La collection `cycles` inclut un champ `trigger` au niveau du document racine.
- **Watchdog (#7)** : Peut maintenant filtrer les logs par `trigger` pour appliquer des logiques différentes (alertes, retry patterns) selon que le cycle est manuel ou auto.

## Références CLAUDE.md respectées

- **Règle 1** (Telegram via curl) : Aucun changement affecté ✓
- **Règle 2** (secrets via .env) : Aucune nouvelle dépendance externe ✓
- **Règle 3** (PROJECT_DIR dynamique) : Substitution centralisée dans runner.py ✓
- **Règle 4** (capture stdout/stderr) : Aucun changement affecté ✓
- **Règle 5** (UTC interne) : Aucun changement affecté ✓
- **Règle 6** (auto-scheduler dans main_loop) : Aucun changement affecté ✓
- **Règle 8** (workflow binance-dev) : Implémentation via PR ✓
