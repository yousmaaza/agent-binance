# PR #363 — [M1] Abaisser min_volume_usdc de 1M à 500k

> **Mergée le** : 2026-07-21
> **Branche** : `feat/issue-357-evaluer-un-abaissement-de-min-volume`
> **Issues** : #357

## Contexte

Ticket #357 demandait une évaluation de l'abaissement du seuil `min_volume_usdc` de 1M à 500k USDC pour élargir l'univers de coins tradables en Phase 1. L'objectif était d'identifier les coins supplémentaires devenant disponibles tout en maintenant une liquidité suffisante pour éviter les slippages excessifs.

Analyse préalable (dans le body de la PR) :
- À 1M USDC : 3 coins passent le filtre (XBT, ETH, SOL)
- À 500k USDC : 5 coins passent le filtre (XBT, ETH, SOL, XRP, ADA)
- Gain net : ADA devient tradable (XRP est toujours inclus via `portfolio_coins`)

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Modification | Paramètre `min_volume_usdc` : `1000000` → `500000` |

### Fonctions affectées

| Fonction | Fichier | Action | Impact |
|---|---|---|---|
| Phase 1 scan | `binance-bot/core/phases/phase1_scan.py:75` | Utilise le nouveau seuil | Élargit l'univers de coins candidats en Phase 1 |

La logique de Phase 1 (`phase1_scan.py` ligne 75) lit déjà `min_volume_usdc` depuis `config.json` (ligne 33) ; aucune modification de code n'était nécessaire. Le changement est purement paramétrique.

## Décisions techniques notables

- **Paramètre dans `config.json` uniquement** : aucune modification du code Python. Le seuil est déjà externalisé, ce qui permet des ajustements rapides sans redéploiement du code (conforme à CLAUDE.md).
- **Bypass portfolio_coins** : les coins configurés dans `portfolio_coins` (XBT, XRP, SOL) restent toujours tradables indépendamment du seuil de volume, ce qui protège la stratégie de base même si un coin principal perdait temporairement sa liquidité.

## Impact sur l'architecture

Changement isolé — pas d'impact architectural. La Phase 1 conserve son comportement fonctionnel (filtre volume + inclusion portfolio). Seul l'ensemble des coins candidats s'élargit graduellement à chaque cycle.

**Observable** : les rapports Phase 1 (`logs/stdout/cycle_*.log`) afficheront un `tradable=N` plus élevé, et `non_tradable` sera plus compact.

## Références CLAUDE.md respectées

- **Principe minimalisme** : aucun code spéculatif ; changement paramétrique pur.
- **Modification chirurgicale** : un seul paramètre touché, aucun adjacent du code.
- **Tests de stabilité** : pas d'ajustement d'ATR, leverage, ou seuils de score. L'augmentation du pool candidats est progressive (contrôlée par Phase 3 scoring).

## Notes

Une divergence doc/code a été détectée (non corrigée dans cette PR, hors scope) : `CLAUDE.md` mentionne un seuil TYPE_D de 5M USDC, alors que le code n'implémente que `min_volume_usdc`. À clarifier séparément si besoin.
