# PR #340 — Trailing stop ne doit pas modifier le TP (Phase 0)

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-339-trailing-stop-no-tp-override`
> **Issues** : #339

## Contexte

Le bug observé le 2026-07-04 sur la position ETH : le TP avait été recalibré intelligemment à 1851 USDC (R2×0.98 issu de la Phase 4 / `/calibrage`) mais le trailing stop du cycle suivant l'écrasait à 2159 USDC via le calcul `new_tp = max(cur_tp, round(price + trail_dist * 3, 8))`. Cette surcharge empêchait le TP intelligent de s'exprimer et causait des sorties non optimales.

La fix sépare clairement les responsabilités :
- **Trailing stop (Phase 0)** : remonte uniquement le `stop_price` (SL) si le prix a progressé.
- **TP intelligent (Phase 4 / `/calibrage`)** : calcule et maintient le `tp_price` basé sur les résistances TradingView.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase0_trailing_stop.py` | Suppression | Trailing stop recentré sur SL uniquement |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| Bloc trailing stop _(Phase 0)_ | Modifié | Supprime la recalcul `new_tp` qui écrasait le TP ; conserve le remontée du SL et ses vérifications de sécurité |

### Détail des suppressions

- **Ligne 39** : suppression `cur_tp = float(t["tp_price"])` — TP courant n'est plus lu
- **Ligne 71** : suppression `new_tp = max(cur_tp, round(price + trail_dist * 3, 8))` — aucun recalcul TP
- **Ligne 92** : suppression `new_tp_r = _round_price(new_tp, tick)` — arrondi TP supprimé
- **Ligne 96** : simplification fallback : `new_stop_r, new_tp_r = new_stop, new_tp` → `new_stop_r = new_stop`
- **Ligne 112** : suppression `t["tp_price"] = new_tp_r` — TP n'est plus modifié
- **Ligne 106-109** : suppression `"attempted_new_tp": new_tp_r` du log structuré
- **Ligne 119-120** : suppression `"old_tp": cur_tp, "new_tp": new_tp_r` des logs
- **Ligne 122-126** : simplification message Telegram (plus de mention TP)

### Code avant / après

**Avant (bug)** :
```python
cur_tp = float(t["tp_price"])
new_stop = round(price - trail_dist, 8)
new_tp = max(cur_tp, round(price + trail_dist * 3, 8))  # ← écrase le TP !
# ... vérifications ...
t["stop_price"] = new_stop_r
t["tp_price"] = new_tp_r  # ← TP modifié par le trailing stop
```

**Après (fixe)** :
```python
# cur_tp n'est plus lu — TP est immutable en Phase 0
new_stop = round(price - trail_dist, 8)
# aucun calcul new_tp
# ... vérifications ...
t["stop_price"] = new_stop_r
# t["tp_price"] absent — TP inchangé
```

## Décisions techniques notables

- **Séparation des responsabilités** : Phase 0 = SL uniquement, Phase 4 + `/calibrage` = TP uniquement. Élimine les écrasements accidentels.
- **Pas de recalcul heuristique** : la formule `price + trail_dist × 3` n'avait aucune justification stratégique — mieux vaut laisser le TP intelligent (basé MCP TradingView) décider.
- **Messages Telegram simplifiés** : affichage réduit à `{coin}: stop {cur_stop:.4g}→{new_stop_r:.4g}` — plus clair sans les mentions TP.

## Impact sur l'architecture

**Aucun impact architectural.** Changement isolé : **Phase 0** perd sa capacité de recalcul TP (erronée), **Phase 4** et **`/calibrage`** conservent leur autorité exclusive sur le TP. Les positions conservent leur TP intelligent et ne sont plus surécrasées.

## Références CLAUDE.md respectées

- **Règle 5 — Modifications chirurgicales** : modification très ciblée (suppression de 11 lignes responsables du bug, aucun ajout), conserve le contexte du trailing stop lui-même
- **Règle 2 — Python venv 3.11** : aucune modification de dépendances
- **Règle 5 — Stdout/stderr toujours capturés** : logs structurés conservés via `log_phase0_event()`
