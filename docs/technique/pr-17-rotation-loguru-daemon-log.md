# PR #17 — [M1] Activer rotation loguru sur state/daemon.log (10 MB, retention 5)

> **Mergée le** : 2026-05-21
> **Branche** : `feat/issue-2-activer-rotation-loguru-daemon-log`
> **Issues** : #2

## Contexte

Sans rotation, `state/daemon.log` grossissait indéfiniment au fil des redémarrages et des cycles toutes les 4h. Le ticket #2 demandait d'activer la rotation loguru à 10 MB avec une rétention de 5 fichiers rotatifs (`.1` à `.5`), et d'uniformiser tous les `print()` du process principal sous loguru pour cohérence de format.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification (+24 lignes, -11 lignes) | Ajout du handler daemon.log avec rotation, suppression du handler stderr par défaut, remplacement de tous les `print()` par des appels loguru |

### Code ajouté (niveau module, avant `get_mongo()`)

```python
_DAEMON_LOG_ADDED = False
if not _DAEMON_LOG_ADDED:
    logger.remove(0)   # supprime le handler stderr par défaut
    logger.add(
        f"{PROJECT_DIR}/state/daemon.log",
        rotation="10 MB",
        retention=5,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    )
    _DAEMON_LOG_ADDED = True
```

### Fonctions ajoutées / modifiées

| Élément | Action | Description |
|---|---|---|
| `_DAEMON_LOG_ADDED` (flag module-level) | Ajouté | Guard idempotent : empêche l'ajout en double du handler `daemon.log` si le module est rechargé |
| `logger.remove(0)` (initialisation module) | Ajouté | Supprime le handler stderr par défaut de loguru (id=0) pour éviter la double écriture dans `daemon.log` via la redirection `nohup ... 2>&1` |
| Appels `print()` → `logger.info/warning/error()` | Modifié | ~11 occurrences remplacées pour uniformiser le format de log (`YYYY-MM-DD HH:mm:ss | LEVEL | message`) |

## Décisions techniques notables

- **`logger.remove(0)` plutôt qu'un `logger.remove()` global** : seul le handler stderr par défaut (id=0) est supprimé, le handler `bot_{date}.log` à rotation quotidienne (ajouté juste avant) est préservé intact — les deux coexistent sans conflit.
- **Flag `_DAEMON_LOG_ADDED` plutôt que `try/except`** : le guard booléen module-level est plus explicite et ne masque pas d'erreurs loguru sous-jacentes.
- **`retention=5` (entier) et non `"5 files"`** : loguru accepte un entier directement comme nombre de fichiers à conserver, plus lisible que la forme chaîne.
- **Rotation `"10 MB"` et non `"10 mb"`** : loguru est case-insensitive mais la convention du projet utilise la majuscule pour les unités de taille.

## Impact sur l'architecture

`state/daemon.log` passe d'un fichier à croissance illimitée (seule la rotation quotidienne du handler `bot_{date}.log` existait, mais pas pour le daemon.log) à un fichier borné à 10 MB × 5 = 50 MB maximum. Le format de log devient uniforme entre tous les messages du process principal. La commande de démarrage `nohup .venv/bin/python -u scripts/webhook_server.py >> state/daemon.log 2>&1 &` reste valide : le stdout/stderr du process nohup continue d'aller dans le même fichier, mais la double écriture loguru/nohup est désormais évitée par `logger.remove(0)`.

## Références CLAUDE.md respectées

- **Règle 3 (`PROJECT_DIR` dynamique)** : le chemin de `state/daemon.log` est construit via `f"{PROJECT_DIR}/state/daemon.log"` — pas de chemin Mac hardcodé.
- **Règle 4 (capture stdout/stderr toujours active)** : le handler daemon.log est un handler loguru supplémentaire ; la capture `logs/stdout/cycle_{cycle_id}.log` et `logs/stderr/cycle_{cycle_id}.log` du sous-processus Claude est inchangée.
