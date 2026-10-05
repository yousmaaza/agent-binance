# PR #520 — Cible au plancher quand la résistance 4h est trop proche

> **Mergée le** : 2026-10-05
> **Branche** : `feat/issue-519-cible-plancher-resistance-proche`
> **Issue** : #519

## Contexte

Depuis la PR #516, la résistance 4h plafonnait la cible TP (`cible = min(capped, resistance × 0.98)`). Mais quand la résistance était trop proche de l'entrée, le rabais 0,98 produisait une cible tombant sous le plancher de viabilité (`entry × (1 + 2 × frais)` = +1,8 %). Dans ce cas, la logique retombait sur le plafond absolu `max_tp_pct` = +6 %, ignorant la résistance.

L'issue #519 propose un changement : si la résistance est présente et dépasse l'entrée, mais que `résistance × 0.98 < plancher`, la cible devient le plancher lui-même (+1,8 %) au lieu de remonter au plafond (+6 %). Une résistance trop proche ne mérite pas une cible haute — elle impose une cible basse.

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `binance-bot/core/trade_helpers.py` | Modification logique | Ajoute un garde-fou plancher à `compute_tp_target()` |
| `tests/test_phase0_recalibrate_tp_floor.py` | Modification tests | 6 nouveaux cas de test, 1 classe entière pour la règle plancher |
| `tests/test_resistance_4h.py` | Modification tests | Ajustement des valeurs attendues |
| `docs/strategie.html` | Mise à jour doc | Ajoute section 05/10 avec mesures et rejeu |
| `docs/strategie.md` | Mise à jour doc | Version markdown régénérée |
| `scripts/target_floor_replay.py` | Nouveau script | Rejeu compare règle ancienne #516 vs plancher #519 |

### Fonction modifiée

| Fonction | Action | Description |
|---|---|---|
| `compute_tp_target()` | Modifiée | Ajoute branche : si `resistance > entry` et `resistance × 0.98 < plancher` → retourne `plancher`. La résistance est trop proche pour justifier une cible plus haute. Cas existants inchangés. |

## Décisions techniques notables

- **Pas de nouvelle clé de config** : la règle plancher est inconditionnelle et découle du même plancher que le plancher d'ordre minimaliste (2 × frais). Aucune flexibilité requise.
- **Trois cas de sortie logiques** :
  1. Résistance > entry ET résistance × 0.98 < plancher → cible = plancher (#519 nouveau)
  2. Résistance > entry ET résistance × 0.98 ≥ plancher → cible = min(capped, résistance × 0.98)
  3. Résistance absent ou ≤ entry → cible = min(mécanique, plafond)
  
  Cas 3 est inchangé. Cas 2 n'est jamais affecté car la résistance respects le plancher. Cas 1 prend la place de l'ancienne branche qui remontait au plafond absolu.

- **Rejeu non décisif** : `-3,22 USDC` depuis le 03/07 (77 trades), `+4,64 USDC` depuis le 22/08 (28 trades). Les écarts changent de signe selon la période — pas de dégradation nette ni d'amélioration robuste. Implémenté sur choix utilisateur (principe stratégique), pas sur la mesure.

## Impact sur l'architecture

Changement isolé à `compute_tp_target()`, qui sert trois points d'appel :
1. **Phase 0** (recalibrage TP) : même logique
2. **Phase 4** (sizing initial) : même logique
3. **Phase 5** (suivi maker) : même logique

Les trois consommateurs sont cohérents. Aucun nouveau composant, aucune nouvelle dépendance. La fonction reste déterministe et testable. Les phases 0, 4 et 5 n'ont aucun changement logique direct.

## Références CLAUDE.md respectées

- **Règle 8 — Toute modification de la stratégie met à jour les docs** : `docs/strategie.html` et `docs/strategie.md` (régénéré) incluent la section 05/10 avec mesures de rejeu. ✅
- **Minimalisme** : un seul `if` ajouté, une branche supprimée. Pas de refacto adjacent. ✅
- **Tests** : classe `TestResistanceBelowFloorKeepsAbsoluteCap` couvre les 6 cas de la règle. ✅
- **Pas de secret hardcodé** : aucune dépendance externe ajoutée. ✅

## Test coverage

**Tests unitaires** (`tests/test_phase0_recalibrate_tp_floor.py`) :
- `TestResistanceBelowFloorKeepsAbsoluteCap` : 6 cas
  - Résistance × 0.98 < plancher → cible = plancher
  - Résistance juste au-dessus entry → cible = plancher
  - Résistance < ou = entry → cible = plafond (inchangé)
  - Pas de résistance → cible = plafond (inchangé)
  - Résistance entre plancher et plafond → cible = résistance × 0.98 (inchangé)
  - Résistance pile au plancher : edge case ✅
  
Tous les tests pré-existants passent (`TestLowResistance*`, `TestResistanceAbove*`, `TestNoResistance*`, `TestAbsoluteCap*`, etc.) — aucun changement dans les autres branches.

**Rejeu** (`scripts/target_floor_replay.py`) :
- Compares règle ancienne (#516) vs plancher (#519) sur 77 trades depuis 03/07 et 28 trades depuis 22/08
- Rejoue les deux règles avec bougies 4h Kraken, frais réels (maker 0,30 %, taker 0,60 %), break-even et partiel actifs
- Résultats : écart non concluant (−3,22 vs +4,64 USDC selon la série)
