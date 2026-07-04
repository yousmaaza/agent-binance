# PR #342 — Augmenter min_profit_pct_take de 2% à 5%

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-341-min-profit-pct-5`
> **Issue** : #341

## Contexte

La Phase 0 réalise automatiquement les profits quand le gain en pourcentage (`pnl_pct`) dépasse le seuil `min_profit_pct_take`. Ce paramètre était historiquement à 2%, ce qui fermait les positions trop tôt : un ordre avec un take-profit visé à +6% était vendu à +3%, contre-productif pour la stratégie récompense/risque.

La hausse à 5% garantit que :
1. Les positions ne se ferment que si elles atteignent un gain substantiel
2. Le seuil respecte la stratégie MM.04 (reward_risk_ratio de 2× l'ATR stop)
3. Les biais de fermeture prématurée sont éliminés

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Modification | Augmentation du seuil de prise de profit de `2.0` à `5.0` |

### Configuration changée

| Paramètre | Ancienne valeur | Nouvelle valeur | Rôle |
|---|---|---|---|
| `min_profit_pct_take` | `2.0` | `5.0` | Seuil minimal (%) pour la clôture automatique en Phase 0 |

## Décisions techniques notables

- **Format de config statique** : Le paramètre reste dans `config.json` (pas de migration dynamique), cohérent avec les autres seuils (min_signal_score, min_adx, etc.)
- **Compatibilité rétroactive** : La fonction `_load_config()` applique déjà un fallback à `2.0` si la clé est absente, donc les versions antérieures sans ce changement ne planteront pas
- **Pas de modification de code applicatif** : Le changement est pur configuration ; la lecture via `phase0_profit.py:25` utilisait déjà `_load_config().get("min_profit_pct_take", 2.0)`

## Impact sur l'architecture

Changement isolé, sans impact architectural. Le flux Phase 0 (`phase0_profit.py`) reste inchangé ; seule la décision de seuil se fait avec une valeur plus restrictive.

La cohérence stratégique est conservée :
- Phase 4 calcule le stop-loss via `atr_stop_multiplier: 3.5` → ~3–4% de risque
- Phase 0 prend les profits à 5% → ratio récompense/risque ~1.3×, donc profitable sur la durée

## Références CLAUDE.md respectées

- **Règle 3 (Aucun secret hardcodé)** : Utilise `.env` non requis ; le paramètre est déjà ici en configuration
- **Principes de minimalisme** : Pas de fonction additionnelle, changement chirurgical (1 ligne modifiée)
- **Configuration via config.json** : Conforme au pattern existant pour les paramètres stratégiques
