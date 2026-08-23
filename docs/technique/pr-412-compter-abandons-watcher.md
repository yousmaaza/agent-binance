# PR #412 — [M1] Compter les abandons du watcher maker

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-408-compteur-abandons`
> **Issues** : #408

## Contexte

La PR ajoute la persistance d'un compteur `total_abandoned` dans `state/maker_watcher_state.json`. Les ordres maker peuvent être abandonnés dans deux scénarios :
1. **Prix invalidé** : le prix a dévié au-delà de `price_deviation_max_pct` pendant la poursuite maker → annulation sans repli marché
2. **Annulation externe** : l'ordre est annulé/expiré hors de notre contrôle avec volume exécuté = 0 → pas de repli marché

Jusqu'à présent, ces abandons n'étaient comptabilisés nulle part. Cette PR les enregistre à côté de `total_fills` et `total_fallbacks` pour le diagnostic et la future UI (`/perf`).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/maker_watcher.py` | Modification | Ajout du paramètre `abandoned_delta` dans `_write_watcher_state()` et propagation à travers les trois handlers de résolution (`_handle_externally_canceled()`, `_handle_invalidated_price()`, `_handle_timeout_or_concession()`) |
| `tests/test_maker_watcher.py` | Ajout | 4 nouveaux tests couvrant l'incrémentation du compteur et la rétrocompatibilité de lecture |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_write_watcher_state()` | Modifiée | Signature enrichie : paramètre `abandoned_delta: int = 0` ajouté. Lit `prev.get("total_abandoned", 0)` pour rétrocompatibilité, puis accumule le compteur dans l'état persisté |
| `_handle_externally_canceled()` | Modifiée | Retourne un tuple `(bool, int, int, int)` au lieu de `(bool, int, int)`. Quatrième valeur = 1 si outcome == "abandoned" |
| `_handle_invalidated_price()` | Modifiée | Idem : retourne 4 valeurs, dernier = 1 si outcome == "abandoned" |
| `_handle_timeout_or_concession()` | Modifiée | Idem : toujours 4 valeurs, mais dernier est toujours 0 (car `allow_market_fallback=True` exclut l'abandon) |
| `_maker_watcher_tick()` | Modifiée | Ajoute `abandoned_delta = 0` et l'accumule depuis les trois handlers lors du traitement de chaque ordre |

## Décisions techniques notables

- **Rétrocompatibilité maximale** : au démarrage du bot, si `maker_watcher_state.json` n'existe pas ou manque le champ `total_abandoned`, `prev.get("total_abandoned", 0)` retourne 0. Le compteur part de zéro (comportement identique à `total_fills` et `total_fallbacks`). Aucune migration.
- **Pas d'affichage en Phase 0** : le ticket #408 était volontairement de scope XS (compteur seul). L'affichage de `total_abandoned` dans `/maker` ou `/perf` est reporté au ticket #396 qui rendra l'ensemble des KPIs maker.
- **Symétrie avec les autres deltas** : `fills_delta`, `fallbacks_delta`, `abandoned_delta` suivent exactement le même modèle de propagation à travers le tick (accumulation dans les handlers, agrégation dans `_write_watcher_state()`).
- **Abandons jamais en `trade_history.json`** : un ordre abandonné n'a jamais exécuté aucune quantité, donc ne crée pas d'entrée dans l'historique des trades. Le compteur incrémental est l'única source de vérité pour les abandons.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. Le flux de décision du watcher (arbre 1-6 du docstring) reste inchangé. Le compteur est une instrumentation supplémentaire, purement en lecture-écriture dans `state/maker_watcher_state.json`. Aucun nouveau composant external, aucune nouvelle dépendance.

## Références CLAUDE.md respectées

- **Minimalisme** : ajout strict du compteur, pas de refactor adjacent, pas de gestion d'erreur pour scénarios impossibles.
- **État persistant dans `state/`** : respect de la convention — fichier JSON, écriture atomique via `.tmp` + `os.replace()`.
- **Python 3.11 + venv** : import loguru, datetime, json, os, subprocess — dépendances existantes.
- **Pas de secret** : aucune clé API ni token manipulé, dépendance `.env` inchangée.

## Couverture de tests

4 nouveaux tests dans `test_maker_watcher.py` (classe `TestAbandonedOrderIncrementsPersistedCounter` et `TestWriteWatcherStateAbandonedCounter`) :
- Validation que le `abandoned_delta=1` remonte depuis `_handle_invalidated_price()` lors d'une déviation de prix
- Validation que le `abandoned_delta=1` remonte depuis `_handle_externally_canceled()` lors d'une annulation externe
- Rétrocompatibilité : vérification que la lecture d'un ancien fichier sans le champ défaut à 0
- Accumulation : vérification que `total_abandoned` s'accumule correctement sur plusieurs appels à `_write_watcher_state()`

Tous les 42 tests (existants + nouveaux) passent. ✅
