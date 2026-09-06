# PR #474 — Cycles en échec — persistance Mongo upsert

> **Mergée le** : 2026-09-06
> **Branche** : `feat/issue-452-cycles-echec-mongo`
> **Issues** : #452

## Contexte

Identifié dans #452 : sur un cycle de trading qui plante **avant la Phase 7** (qui crée le document MongoDB), les écritures Mongo effectuées ultérieurement par le post-processing (`_update_cost_in_mongo`, `_update_billing_mode_in_mongo`, `_update_perf_in_mongo`) échouaient silencieusement en utilisant `update_one` **sans `upsert=True`**. Résultat : **102 documents cycles** sur la production historique ont perdu leur `error_type` (« quota » ou « crash »), `api_cost_usd` et `duration_s`.

Le bug repose sur une confusion : avant cette PR, les 3 fonctions supposaient à tort que le document était déjà créé à ce stade (par la Phase 7) — ce qui n'était jamais le cas sur un cycle en échec.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Modification | Ajout `upsert=True` à 4 `update_one` Mongo ; ajout logging quand `matched_count == 0` |
| `binance-bot/commands/perf.py` | Modification | Support fallback `duration_seconds` → `duration_s` pour compatibilité avec les 102 documents historiques |
| `tests/test_perf_command_duration_fallback.py` | Nouvelle | Vérifier le fallback de lecture de durée (2 noms de champ) |
| `tests/test_runner_cycle_mongo_persistence.py` | Nouveau | Vérifier que `upsert=True` crée le document ; tester les 4 fonctions d'écriture |

### Fonctions modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `_update_cost_in_mongo()` | runner.py | Modifiée | `upsert=True` + log warning si `matched_count == 0` |
| `_update_billing_mode_in_mongo()` | runner.py | Modifiée | `upsert=True` + log warning si `matched_count == 0` |
| `_update_perf_in_mongo()` | runner.py | Modifiée | `upsert=True` + log warning si `matched_count == 0` |
| `_handle_error()` | runner.py | Modifiée | Unification nom champ : `duration_s` au lieu de `duration_seconds` (ligne 572) ; ajout `upsert=True` + log warning |
| `_bloc_cycles()` | perf.py | Modifiée | Projection Mongo lire les deux noms : `duration_s` + `duration_seconds` ; calcul durée moyenne avec fallback |

## Décisions techniques notables

- **`upsert=True` plutôt que créer le doc dans la Phase 7** : les écritures du post-processing (coût, billing, durée, erreur) doivent être résilientes. Elles peuvent intervenir avant que la Phase 7 ait terminé ou en parallèle sur le fichier stderr (race condition). `upsert=True` résout : créer le doc s'il n'existe pas, sinon le mettre à jour.

- **`duration_s` (nouveau champ) vs `duration_seconds` (ancien)** : unification future. Les 102 documents historiques gardent `duration_seconds` (non migré). La lecture dans `perf.py` implémente un fallback : `duration_s` si présent, sinon `duration_seconds`. Les écritures futures (à partir de cette PR) utiliseront `duration_s` pour uniformité avec `_update_perf_in_mongo()`.

- **Log warning quand `matched_count == 0`** : détecte silencieusement quand une écriture a créé le document via upsert plutôt que le mettre à jour. Utile pour le debug : si un cycle plante avant Phase 7, on verra `"Mongo cost update : aucun document existant pour YYYYMMDD_HHMMSS, créé via upsert"`.

- **Tests doubles : fake Mongo + mutation assert** : deux nouveaux fichiers test modélisent fidèlement la sémantique `update_one` (retour `matched_count`, `upsert`), permettant de tester les 102 cycles historiques (avec/sans document pré-existant).

## Impact sur l'architecture

**Changement isolé, pas d'impact sur l'architecture globale.** La sémantique du cycle reste identique : Phase 7 écrit le document complet (`status: "completed"`, `decisions`, `execution`). Le post-processing écrit des champs **supplémentaires** (`api_cost_usd`, `billing_mode`, `duration_s`, `error_type`) — avant, ces écritures étaient silencieusement perdues sur un cycle en échec.

Résultat : tous les cycles (y compris ceux en erreur) ont maintenant leurs métadonnées d'observabilité complètes en Mongo.

## Références CLAUDE.md respectées

- **Minimalisme** : seulement les appels Mongo modifiés, pas de refactoring des conteneurs ou des handlers. Les 4 fonctions restent disjointes (pas d'abstraction prématurée : un `upsert_helper()` ne serait pas justifié pour 4 call-sites simples).

- **État persistant** : ajout transparent des champs manquants en Mongo (section 4 SPEC.md). Pas de changement de structure de cycle — juste complétude des champs existants.

- **Déploiement : aucun breaking change** : la PR tourne immédiatement après merge, sans migration Mongo ni ajustement VPS.

---

## Test plan (validé)

- ✅ Un cycle qui plante avant Phase 7 conserve `error_type` (« quota » ou « crash »), son coût API et sa durée
- ✅ Un cycle réussi (Phase 7 complète) n'est pas régressé
- ✅ L'unification `duration_s` n'efface pas `duration_seconds` d'un document historique
- ✅ Une écriture qui ne matche aucun document laisse une trace (`cycle_log.warning`)
- ✅ `pytest` complet : 493 passed
- ✅ `ruff check` : 0 nouvelle erreur (36 préexistantes sur main, inchangées)
