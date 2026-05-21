# PR #28 — [REC] Supprimer le double handler loguru sur state/daemon.log

> **Mergée le** : 2026-05-21
> **Branche** : `feat/issue-18-supprimer-double-handler-loguru-daemon`
> **Issues** : #18

## Contexte

La PR #17 avait activé la rotation loguru sur `state/daemon.log` et ajouté `logger.remove(0)` pour supprimer le handler stderr par défaut. Cependant, ce `logger.remove(0)` était placé à l'intérieur du bloc `if not _DAEMON_LOG_ADDED:`, qui s'exécutait *après* un premier `logger.add()` (le handler `bot_{date}.log` quotidien). Résultat : le handler stderr (id=0) restait actif lors des premières écritures loguru — notamment le `logger.warning()` ligne 44 pour l'absence de `TELEGRAM_TOKEN` — et écrivait dans `daemon.log` via la redirection `nohup ... 2>&1`, produisant toujours des lignes dupliquées.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification (+1 ligne, -11 lignes) | `logger.remove(0)` déplacé au niveau module juste après l'import loguru ; guard `_DAEMON_LOG_ADDED` supprimé |

### Fonctions ajoutées / modifiées

| Élément | Action | Description |
|---|---|---|
| `logger.remove(0)` (ligne :23, niveau module) | Déplacé | Était dans `if not _DAEMON_LOG_ADDED:` (après le premier `logger.add()`) ; maintenant juste après `from loguru import logger`, avant tout appel `logger.*` |
| `_DAEMON_LOG_ADDED` (flag module-level) | Supprimé | Devenu inutile : la suppression du handler stderr au bon moment (avant tout `logger.add()`) rend le guard idempotent caduc |
| `if not _DAEMON_LOG_ADDED: ... _DAEMON_LOG_ADDED = True` (bloc module) | Supprimé | Le handler `daemon.log` est désormais ajouté directement (sans guard) puisque `logger.remove(0)` garantit l'état propre avant tout ajout |

## Décisions techniques notables

- **Placement de `logger.remove(0)` à l'import** : déplacer le `remove` immédiatement après `from loguru import logger` (ligne :23) garantit qu'aucun handler stderr ne peut écrire, quelle que soit l'ordre des `logger.add()` qui suivent. C'est la solution la plus robuste : elle ne dépend pas de l'ordre des blocs d'initialisation module.
- **Suppression du guard `_DAEMON_LOG_ADDED`** : le guard avait deux rôles — supprimer stderr et éviter le double-ajout de daemon.log. Une fois `logger.remove(0)` déplacé en tête, le guard n'a plus de raison d'être. Le `logger.add()` de `daemon.log` s'exécute une seule fois au chargement du module, ce qui suffit.
- **Pas de modification du handler daemon.log lui-même** : rotation 10 MB, rétention 5 fichiers, format et level inchangés — seul le positionnement du `remove` change.

## Impact sur l'architecture

Changement isolé d'initialisation du système de logging. Le comportement observable est identique à ce qui était *attendu* après la PR #17 : aucune ligne dupliquée dans `state/daemon.log`. L'ordre d'initialisation module est désormais :
1. `logger.remove(0)` → supprime le handler stderr par défaut
2. `_load_env()` + variables globales
3. `logger.add(bot_{date}.log)` → handler quotidien
4. `logger.add(state/daemon.log)` → handler avec rotation 10 MB

Aucun impact sur les autres composants (Telegram, Binance CLI, MongoDB, sous-processus Claude).

## Références CLAUDE.md respectées

- **Règle 3 (`PROJECT_DIR` dynamique)** : le chemin de `state/daemon.log` reste construit via `f"{PROJECT_DIR}/state/daemon.log"` — inchangé.
- **Règle 4 (capture stdout/stderr toujours active)** : la capture `logs/stdout/cycle_{cycle_id}.log` et `logs/stderr/cycle_{cycle_id}.log` du sous-processus Claude est strictement inchangée par ce fix.
