# PR #39 — [BUG] Phase 5 — Remplacer OTOCO par BUY MARKET + OCO immédiat

> **Mergée le** : 2026-05-22
> **Branche** : `feat/issue-38-phase5-buy-market-oco-protection`
> **Issues** : #38

## Contexte

La stratégie d'exécution Phase 5 reposait sur l'ordre `order-list-otoco` : un BUY LIMIT de travail qui armait automatiquement un OCO SELL (TP + SL) dès que le fill était confirmé. Cette mécanique entraînait des entrées `protection_failed=True` dans `trade_history.json` lorsqu'un wick rapide ou une latence réseau faisait que le BUY était rempli mais que l'OCO n'arrivait pas à se poser (TP déjà dépassé ou race condition). Cinq positions actives (BTC, STX, SOL, AR, PENDLE) se retrouvaient exposées sans stop-loss ni take-profit.

De plus, l'entrée OTOCO utilisait un `prix_limit` pré-calculé avant l'exécution. En cas de fill partiel ou de glissement, le prix réel pouvait diverger du prix initial, et les niveaux TP/SL enregistrés étaient incorrects.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Delta |
|---|---|---|
| `scripts/webhook_server.py` | Refactoring TRADE_PROMPT : Phase 5 + Phase 0 rattrapage | +167 / −27 |

### Fonctions / sections modifiées

| Section TRADE_PROMPT | Action | Description |
|---|---|---|
| Phase 5 — Exécution | Refactoring complet | Suppression de `order-list-otoco` ; séquence BUY MARKET puis OCO SELL standalone |
| Phase 0 — Vérifications | Ajout | Routine idempotente de rattrapage des trades `protection_failed=True` |
| Enregistrement `trade_history.json` | Modifié | Ajout du champ `protection_failed`, chemins via `__PROJECT_DIR__` |

### Nouveau flux Phase 5 (après PR)

```
Avant :
  order-list-otoco (BUY LIMIT + OCO armé en attente)
    → TP/SL calculés sur le prix limit pré-trade
    → race condition si fill rapide ou wick

Après :
  1. order-market BUY (fill immédiat)
  2. actual_entry = cummulativeQuoteQty / executedQty  ← prix moyen pondéré réel
  3. Recalcul TP et SL sur actual_entry
  4. Si prix_post_fill >= actual_tp → fermeture market immédiate (close_reason="market_above_tp_at_fill")
  5. Sinon → order-list-oco SELL standalone (TP + SL sur prix réel)
  6. Si OCO échoue → protection_failed=True dans trade_history.json (reprise Phase 0)
```

### Routine de rattrapage Phase 0 (ajout)

Exécutée en tête de chaque cycle (dans un bloc `try/finally` pour ne pas bloquer le lock), elle :

1. Lit `trade_history.json` et filtre les entrées `status="open"` ET `protection_failed=True`.
2. Pour chaque trade non protégé — vérifie d'abord l'idempotence via `get-open-orders` (un OCO pourrait déjà exister).
3. Récupère le prix actuel via `get-symbol-price-ticker`.
4. Si `prix_actuel > tp_calc` : fermeture `order-market` SELL immédiate + mise à jour du trade (`status="closed"`, `close_reason="market_above_tp"`, PnL calculé).
5. Si `prix_actuel <= tp_calc` : replacement d'un OCO de rattrapage (`order-list-oco`) avec ajustement `LOT_SIZE` via `get-exchange-info`. Le `tp_oco` est forcé à `max(tp_calc, prix_actuel * 1.001)` pour garantir que le LIMIT_MAKER soit strictement au-dessus du marché.
6. Ecrit `trade_history.json` en fin de boucle (une seule écriture pour tous les trades traités).

## Décisions techniques notables

- **BUY MARKET plutôt que LIMIT** : élimine le risque de non-fill et simplifie la logique de protection. Contrepartie : le prix d'entrée n'est plus contrôlé ; le recalcul sur `actual_entry` compense en alignant TP/SL sur la réalité du fill.

