# PR #327 — [M1] TP intelligent basé sur les résistances TradingView (Phase 4)

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-325-smart-tp-resistance`
> **Issues** : #325

## Contexte

La Phase 4 (Sizing) calculait historiquement le take-profit (TP) de manière mécanique, en appliquant une formule fixe : `TP = prix_entry × (1 + stop_distance_pct × reward_risk_ratio)`. Ce TP était souvent trop agressif (3× le risque appliqué) et ne tenait pas compte des vrais niveaux de résistance du marché détectés par TradingView.

La PR #326 ([M1] Phase 2 combined_analysis) a introduit l'extraction automatique des résistances TradingView (`resistance_1_4h`, `resistance_2_4h`, `nearest_resistance_4h`). Cette PR exploite ces nouvelles données pour calculer un TP plus intelligent et plus réaliste, plafonné par la résistance la plus proche au-dessus du prix d'entry, tout en conservant un fallback vers le TP mécanique pour les cycles sans résistance disponible.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/phases/phase4_sizing.txt` | Modification | Remplacement du calcul TP mécanique par une logique conditionnelle : utilise résistance TradingView si disponible, fallback vers TP mécanique sinon ; notification Telegram affiche la source du TP |

### Algorithme ajouté (Phase 4)

**Calcul du TP intelligent** (lignes 23–38 du nouveau fichier) :

```
# Extraire les résistances depuis Phase 2
r2_4h = analysis_results[coin].get("resistance_2_4h")    # résistance 2 sur 4h
r1_1d = analysis_results[coin].get("resistance_1_1d")    # résistance 1 sur 1D (None pour l'instant)

# Prendre la résistance la plus proche strictement au-dessus du prix entry
candidates = [r for r in [r2_4h, r1_1d] if r and float(r) > prix_entry]
nearest_resistance = min(candidates) if candidates else None

if nearest_resistance:
    tp_resistance = float(nearest_resistance) × 0.98    # marge de 2% sous la résistance
    prix_tp = min(tp_mecanique, tp_resistance)          # ne réduit pas un TP déjà conservateur
    tp_source = f"R {nearest_resistance:.4g} × 0.98"
else:
    prix_tp = tp_mecanique
    tp_source = "mécanique"
```

**Notification Telegram enrichie** (Phase 4) :
- Avant : `TP: 1.2902`
- Après : `TP: 1.2460 (R 1.271 × 0.98)` ou `TP: 1.2902 (mécanique)`

## Décisions techniques notables

- **Marge de 2% sous la résistance** : évite les ordres SELL remplis trop proches de la résistance exacte où le marché peut rebondir sharply. Empiriquement, 2% offre un compromis entre capture de la tendance et protection contre le rejet.

- **Minimum avec TP mécanique** : `prix_tp = min(tp_mecanique, tp_resistance)` — la résistance ne réduit un TP que si elle est plus proche que le TP mécanique. Un TP mécanique déjà conservateur (ex : ATR faible) n'est jamais remplacé par une résistance plus éloignée.

- **Fallback explicite** : aucune régression — si `combined_analysis` échoue en Phase 2 (champ `resistance_2_4h = None`), le TP revient automatiquement au TP mécanique. Pas d'attente vaine de résistances manquantes.

- **Pas de modification de variable clé** : les variables `prix_tp` et `tp_source` sont calculées localement dans la Phase 4 du prompt, sans toucher à la logique dimensionnement (quantité, montant, vérifications SKIP TYPE_B).

## Impact sur l'architecture

**Changement isolé, impact nul sur l'architecture globale.**

Phase 4 élargit la logique d'ordre en conditionnant le TP selon les données marché Phase 2, mais :
- L'ordre de phases reste inchangé (Phase 2 → Phase 4)
- Les phases 0–3, 5–8 ne sont pas affectées
- L'interface vers Kraken CLI (execution Phase 5) reste identique (mêmes variables `prix_entry`, `prix_stop`, `prix_tp`)
- La persistance MongoDB, les heartbeats, les notifications restent inchangés

**Dépendance** : exige que PR #326 (Phase 2 combined_analysis) soit mergée et fonctionnelle. Si Phase 2 n'expose pas les résistances, le fallback (`tp_source = "mécanique"`) prend le relais sans cassure.

## Références CLAUDE.md respectées

- **Minimalisme** : 18 lignes de code prompt ajoutées pour un changement stratégique complet (pas de refactoring adjacent).
- **Aucune modification applicative** : seul `prompts/phases/phase4_sizing.txt` est modifié, aucun Python touché. L'exécution reste sous le contrôle du sous-processus Claude.
- **Format date** : aucun nouveau timestamp — logique purement conditionnelle sur des champs existants.
- **Dépendances stables** : pas de nouvelles variables d'env, pas de nouvelles dépendances Python.

## Test plan (merging user)

- [ ] Vérifier que `analysis_results[coin]` contient bien `resistance_2_4h` et `resistance_1_1d` après Phase 2 (PR #326 mergée)
- [ ] Cycle avec résistance disponible au-dessus du prix entry : `prix_tp` doit être `min(tp_mecanique, resistance × 0.98)` et notification affiche `(R X × 0.98)`
- [ ] Cycle sans résistance (Phase 2 échoue → None) : `prix_tp` doit rester `tp_mecanique` et notification affiche `(mécanique)`
- [ ] Cycle où `tp_mecanique < resistance × 0.98` : `prix_tp` conserve `tp_mecanique` (résistance plus éloignée ignorée)
- [ ] Notification Telegram Phase 4 affiche bien `(tp_source)` après la valeur TP
- [ ] Redémarrage bot et vérification `/status` (utilisateur avant merge)
