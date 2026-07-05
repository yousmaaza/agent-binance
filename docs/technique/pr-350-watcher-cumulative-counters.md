# PR #350 — Compteurs cumulatifs total_ticks et total_sales dans tp_watcher_state.json

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-348-watcher-cumulative-counters`
> **Issues** : #348

## Contexte

Le TP Watcher (thread daemon qui surveille les positions ouvertes et vend au take profit temps réel, toutes les 2 min) persistait son état dans `state/tp_watcher_state.json`, mais ne suivait pas les statistiques cumulatives sur la durée de vie du bot. Cette PR ajoute deux compteurs : `total_ticks` (nombre d'appels au watcher depuis le démarrage du bot) et `total_sales` (nombre de ventes TP réussies cumulées), pour la traçabilité et le debugging.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/tp_watcher.py` | Modification | Ajout persistance compteurs cumulatifs dans `_write_watcher_state()` et intégration dans la boucle `_tp_watcher_tick()` |
| `state/cycle_log.jsonl` | Mise à jour | Nettoyage de deux entrées de log obsolètes (suppressions uniquement, pas de fonction modifiée) |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_write_watcher_state(status, last_error, positions_checked, sales_delta=0)` | Modifiée | **Signature étendue** : paramètre `sales_delta` (défaut 0) ajouté. **Logique atomique** : lit les compteurs précédents depuis `state/tp_watcher_state.json` (si présent), incrémente `total_ticks` de 1, ajoute `sales_delta` à `total_sales`. En cas d'absence ou corruption du fichier état (démarrage à froid), initialise `total_ticks=1` et `total_sales=sales_delta`. Écrit l'état complet (incluant les deux compteurs) atomiquement via tempfile + `os.replace()`. |
| `_tp_watcher_tick()` | Modifiée | **Suivi `sales_delta`** : initialise `sales_delta = 0`, incrémente de 1 à chaque vente TP réussie (ligne 132, après `changed = True`). Passe `sales_delta` à l'appel `_write_watcher_state()` en fin de fonction (ligne 149). |

## Décisions techniques notables

- **Lecture au démarrage de chaque tick** : Les compteurs sont lus depuis le fichier d'état à chaque appel de `_write_watcher_state()`, pas cachés en mémoire. Cela assure la persistance même en cas de redémarrage du bot ou du thread daemon. Le coût I/O est négligeable (1 lecture + 1 écriture par tick, toutes les 2 min).

- **Gestion des démarrages à froid** : Via un bloc `try/except` sur la lecture du fichier. Si le fichier absent ou corrompu, les compteurs partent de zéro (sauf `total_sales` qui part de `sales_delta` si vente lors du premier tick, cas rarissime).

- **Incrémentation `total_ticks` systématique** : Elle se fait **toujours**, même si aucune position ouverte ou si vérification du lock échoue (la ligne `positions_checked = 0` n'empêche pas l'incrémentation de `total_ticks`). Cela reflète fidèlement la fréquence réelle d'exécution du watcher.

- **Paramètre `sales_delta` par défaut** : Accepte un entier (0 si aucune vente, 1+ si plusieurs ventes en un tick — théoriquement possible sur plusieurs positions). Défaut à 0 pour compatibilité rétroactive avec d'éventuels appels directs à `_write_watcher_state()` (il n'y en a actuellement qu'un seul : ligne 149).

## Impact sur l'architecture

Changement **isolé et addititif**. Le watcher continue de fonctionner identiquement pour les ventes TP. Les nouveaux champs dans le fichier état ne sont lus que par `/status` (commande Telegram) pour afficher la santé du watcher. Aucune modification des flux de données existants ou des composants externes.

La fonction `_format_watcher_section()` (commands/status.py:172) utilise déjà ces compteurs pour afficher les ventes TP 24h (via `_count_tp_watcher_sales_24h()`), mais n'accède pas directement aux champs `total_ticks` et `total_sales` du JSON — elle les utilise uniquement à titre informatif interne.

## Références CLAUDE.md respectées

- **Règle 5 (Stdout et stderr toujours sauvegardés)** : Aucune modification. Le watcher hérite de la capture des logs du cycle 4h via les logs structurés loguru.
- **Règle 6 (Convention horaire UTC interne)** : `last_tick` stocké en ISO 8601 UTC + Z, compatible avec les affichages via `fmt_local()`.
- **Règle 2 (PROJECT_DIR dynamique)** : `_WATCHER_STATE_PATH` utilise `PROJECT_DIR` sans chemins hardcodés Mac.
- **Minimalisme** : Modification minimale (14 lignes ajoutées, 2 supprimées dans tp_watcher.py). Zéro dépendance ajoutée.
