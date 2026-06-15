# PR #235 — Augmente max_single_position_pct de 0.40 à 0.65

> **Mergée le** : 2026-06-15
> **Branche** : `feat/issue-218-config-max-single-position`
> **Issues** : #218

## Contexte

Résolution du problème identifié le 2026-06-12 : deux cycles consécutifs ont été bloqués avec un statut `TYPE_B` (montant < seuil minimal), car le capital résiduel était faible. Ce paramètre contrôle la fraction maximale du portefeuille allouable à une seule position. En le portant de 0.40 (40%) à 0.65 (65%), on rend possible le passage d'ordres au seuil minimum de 11 USDC même après un drawdown.

**Exemple numérique** :
- Capital disponible avant merge : 17.24 USDC
- Ancien calcul (0.40) : 17.24 × 0.40 = **6.90 USDC** < 11 USDC → TYPE_B skip
- Nouveau calcul (0.65) : 17.24 × 0.65 = **11.21 USDC** > 11 USDC → ordre exécutable

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Modification | Augmentation d'un paramètre de configuration d'ordre (une ligne) |

### Paramètres modifiés

| Paramètre | Ancien | Nouveau | Raison |
|---|---|---|---|
| `max_single_position_pct` | `0.40` | `0.65` | Permettre le passage d'ordres au seuil minimum (11 USDC) sur portefeuilles en drawdown |

## Décisions techniques notables

- **Minimisme** : modification d'une seule ligne de configuration JSON ; aucun changement de code applicatif
- **Validité** : syntaxe JSON vérifiée par le test plan (`python3 -c "import json; json.load(open('config.json'))"`)
- **Portée** : affecte uniquement la Phase 3 (Scoring) où le paramètre est consulté pour valider le dimensionnement

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. La valeur est consultée à la Phase 4 (Sizing) lors du calcul `amount_usdc = capital_residuel * max_single_position_pct` pour chaque candidat BUY. Une augmentation du plafond réduit simplement le nombre de cycles bloqués en TYPE_B lors de capital résiduel faible.

## Références CLAUDE.md respectées

- **Règle : Minimalisme** — Code minimum qui résout le problème ; aucune abstraction spéculative
- **Règle : Modifications chirurgicales** — Un paramètre de configuration, rien d'autre ; pas d'amélioration du code adjacente
- **Règle : Pas de secret hardcodé** — La configuration vit dans `config.json`, pas en dur dans le code
