# PR #144 — Vérifier la définition des variables Phase 3/5/6 en trade_prompt

> **Mergée le** : 2026-05-28
> **Branche** : `feat/issue-125-verify-variable-definitions`
> **Issues** : #125

## Contexte

Le prompt `prompts/trade_prompt.txt` utilise des variables de synthèse (`top_score`, `executed`, `skipped`, `skip_type`, `skip_detail`) qui sont censées être définies et mises à jour par les différentes phases (3, 5, 6, 7). Cependant, l'initialisation et le tracking de ces variables n'était pas explicite, risquant des `UnboundLocalError` en Phase 7 (persistance MongoDB) ou Phase 8 (JSONL) si une phase précédente échouait partiellement ou était ignorée.

Cette PR ajoute :
- **Initialisation explicite** au démarrage du prompt (valeurs par défaut)
- **Assignation claire dans chaque phase** (quand et où la variable est mise à jour)
- **Fallbacks en Phase 7** pour éviter les erreurs de variable non définie

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Modification | Ajout initialisation + instructions de tracking par phase |

### Structure des modifications

**1. Bloc d'initialisation (après les helpers `tg()` et `hb()`)**

```python
# Initialisation des variables de synthèse (utilisées par Phase 8)
top_score = 0
executed = 0
skipped = 0
skip_type = None
skip_detail = None
sentiment = "Neutral"
portfolio_total = 0.0
open_positions = 0
```

Ces fallbacks garantissent qu'aucune variable ne reste non définie, même si une phase échoue.

**2. Phase 3 — Scoring et sélection**

Ajout de paragraphes explicites clarifiant :
- **Quand assignner** `top_score` : après le calcul du score maximum parmi tous les coins
- **Quand assigner** `skipped` : nombre de coins rejetés par les filtres (corrélation, budget, etc.)
- **Quand assigner** `skip_type` et `skip_detail` : classification du skip principal (TYPE_A/B/C/D)
  - TYPE_A : filtre stratégique (score insuffisant, max positions atteintes, corrélation excessive)
  - TYPE_B : contrainte de dimensionnement (montant trop petit, prix invalide)
  - TYPE_C : conditions de marché dégradées (drift prix, solde insuffisant, fill partiel)
  - TYPE_D : indisponibilité (paire USDC inexistante, volume insuffisant)

**3. Phase 5 — Exécution automatique**

Ajout d'instructions pour mettre à jour :
- **`executed`** : nombre d'ordres BUY MARKET effectivement passés
- **`skipped`** : nombre d'ordres bloqués par re-fetch (drift, solde insuffisant, fill échoué)
- **`skip_type` et `skip_detail`** pour chaque ordre skippé en Phase 5 (collectés dans `orders_skipped_detail`)
- **`open_positions`** : recalculé depuis `trade_history.json` après cette phase

**4. Phase 6 — Rapport final**

Fallback explicite :
```python
top_score = top_score if 'top_score' in locals() and top_score else 0
```

**5. Phase 7 — Persistance MongoDB**

Bloc de fallbacks au démarrage de Phase 7 :
```python
top_score = top_score if 'top_score' in locals() else 0
executed = executed if 'executed' in locals() else 0
skipped = skipped if 'skipped' in locals() else 0
skip_type = skip_type if 'skip_type' in locals() else None
skip_detail = skip_detail if 'skip_detail' in locals() else None
sentiment = sentiment if 'sentiment' in locals() else "NEUTRAL"
open_positions = open_positions if 'open_positions' in locals() else 0
```

Ceci garantit que le document MongoDB peut toujours être écrit, même si une phase a échoué.

## Décisions techniques notables

- **Initialisation placée en tête du prompt** : avant Phase 0, garantit que les fallbacks sont en place quoi qu'il advienne
  
- **Double fallback (Phase 7)** : bien que les initialisations en début de prompt suffisent, un bloc de fallback explicite en Phase 7 sert de filet de sécurité et explicite l'intention

- **Classification skip_type explicite** : forcer le prompt à assigner `skip_type` en Phase 3/5 (plutôt que laisser `None` implicite) améliore la traçabilité et le debug

- **Pas de modification architecturale** : aucun changement au flux des 7 phases, uniquement clarification et ajout de fallbacks

## Impact sur l'architecture

Changement isolé au prompt, sans impact sur l'architecture ou les dépendances. Effets visibles :
- **Robustesse** : Phase 7 et 8 ne peuvent plus échouer sur `UnboundLocalError`
- **Traçabilité** : chaque variable a un point d'assignation explicite, facilite le debug
- **Documentation** : les instructions claires permettent à un nouveau développeur de comprendre où chaque variable est définie

## Références CLAUDE.md respectées

- **Aucune modification applicative** : changement entièrement dans `prompts/trade_prompt.txt`
- **Classification skip_type conforme** : les types TYPE_A/B/C/D respectent la classification définie en CLAUDE.md §"Cycles de trading : skip_type et skip_detail"
- **Persistance Mongo conforme** : le document `cycles` inclut `skip_type`, `skip_detail`, `executed`, `skipped`, `top_score` comme prévu
