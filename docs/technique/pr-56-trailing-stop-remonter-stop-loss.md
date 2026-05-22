# PR #56 — [M1] Phase 0 — Trailing stop : remonter le stop-loss si le prix a progressé

> **Mergée le** : 2026-05-22
> **Branche** : `feat/issue-55-trailing-stop-remonter-stop-loss`
> **Issues** : #55

## Contexte

Après l'introduction en PR #39 du couple BUY MARKET + OCO SELL, les positions ouvertes étaient protégées par un stop fixe calculé au moment de l'entrée. Si le prix progressait significativement, le stop restait à son niveau initial, exposant l'agent à un retour en arrière sans avoir sécurisé les gains. La PR #56 ajoute une routine de trailing stop dans Phase 0 du `_TRADE_PROMPT_TEMPLATE` : à chaque cycle (toutes les 4h ou sur déclenchement `/trade`), le stop-loss est remonté proportionnellement à la progression du prix, garantissant que chaque trade sorti en profit dépasse au moins la distance de trailing accumulée.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification | Ajout du bloc `# --- TRAILING STOP ---` dans `_TRADE_PROMPT_TEMPLATE` (lignes :264–365), exécuté dans le sous-processus Claude en Phase 0, après la routine `protection_failed` |

### Fonctions ajoutées / modifiées

| Fonction / Bloc | Action | Description |
|---|---|---|
| Bloc trailing stop (TRADE_PROMPT:264–365) | Ajouté | Routine Phase 0 dans le prompt : pour chaque position `open` avec `order_list_id` non null, récupère le prix actuel via `binance-cli ticker`, calcule le nouveau stop candidate (`prix - trail_dist`), met à jour uniquement si la progression dépasse 20% de la distance originale et que le stop reste à plus de 2% du prix actuel ; annule l'OCO existant, recalcule le TP (`max(original_tp, prix + 3 × trail_dist)`), replace un nouvel OCO avec arrondis `tick_size`/`lot_size`, met à jour `trade_history.json` et notifie Telegram |

## Décisions techniques notables

- **Seuil de déclenchement à 20% de `trail_dist`** : évite les mises à jour parasites sur de micro-progressions qui ne justifient pas d'annuler et de recréer un OCO (coût en appels API + risque d'interruption de la protection). Le seuil de 20% correspond à une avance significative avant de remonter le stop.

- **Garde-fou « stop à moins de 2% du prix »** (`_new_stop >= _price * 0.98`) : empêche de poser un stop si proche du cours que le moindre spread ou wick l'activerait immédiatement. Assure une marge minimale de respiration à la position.

- **TP réévalué à chaque remontée** (`max(original_tp, prix + 3 × trail_dist)`) : le TP ne peut que monter, jamais descendre. La logique applique le même ratio reward/risk que lors de l'entrée (3×) calculé sur le prix courant, ce qui permet d'exploiter la continuation de tendance sans plafonner le gain.

- **`binance-cli ticker` sans `--profile`** utilisé pour le prix courant, à distinguer de `binance-cli spot get-symbol-price-ticker --profile agent-profile` utilisé ailleurs dans le prompt. La note dans le PR body signale une potentielle incompatibilité selon la version de `binance-cli` déployée — point de vigilance en cas de mise à jour de l'outil.

- **Annulation OCO en try/except avec skip** : si l'annulation échoue (OCO déjà déclenché entre deux cycles par exemple), la routine loggue l'erreur via Telegram et passe au trade suivant sans interrompre les autres positions. Évite qu'une position devenue invalide bloque la mise à jour des positions saines.

- **Résumé de synthèse Telegram** (`_ts_updates`) : un message récapitulatif groupé est envoyé uniquement si au moins un stop a été remonté, évitant les notifications parasites sur les cycles sans mouvement.

## Impact sur l'architecture

La routine s'insère dans Phase 0 du `_TRADE_PROMPT_TEMPLATE`, juste après le bloc `protection_failed` existant. Elle s'exécute donc dans le sous-processus Claude à chaque cycle, avant le scan marché (Phase 1). L'état persistant `state/trade_history.json` est modifié en place (mise à jour des champs `stop_price`, `tp_price`, `order_list_id`, `stop_order_id`, `tp_order_id` pour chaque position trailée). Aucun nouveau fichier d'état n'est introduit. La logique de polling Telegram, le scheduler 4h et `run_trade_workflow()` côté `webhook_server.py` sont inchangés — le trailing stop est entièrement porté par le prompt injecté dans Claude.

## Références CLAUDE.md respectées

- **Règle 1 (Telegram via curl)** : les notifications trailing stop (`tg()`) utilisent le helper curl défini en tête du prompt, conforme à la règle d'exclusion de `urllib`.
- **Règle 3 (`PROJECT_DIR` dynamique)** : la lecture/écriture de `trade_history.json` dans la routine utilise `__PROJECT_DIR__` (substitué à chaque cycle par `run_trade_workflow()`), pas de chemin hardcodé.
- **Règle 4 (stdout/stderr toujours capturés)** : la routine s'exécute dans le sous-processus Claude dont tous les outputs sont capturés dans `logs/stdout/cycle_<id>.log` et `logs/stderr/cycle_<id>.log`.
