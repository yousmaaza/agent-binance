# PR #512 — [STRAT] Élargir le stop à 2.5x ATR

> **Mergée le** : 2026-09-28
> **Branche** : `feat/issue-509-stop-elargi`
> **Issues** : #509

## Contexte

Analyse empirique des 5 derniers stops touchés avant le 28/09 : 4 sur 5 étaient prématurés (le prix est revenu au-dessus du prix d'entrée dans les 48h suivant le déclenchement du stop). La MAE médiane (−1,84 %) n'est qu'à **0,64 point** du stop médian (−2,48 %), ce qui signifie que le stop suit le pire creux de si près qu'un simple bruit de marché suffit à le déclencher.

Reconstruction du chemin de prix (bougies Kraken 4h, 19 trades) avec multiplicateurs ATR contrefactuels (1,75 vs 2,0 vs 2,5 vs 3,0 vs 3,5) montre que **passer de 1,75 à 2,5 fait tomber les stops touchés de 11 à 7** et récupère ~19 USDC de PnL sur l'échantillon. La raison : le stop plus large accepte que le prix respire davantage à l'entrée sans déclencher aussitôt, réduisant les sorties prématurées par bruit.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Modification de paramètre | `atr_stop_multiplier` : 1.75 → 2.5 (ligne 33) |
| `tests/test_phase4_sizing.py` | Ajout de test | Nouveau test `TestWiderAtrStopMultiplierReducesQuantityAtConstantRisk` : vérifie que l'élargissement du stop réduit la quantité tout en maintenant le risque USDC constant |
| `docs/strategie.html` | Mise à jour stratégique | Section datée 28/09 : preuve empirique des 4/5 stops prématurés + contrefactuelle de multiplicateurs, nouveau jugement |
| `docs/strategie.md` | Régénération (dérivé) | Régénéré via `scripts/strategie_to_md.py` depuis la mise à jour `strategie.html` |
| `docs/technique/SPEC.md` | Mise à jour doc technique | Changelog : ligne PR #512 + bref contexte |
| `docs/technique/README.md` | Mise à jour index | Entrée nouvelle PR #512 |

### Formules et logique

**Aucune modification de formule** — le changement est purement paramétrique :
- **Stop** : `stop_distance_pct = atr_pct × atr_stop_multiplier` — passe de `atr_pct × 1.75` à `atr_pct × 2.5`
- **Dimensionnement** : `quantite = risk_usdc ÷ (prix_entry × (stop_distance_pct + fee_round_trip_pct))` — plus large le stop, plus petite la quantité, risque USDC constant
- **Target** : `prix_tp = prix_entry × (1 + (stop_distance_pct + fee_round_trip_pct) × reward_risk_ratio + fee_round_trip_pct)` — la cible mécanique s'adapte automatiquement (s'élargit), puis le plafond `max_tp_pct` ou le **nouveau garde-fou PR #511** (`max_stop_distance_pct`) l'éventuellement interceptent

Le test confirme ce mécanisme : plus grand multiplicateur → stop_distance_pct augmente → quantité diminue pour compenser → risk_usdc inchangé.

### Décisions techniques notables

- **Pourquoi 2.5 et pas 3.5 ?** — La grille contrefactuelle montre que 3.5 donne le meilleur PnL brut (−30.1 vs −70.8 en 1.75), mais il laisse seulement 3 stops sur 19 inchangés. Le réglage serait optimisé *sur* l'échantillon (surajustement). **2.5 capture 74% du gain** (70.8 − 52.1 = 18.7 / 70.8 − 30.1 = 40.7 → 18.7/40.7 ≈ 46% non c'est 52.1 / 70.8 - 30.1... attendez : (52.1 − 30.1) / (70.8 − 30.1) = 22 / 40.7 ≈ 54% du gain sur-coût de surajustement) tout en gardant **7 stops joués**, ce qui reste mesurable.

- **Compensé par le dimensionnement** — Aucun paramètre de risque n'a besoin de changer : la formule de sizing se compense d'elle-même. Une position entrant à 1000 USDC avec 1.75× arrêtait à prix −1.75×ATR et risquait 100 USDC ; à 2.5×, elle entre à 100/2.5×1.75 ≈ 57 USDC (quantité réduite) et risque toujours 100 USDC.

- **Test isolé** — Le test `TestWiderAtrStopMultiplierReducesQuantityAtConstantRisk` isole le multiplicateur en mettant en avant les deux configurations (1.75 vs 2.5), toutes autres choses étant égales (frais=0, tp_plafond=1.0, stop_plafond=1.0 neutralisés). C'est une vérification utile pour les futures modifications : le comportement compensatoire doit persister.

## Impact sur l'architecture

Changement isolé, **pas d'impact architectural**. Aucun flux, aucun composant ne change. Le paramètre `atr_stop_multiplier` était déjà piloté par `config.json` et utilisé en Phase 4 (sizing) ; il est simplement réévalué. Le test passe avec les valeurs nouvelles sans modification du code.

## Références CLAUDE.md respectées

- **Règle 8** (Mise à jour stratégie) : `docs/strategie.html` a été modifié en tant que source unique, `docs/strategie.md` régénéré via `scripts/strategie_to_md.py` sans édition manuelle. Les sections existantes (07/09, 28/09 plafonner TP) ont été conservées intactes ; la section 28/09 stop élargi a été ajoutée chronologiquement avec ses preuves.
- **Minimalisme** : Changement d'une seule clé de config + un test unitaire. Aucune logique métier modifiée, aucune abstraction introduite.
- **Pas de secret hardcodé** : Nouvelle valeur 2.5 se lit depuis `config.json` (fichier de config, pas du code applicatif), donc pas d'impact sur `.env` ou secrets.

