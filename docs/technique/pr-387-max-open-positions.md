# PR #387 — Corriger l'enforcement de max_open_positions en Phase 3

> **Mergée le** : 2026-08-22
> **Branche** : `feat/issue-384-max-open-positions-enforcement`
> **Issues** : #384

## Contexte

Cycle incidentiel **20260821_040505** : le bot a accepté 4 coins en `buy_candidates` simultanément alors que `max_open_positions=4` et que 1 position était déjà ouverte — le max aurait dû limiter à 3 nouveaux coins (1 + 3 = 4 total).

**Root cause** : en Phase 3 (scoring), la variable `open_positions` était lue une seule fois depuis le snapshot Phase 0 (ligne 40) et jamais mise à jour. Au fur et à mesure que des coins passaient la sélection stratégique, `buy_candidates` croissait, mais le check `elif open_positions >= max_open_positions:` (ligne 111 AVANT la fix) comparait toujours la valeur statique initiale. Résultat : plusieurs coins pouvaient être acceptés simultanément au-delà du seuil configuré.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase3_scoring.py` | Modification | Enforcement de `max_open_positions` désormais dynamique dans la boucle |
| `tests/test_phase3_scoring.py` | Ajout | Test de régression `test_candidates_accepted_this_cycle_count_toward_max` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| (phase3_scoring.py — script top-level, pas de fonctions) | Modifiée | Ligne 111 : comparaison change de `open_positions >= max_open_positions` à `open_positions + len(buy_candidates) >= max_open_positions` |
| (phase3_scoring.py — ligne 112) | Modifiée | `skip_detail_str` recalcule le compte affichant `open_positions + len(buy_candidates)` au lieu de `open_positions` seul |

## Décisions techniques notables

- **Recalcul dynamique plutôt que variable incrementée** : à chaque itération de la boucle, `len(buy_candidates)` est recalculé pour refléter les coins acceptés dans le **même cycle**. Cette approche est simple et déterministe, sans état mutable additionnel.
- **skip_detail synchronisé** : le message de skip reflète maintenant le compte réel (`open_positions + len(buy_candidates)`) pour que le report Telegram soit cohérent avec le motif du skip (utile pour le debug).
- **Pas de modification de config.json** : le ticket #384 proposait aussi un changement de `risk_per_trade_pct` et `min_signal_score_degraded`, explicitement hors scope de cette PR — pas de changement de config.

## Impact sur l'architecture

**Changement isolé sur la logique Phase 3.** Aucun impact architectural global — les vecteurs d'entrée/sortie de Phase 3 restent identiques (`phase3_input.json` → `phase3_output.json`). Le format des messages Telegram et des logs MongoDB n'est pas affecté (seul le contenu du `skip_detail` pour TYPE_A est enrichi de la valeur recalculée).

Incidents futurs similaires sur les positions `max_*` seraient détectés par le test de régression `test_candidates_accepted_this_cycle_count_toward_max`.

## Références CLAUDE.md respectées

- **Règle 2 — Modifications chirurgicales** : seules les 2 lignes nécessaires (check + skip_detail) ont été modifiées, pas de refactoring adjacent.
- **Pas de gestion d'erreur pour scénarios impossibles** : on ne valide pas si `max_open_positions` est bien > 0, car c'est garanti par la config (cf. `config.json` ou `DEFAULT_CONFIG` des tests).
- **Test de régression complet** : le test `test_candidates_accepted_this_cycle_count_toward_max` couvre exactement l'incident et vérifie que le compte des positions est bien appliqué dans la boucle.

## Vérifications du merge

- ✅ Syntaxe Python Phase 3 + tests valides
- ✅ `python -m unittest tests.test_phase3_scoring::TestMaxOpenPositions::test_candidates_accepted_this_cycle_count_toward_max -v` → PASS
- ✅ 12/12 tests de la suite Phase 3 → PASS
- ✅ Aucune régression sur les autres logiques (scoring, seuils, corrélation)
