# PR #39 — [BUG] Phase 5 — Remplacer OTOCO par BUY MARKET + OCO immédiat

> **Mergée le** : 2026-05-21
> **Branche** : `feat/issue-38-phase5-buy-market-oco-protection`
> **Issues** : #38

## Contexte

L'ordre OTOCO (`order-list-otoco`) combinait en une seule requête l'ordre d'entrée LIMIT et les protections TP/SL. En pratique, des wicks rapides entre le fill de l'entrée et la pose de la protection provoquaient des erreurs `protection_failed` : le prix fixé pour le TP/SL était calculé sur le prix pre-fill et non sur le prix de fill réel, ce qui déclenchait des rejets Binance. De plus, si l'OTOCO échouait complètement, la position restait non protégée sans mécanisme de rattrapage.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification du `_TRADE_PROMPT_TEMPLATE` | Phase 5 entièrement réécrite + nouvelle routine de rattrapage en Phase 0 |

### Sections du prompt ajoutées / modifiées

| Section | Action | Description |
|---|---|---|
| Phase 5 — Étapes 1-8 | Remplacée | Suppression de `order-list-otoco` ; remplacement par `order-market` BUY puis `order-list-oco` SELL standalone calculé sur `actual_entry = cummulativeQuoteQty / executedQty` |
| Phase 0 — Rattrapage `protection_failed` | Ajoutée | Routine idempotente qui détecte les trades `status="open"` et `protection_failed=True` dans `trade_history.json`, vérifie qu'aucun OCO actif n'existe (idempotence), puis soit replace un OCO de rattrapage (prix actuel ≤ TP calculé) soit ferme à market (prix actuel > TP calculé) |
| Champ `protection_failed` dans le document trade | Ajouté | Nouveau champ booléen dans l'entrée `trade_history.json` (Phase 5, étape 7) ; `True` si l'OCO a échoué après le BUY MARKET |

## Décisions techniques notables

- **Séquence BUY MARKET → OCO SELL** : en séparant l'entrée de la protection en deux appels distincts, le prix de fill réel (`cummulativeQuoteQty / executedQty`) est disponible avant de poser l'OCO. Le TP et le SL sont recalculés sur `actual_entry`, ce qui élimine la race condition wick/protection_failed de l'OTOCO.

- **Garde `prix_post_fill >= actual_tp`** : après le fill BUY, le prix est re-fetché. Si le marché dépasse déjà le TP recalculé (wick ultra-rapide), la position est fermée à market immédiatement sans tenter l'OCO — `close_reason="market_above_tp_at_fill"`. Cela évite un rejet certain de l'OCO dans ce cas limite.

- **Routine de rattrapage en try/finally (Phase 0)** : l'ensemble du bloc de rattrapage est encapsulé dans un `try/finally` pour garantir que le lock n'est jamais conservé même en cas d'erreur dans la routine. L'idempotence est assurée par vérification des ordres ouverts Binance (`get-open-orders`) avant toute tentative de replacement.

- **Vérification LOT_SIZE avant l'OCO** : `get-exchange-info` est appelé pour récupérer le `stepSize` du filtre LOT_SIZE et arrondir `actual_qty_oco` au step inférieur — requis pour éviter les rejets Binance sur la quantité.

- **Champ `protection_failed` dans `trade_history.json`** : introduit pour tracer les positions non protégées entre deux cycles. Il n'impacte pas les trades existants (champ absent = `False` implicite dans la Phase 0 de rattrapage).

## Impact sur l'architecture

Phase 5 ne passe plus par `order-list-otoco` mais par la séquence `order-market` (BUY) + `order-list-oco` (SELL). Le diagramme `trade-phases.d2` était libellé "Phase 5 — Exécution OTOCO" ; cette étiquette est désormais caduque mais non mise à jour dans les sources D2 (impact visuel mineur, correction possible via `/generate-diagrams`).

La Phase 0 acquiert une nouvelle responsabilité : elle agit désormais comme un mécanisme de self-healing entre cycles pour les positions non protégées, en complément de sa mission de vérification de solde et de daily loss limit. Ce changement élargit la portée de Phase 0 mais ne modifie pas le flux principal (`main_loop → run_trade_workflow`).

La structure de `state/trade_history.json` s'enrichit d'un nouveau champ optionnel `protection_failed` (booléen). Les entrées existantes sans ce champ restent compatibles (traitement par valeur par défaut `None`/falsy dans la Phase 0).

## Références CLAUDE.md respectées

- **Règle 1 (curl)** : le helper `tg()` continue d'utiliser `subprocess.run(["curl", ...])` pour toutes les notifications dans le prompt — aucune régression `urllib`.
- **Règle 4 (capture stdout/stderr)** : `run_trade_workflow()` non modifiée ; la capture `logs/stdout/` et `logs/stderr/` est préservée.
- **Règle 5 (UTC interne)** : tous les timestamps enregistrés dans `trade_history.json` (champ `exit_date`) utilisent `datetime.now(timezone.utc).isoformat()`.
