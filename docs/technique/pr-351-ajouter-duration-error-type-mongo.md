# PR #351 — Ajouter duration_s et error_type dans les cycles Mongo

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-347-duration-error-type-mongo`
> **Issues** : #347

## Contexte

Amélioration de la traçabilité des cycles de trading en persistant deux métriques critiques dans MongoDB :
- **`duration_s`** (entier) : durée totale du cycle en secondes
- **`error_type`** (null | "quota" | "crash") : classification des erreurs pour le debugging

Ces champs permettent de distinguer les skips volontaires (stratégiques) des skips techniques (indisponibilité, quota) et d'analyser les performances réelles des cycles.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Ajout de 22 lignes | Nouvelle fonction `_update_perf_in_mongo` + logique de classification d'erreurs dans `_handle_trade_post_run` |
| `prompts/phases/phases6_8.txt` | Ajout de 7 lignes | Documentation dans Phase 7 expliquant l'injection post-cycle des deux champs |
| `state/cycle_log.jsonl` | Données | Deux entrées modifiées/ajoutées avec exemple de cycles |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_update_perf_in_mongo()` | Ajoutée | Persiste `duration_s` (int) et `error_type` (null/"quota"/"crash") dans la collection MongoDB `cycles` |
| `_handle_trade_post_run()` | Modifiée | Calcule `duration_s` et `error_type` après le cycle, puis appelle `_update_perf_in_mongo()` |

## Décisions techniques notables

- **Classification d'erreurs** : L'`error_type` détecte automatiquement les erreurs de quota (rate limit, credit balance, overloaded, etc.) en analysant le stderr. Tout autre exit code non-zéro → "crash".
- **Injection post-cycle** : Les vraies valeurs sont écrites **après** la fin du sous-processus Claude via `_update_perf_in_mongo()`. Le prompt Phase 7 initialise ces champs à `null` par sécurité, puis runner.py les corrige immédiatement.
- **Cohérence avec le pattern existant** : Même approche que `_update_cost_in_mongo()` et `_update_billing_mode_in_mongo()` (MongoDB update avec $set).

## Impact sur l'architecture

Changement isolé, **pas d'impact architectural** :
- La nouvelle fonction s'intègre au flow post-run existant `_handle_trade_post_run()`.
- Aucune modification du orchestration du cycle, des phases, ou des composants externes.
- Les deux champs enrichissent le document MongoDB `cycles` sans modifier la structure globale.

## Références CLAUDE.md respectées

- **Règle 4 (curl pour Telegram)** : Non applicable, pas de changement Telegram.
- **Règle 5 (logs stdout/stderr)** : Respectée — la classification d'erreurs lit `logs/stderr/cycle_{id}.log`, qui est toujours capturé.
- **Règle 6 (UTC interne)** : Respectée — `duration` est calculé en UTC via `datetime.now(timezone.utc)`.
- **État persistant MongoDB** : Nouvelle colonne bien documentée dans le prompt Phase 7.

