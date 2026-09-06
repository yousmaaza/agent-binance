# PR #466 — [BUG] L'analyse hebdo échouait sur ses propres sous-totaux

> **Mergée le** : 2026-09-06
> **Branche** : `feat/issue-465-sous-totaux-hebdo`
> **Issues** : #465

## Contexte

L'analyse hebdomadaire rédigée par Claude échouait deux fois de suite en rejetant des nombres qu'elle venait elle-même de calculer : `-33.04` (net réel des sorties au stop) et `15.28` (nombre non rattachable). Le garde-fou numérique (#453) rejetait ces valeurs car elles n'existaient pas dans la charge utile transmise au modèle. La contradiction venait du prompt lui-même : il autorisait la dérivation (« s'en déduire par une opération simple ») mais le contrôle la refusait.

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `binance-bot/core/weekly_analysis.py` | Modification | Ajout fonction `_net_by()`, exposition des sous-totaux dans la payload, durcissement du prompt |
| `tests/test_weekly_analysis.py` | Test | Validation des sous-totaux et cohérence avec le garde-fou (5 tests ajoutés) |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_net_by(trades, key_fn)` | Ajoutée | Calcule les sous-totaux (net_usdc + effectif) regroupés par une clé arbitraire (motif de sortie, crypto, etc.). L'effectif est présent pour éviter de croire à une tendance sur un seul trade. |
| `_build_payload(...)` | Modifiée | Ajoute deux champs à la charge utile : `by_close_reason` (sous-totaux par motif de sortie — tp_watcher, sl_hit, etc.) et `by_coin` (sous-totaux par crypto). Ces valeurs étaient autrefois recalculées par le modèle. |
| `_build_prompt(...)` | Modifiée | Remplace la consigne « s'en déduire par une opération simple » par « N'écris QUE des nombres présents tels quels dans le JSON ». Énumère explicitement les champs de sous-totaux disponibles (`aggregate`, `by_close_reason`, `by_coin`, `significance`). |

## Décisions techniques notables

- **Effectif dans les sous-totaux** : chaque bucket contient `net_usdc` ET `count`. Un montant sans effectif laisse croire à une tendance là où il n'y a parfois qu'un seul trade — cette clarification avait été manquée dans le premier cadrage.

- **Clés manquantes nommées, non omises** : quand un trade n'a pas de `close_reason`, la clé devient `"non renseignée"` (pas `None`). Cela évite de confondre les valeurs manquantes avec les vrais zéros.

- **Validation testée** : le lien critique entre l'exposition des sous-totaux et leur acceptance par le garde-fou a reçu un test unitaire (`test_subtotals_are_reachable_by_the_numeric_guard`). Un choix de valeur de test (`-777.77`) hors de portée assure que l'assertion ne s'écoule pas silencieusement.

## Impact sur l'architecture

Changement isolé, pas d'impact architectural : la fonction `_net_by()` ne touche que la structure de la charge utile du modèle. Le reste du pipeline d'analyse (sélection de fenêtre, significativité, cycles summary) reste inchangé. Deux générations consécutives qui avaient échoué (2026-09-05) sont maintenant attendues de réussir.

## Références CLAUDE.md respectées

- **Règle 0 : passer par binance-dev** — validation par la PR workflow
- **Règle 5 : minimalisme** — ajout de 26 lignes code + 43 lignes tests, zéro refactoring adjacent
- **Règle 8 : logique interne en UTC** — les timestamps des trades dans `by_close_reason` restent en UTC (décision inchangée)

