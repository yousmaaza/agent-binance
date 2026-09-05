# PR #460 — [BUG] Le garde-fou de l'analyse hebdo rejetait les dates

> **Mergée le** : 2026-09-05
> **Branche** : `feat/issue-458-garde-fou-dates`
> **Issues** : #458

## Contexte

L'analyse hebdomadaire (#453 — feature de génération par Claude) s'est déclenchée correctement le 31 août à 00:10 UTC mais a été rejetée par son propre garde-fou numérique. Le texte généré contenait la date du mois (« le 31 août »), dont le nombre « 31 » a été capturé par la regex de vérification `_NUMBER_RE` comme « affirmation financière non rattachée aux données ». Résultat : **aucune analyse n'a jamais été publiée**, et le dashboard a affiché le repli déterministe depuis.

La faille : le garde-fou était **trop strict sur le mauvais axe**. Il capturait tous les entiers (dates, durées, ordinaux) et exigeait que chacun se rattache aux données de trading, bloquant 100% des générations citant une date.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/weekly_analysis.py` | Modification | Affinement de la regex `_NUMBER_RE` pour ne vérifier que les affirmations financières |
| `tests/test_weekly_analysis.py` | Ajout | 58 lignes : 2 nouvelles classes de tests, 10 cas de test |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| `_extract_numbers()` | Modifiée | **Définition de `_NUMBER_RE` (lignes 31–39)** — remplace `-?\d+(?:\.\d+)?` par une regex restrictive : tout décimal (p. ex. `3.81`, `-11.87`) OU entier suivi d'une unité (`%`, `USDC`, `USD`, `$`, `€`, `EUR`). Un entier nu (date, durée, ordinal) ne passe plus. |
| `_verify_numbers()` | Pas de changement | Même contrat : retourne vrai si tous les nombres du texte se rattachent aux données. |

### Nouveaux tests

**Classe `TestNumberExtractionScope`** — vérifie le nouveau périmètre de capture :
- `test_dates_are_not_treated_as_financial_claims()` — « le 31 août, puis le 07/09 » → extracte rien
- `test_durations_are_not_treated_as_financial_claims()` — « sur 7 jours et les 30 derniers jours » → extracte rien
- `test_percentages_are_still_extracted()` — « 64% des trades », « 64 % des trades » → extracte [64.0]
- `test_amounts_with_a_unit_are_still_extracted()` — « a gagné 812 USDC », « perdu 45 $ » → extracte [812.0], [45.0]
- `test_any_decimal_is_extracted_even_without_a_unit()` — « écart-type de 3.81 » → extracte [3.81]
- `test_bare_counts_are_a_documented_gap_not_an_oversight()` — « 27 trades clôturés » → extracte rien (**limite assumée**, documentée explicitement)

**Classe `TestGuardStillRejectsFabricationAfterLoosening`** — vérifie que l'assouplissement ne rouvre pas la faille démontrée en #453 :
- `test_fabricated_win_rate_is_still_rejected()` — taux factice 64% → rejeté
- `test_free_percentages_are_still_rejected()` — enchevêtrement 73%, +41%, 88% → rejeté
- `test_invented_amount_is_still_rejected()` — montant 812.44 USDC (faux) → rejeté
- `test_a_text_citing_a_date_now_passes()` — **scénario exact du 31/08** — texte contenant une date → passe ✅

## Décisions techniques notables

- **Affinement du champ de vérification** : le garde-fou ne vérifiait que la syntaxe (tout entier), pas la sémantique (affirmation financière). Constater que la majorité des entiers d'un texte en prose sont des contextes (dates, durées) et ne font rien affirmer sur l'argent.

- **Limite assumée explicite** : un effectif écrit sans unité (« 27 trades clôturés ») n'est plus vérifié. Un entier nu sous 31 est indistinguable d'un quantième en prose — il fallait choisir entre laisser passer les comptes ou rejeter toute date. Rejeter les dates bloquait 100 % des générations, donc le compromis a tranché pour les comptes. **Documenté dans le code et figé par un test** (`test_bare_counts_are_a_documented_gap_not_an_oversight`) pour que ce compromis soit revu sciemment plutôt que découvert par surprise.

- **Regex alternée** : deux branches avec `|` (OU) pour maximum de clarté :
  - `-?\d+\.\d+` : tout décimal, presque toujours financier en contexte d'analyse
  - `-?\d+(?=\s*(?:%|USDC|USD|\$|€|EUR))` : entier avec lookahead positif sur une unité monétaire ou de pourcentage

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. La fonction `_extract_numbers()` est un utilitaire interne utilisé uniquement par `_verify_numbers()` (ligne 367), elle-même appelée une seule fois en Phase 7 du cycle (ligne 404 : `if not _verify_numbers(text, payload)`). Le contrat reste identique : même signature, même sémantique (vrai = données cohérentes, faux = génération échouée, repli déterministe).

## Référence CLAUDE.md respectées

- **Règle 1 (Minimalisme)** : Modification chirurgicale — seules 8 lignes changées dans `weekly_analysis.py`, le reste du code intact.
- **Règle 5 (Modification de code passe par l'agent `binance-dev`)** : PR créée par `binance-dev` depuis le ticket #458.
- **Règle de commentaire (Documentation du code)** : Ajout de commentaires détaillés explicant le POURQUOI (les dates bloquaient 100% des générations, pas une simple optimisation syntaxique).

## Vérification

- **455 tests passent**, dont les 10 ajoutés.
- **Couverture du garde-fou reste < 35%** : même sur la charge 37 trades de #453, un produit croisé accepterait 89% des entiers 0-100 comme pourcentage ; ici le catalogue reste borné et très restrictif (dizaines de valeurs).
- **Faille de #453 demeure fermée** : tous les cas de fabrication démontrés (taux factice 64%, montant inventé, pourcentages libres) restent rejetés sur la charge de test.
- **Scénario du 31/08 rejoué** : la même charge de 37 trades, un texte citant la date du 31, passe désormais ✅.

---

**Commit** : `6e857ee` — branche `feat/issue-458-garde-fou-dates` mergée dans `main`.
