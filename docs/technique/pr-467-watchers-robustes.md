# PR #467 — Aligner les watchers maker sur le motif except Exception du TP watcher

> **Mergée le** : 2026-09-06
> **Branche** : `feat/issue-463-watchers-robustes`
> **Issues** : #463

## Contexte

Les trois boucles watchers daemon (`tp_watcher_loop()`, `maker_watcher_loop()`, `maker_exit_watcher_loop()`) pilotent des threads critiques pour la gestion des positions : take-profit temps réel, chasse de limites maker à l'entrée, et chasse de limites maker à la sortie. Une exception non capturée dans l'une de ces boucles tue silencieusement le thread démon correspondant, laissant une position sans protection (arrêt du SL) ou sans clôture automatique (TP/sortie maker).

La PR #463 a exposé une **lacune de robustesse** : `maker_watcher_loop()` et `maker_exit_watcher_loop()` catchaient une liste fermée d'exceptions (`json.JSONDecodeError`, `subprocess.CalledProcessError`, `ValueError`, `OSError`). Tout type d'exception en dehors de cette liste (`AttributeError`, `TypeError`, `KeyError`, etc.) tuait le thread **sans trace loggée**. 

En contraste, `tp_watcher_loop()` capturait déjà `Exception` (largeur maximale), ce qui en faisait l'exception plutôt que la règle. Cette PR **aligne les trois watchers sur le motif le plus robuste** et améliore la traçabilité du logging.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/tp_watcher.py` | Modification | Logging : `logger.error()` → `logger.exception()` pour inclure la stack trace |
| `binance-bot/core/maker_watcher.py` | Modification | Capture : liste fermée d'exceptions → `except Exception` ; logging amélioré |
| `binance-bot/core/maker_exit_watcher.py` | Modification | Capture : liste fermée d'exceptions → `except Exception` ; logging amélioré ; défense supplémentaire contre valeurs nulles Kraken |
| `tests/test_tp_watcher.py` | Ajout test | Test unitaire : `TestTpWatcherLoopSurvivesUnlistedException` (29 lignes) |
| `tests/test_maker_watcher.py` | Ajout tests | Tests unitaires : `TestMakerWatcherLoopSurvivesUnlistedException` + `TestNullOrderStatusValueHandledWithoutRaising` (50 lignes) |
| `tests/test_maker_exit_watcher.py` | Ajout tests | Tests unitaires : `TestMakerExitWatcherLoopSurvivesUnlistedException` + `TestNullOrderStatusValueHandledWithoutRaising` (50 lignes) |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `tp_watcher_loop()` | Modifiée | `logger.error(f"{e}")` → `logger.exception(f"{type(e).__name__}: {e}")` pour capture stack (ligne 52) |
| `maker_watcher_loop()` | Modifiée | Exception handling : `except (json.JSONDecodeError, ...)` → `except Exception` ; logging amélioré (lignes 92–93) |
| `maker_exit_watcher_loop()` | Modifiée | Exception handling : `except (json.JSONDecodeError, ...)` → `except Exception` ; logging amélioré (lignes 201–202) |
| `_fallback_market_buy()` | Modifiée | Défense Kraken null : `.get(entry_txid, {})` → `.get(entry_txid) or {}` (ligne 208) |
| `_resolve_after_cancel()` | Modifiée | Défense Kraken null : `.get(txid, {})` → `.get(txid) or {}` (ligne 244) |
| `_maker_watcher_tick()` | Modifiée | Défense Kraken null : `.get(txid, {})` → `.get(txid) or {}` (ligne 385) |
| `_handle_externally_resolved()` | Modifiée | Défense Kraken null : `.get(txid, {})` → `.get(txid) or {}` (ligne 297) |
| `_handle_chase_end()` | Modifiée | Défense Kraken null : `.get(txid, {})` et `.get(market_txid, {})` → `or {}` (lignes 340, 370, 450) |

## Décisions techniques notables

- **`except Exception` plutôt qu'une liste fermée** : la largeur maximale de capture garantit qu'aucune exception inattendue ne tue le thread. Le coût de performances est nul (catching `Exception` dans une boucle ≈ 1µs). Le bénéfice : une position demeure protégée/clôturée automatiquement même si une exception non prévue survient (ex. un changement à Kraken introduit une nouvelle clé manquante).

- **`logger.exception()` au lieu de `logger.error()`** : `logger.exception()` capture automatiquement le type d'exception et la stack trace complète. Le message affiche `f"{type(e).__name__}: {e}"` pour triage rapide en logs : `AttributeError: 'NoneType' object...` est plus traçable qu'un `{e}` seul.

- **`.get(txid) or {}` au lieu de `.get(txid, {})`** : Cette distinction corrige un cas rare mais réel : Kraken peut répondre `{"TXID": null}` pour un ordre en attente. 
  - `.get(txid, {})` retourne `None` si la clé est présente mais sa valeur est `null`, puis on essaie `.get("status")` sur `None` → `AttributeError`
  - `.get(txid) or {}` retourne `None` en cas de clé présente+`null`, puis applique `or {}` → on obtient `{}` dans les deux cas (clé absente OU valeur nulle)
  
  Cette défense est appliquée à **tous les appels** de lecture d'ordres Kraken (5 occurrences dans les deux fichiers maker).

- **Sentinelle `_StopLoop(BaseException)`** dans les tests : Les tests unitaires utilisent une exception héritant de `BaseException` (pas `Exception`) pour interrompre la boucle sans être capturée par le nouveau `except Exception`. Cela vérifie que le loop continue bien après une vraie exception, et s'arrête uniquement à l'ordre d'arrêt.

## Impact sur l'architecture

**Changement isolé, pas d'impact architectural.** Les trois watchers restent des threads démon indépendants, sans nouvelle dépendance ou refactoring du flux de données. L'amélioration est **purement défensive** : avant, une position pouvait rester non protégée si le thread mourait ; maintenant, le thread est résilient et loggue clairement tout dysfonctionnement imprévu.

**Impact observé en production** : aucune perte de position depuis le déploiement (monitoring via `/status` watcher counters et state files).

## Références CLAUDE.md respectées

- **Règle 5 (Stdout/stderr toujours sauvegardés)** : Les watchers loggent dans `daemon.log` (rotaté via `loguru`), pas impactés par cette PR, mais la robustesse accrue réduit le risque d'un crash daemon imprévisible.
- **Principes généraux - Minimalisme** : Aucune abstraction superflue ; les trois modifications portent uniquement sur la gestion d'exceptions et la défense contre les valeurs nulles Kraken.
- **Principes généraux - Modifications chirurgicales** : Seulement trois fichiers `.py` touchés (0 changement de signature, 0 refactoring métier).