- **`actual_entry = cummulativeQuoteQty / executedQty`** : gère correctement les fills partiels en plusieurs lots — la moyenne pondérée est plus précise qu'un simple prix unitaire.

- **Vérification `LOT_SIZE` avant l'OCO** : `get-exchange-info` est appelé pour extraire le `stepSize` du filtre `LOT_SIZE` et arrondir `actual_qty_oco = floor(actual_qty / stepSize) * stepSize`. Cela évite les erreurs `LOT_SIZE` de l'API Binance qui rejetaient auparavant certains OCOs.

- **Idempotence Phase 0** : avant tout remplacement, `get-open-orders` est interrogé pour détecter un OCO déjà actif (cas où la Phase 0 précédente a réussi à placer l'OCO mais a planté avant de persister `protection_failed=False`). Si un OCO est trouvé, seul le flag est corrigé, aucun nouvel ordre n'est envoyé.

- **`try/finally` dans Phase 0** : la routine est encapsulée pour garantir que le lock n'est pas bloqué si une exception survient pendant le rattrapage (ex. : API Binance injoignable).

- **Champ `protection_failed` rétrocompatible** : les trades existants dans `trade_history.json` sans ce champ retournent `None` pour `.get("protection_failed")` — le filtre `is True` les exclut correctement sans erreur.

- **`__PROJECT_DIR__` dans les chemins** : les `open("state/trade_history.json")` devenus des chemins relatifs dans le sous-processus Claude (cwd incertain) sont remplacés par `open("__PROJECT_DIR__/state/trade_history.json")`, substitué au boot comme les autres tokens du template.

## Impact sur l'architecture

| Composant | Avant | Après |
|---|---|---|
| Phase 5 : type d'ordre d'entrée | `order-list-otoco` (LIMIT atomique + OCO) | `order-market` BUY + `order-list-oco` SELL séparés |
| Phase 5 : base de calcul TP/SL | Prix limit pré-calculé avant execution | Prix de fill réel (`cummulativeQuoteQty / executedQty`) |
| Phase 0 : périmètre | Vérifications solde + daily loss + positions | + routine rattrapage `protection_failed` (idempotente) |
| `trade_history.json` : schéma | `entry_order_id` = ID du working OTOCO | `entry_order_id` = ID du BUY MARKET + nouveau champ `protection_failed` |
| Appels Binance CLI Phase 5 | 1 appel (`order-list-otoco`) | 3 à 4 appels (`order-market`, `get-symbol-price-ticker`, `get-exchange-info`, `order-list-oco`) |

Le diagramme des phases (`trade-phases.svg`) devra être mis à jour pour refléter la décomposition Phase 5 en deux ordres distincts (hors périmètre de cette PR).

La mention `order-list-otoco` dans la section 2.2 du SPEC (`binance-cli spot … order-list-otoco`) et dans le tableau de l'état persistant (section 5) est obsolète — corrigée dans cette mise à jour SPEC.

## Références CLAUDE.md respectées

- **Règle 1** (Telegram via `curl`) : toutes les notifications dans le TRADE_PROMPT utilisent le helper `tg()` qui shell-out vers curl — aucun `urllib` introduit.
- **Règle 2** (pas de secret hardcodé) : les tokens Telegram restent injectés via `__BOT_TOKEN__` / `__CHAT_ID__`.
- **Règle 3** (`PROJECT_DIR` dynamique) : les chemins `state/trade_history.json` dans le TRADE_PROMPT passent désormais tous par `__PROJECT_DIR__` (substitution au boot) — aucun chemin Mac absolu.
- **Règle 4** (stdout/stderr capturés) : aucune modification au mécanisme de capture de `run_trade_workflow()`.
- **Règle 5** (UTC interne, local à l'affichage) : les timestamps écrits dans `trade_history.json` (`exit_date`) sont en ISO UTC via `datetime.now(timezone.utc).isoformat()`.
