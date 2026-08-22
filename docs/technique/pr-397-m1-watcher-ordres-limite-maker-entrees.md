# PR #397 — [M1] Watcher d'ordres limite maker sur les entrées (stratégie B)

> **Mergée le** : 2026-08-22
> **Branche** : `feat/issue-388-maker-entry-watcher`
> **Issues** : #388

## Contexte

L'objectif du ticket est de réduire les frais de trading en utilisant des ordres LIMIT post-only (maker) au lieu de BUY MARKET (taker) lors des entrées de position. Cela permet d'économiser ~0.30% sur les frais Kraken par trade (maker 0.30% vs taker 0.60% au palier du compte), soit ~27,56 USDC estimés sur la période mesurée contre un PnL net total de +11,11 USDC.

La stratégie demande un nouveau composant : un watcher asynchrone qui ajuste les ordres LIMIT via `order amend` (jamais annuler/replacer) jusqu'à exécution ou repli selon trois bornes priorisées : budget de concession (0.30%), invalidation du signal via drift prix, ou timeout (60 min).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/maker_watcher.py` | Création (426 lignes) | Nouveau daemon thread pour gérer les ordres maker limites en attente |
| `binance-bot/core/phases/phase5_execution.py` | Modification | Remplace BUY MARKET par ordre LIMIT post-only quand `maker_entry_enabled=true` |
| `binance-bot/core/trade_helpers.py` | Modification | Extension de `maker_or_taker_from_ordertype()` et helpers `load_maker_pending_orders()` / `save_maker_pending_orders()` |
| `binance-bot/core/phases/phase8_cycle_log.py` | Modification | Log des détails du watcher dans le cycle (status, error) |
| `binance-bot/webhook_server.py` | Modification | Lance le thread daemon `maker_watcher.maker_watcher_loop()` au startup |
| `config.json` | Modification | Ajout 4 clés de config ; suppression de `order_type` (inutilisée) |
| `prompts/phases/phase5_execution.txt` et `phases6_8.txt` | Modification | Mise à jour des prompts pour refléter le nouveau flux |
| `tests/` | Création/modification | 13 nouveaux tests + 117 pré-existants inchangés : `test_maker_watcher.py` (8 tests), `test_phase5_execution_maker.py` (3 tests), `test_trade_helpers.py` (+4), `test_webhook_server_routing.py` (mocker le thread) |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `maker_watcher_loop()` | Ajoutée | Boucle principale du watcher : tick à intervalle configurable, gère les ordres limites maker en attente |
| `_maker_watcher_tick()` | Ajoutée | Logique par tick : query statut ordres, ajuste via `amend`, ou repli au marché selon bornes |
| `_register_open_position()` | Ajoutée | Enregistre une position remplie (maker ou taker) dans l'historique avec SL |
| `_fallback_market_buy()` | Ajoutée | Repli BUY MARKET si le budget maker est épuisé |
| `_cancel_and_resolve()` | Ajoutée | Annule un ordre et résout le remplissage partiel éventuel |
| `_handle_closed_order()` | Ajoutée | Traite un ordre rempli (status "closed") |
| `_handle_externally_canceled()` | Ajoutée | Traite un ordre annulé de façon inattendue (hors de notre fait) |
| `_handle_invalidated_price()` | Ajoutée | Traite un ordre invalidé par le drift prix (`price_deviation_max_pct`) — abandon sans repli marché |
| `_handle_timeout_or_concession()` | Ajoutée | Traite dépassement de budget ou timeout — repli BUY MARKET |
| `_place_maker_entry_order()` | Modifiée (phase5) | Nouvelle fonction pour poser l'ordre LIMIT post-only au bid avec retry |
| `maker_or_taker_from_ordertype()` | Modifiée (trade_helpers) | Étend le support : `post_only=True` sur `limit` → `"maker"` |
| `load_maker_pending_orders()` | Ajoutée (trade_helpers) | Charge `state/maker_pending_orders.json` |
| `save_maker_pending_orders()` | Ajoutée (trade_helpers) | Sauvegarde `state/maker_pending_orders.json` de façon atomique |

## Décisions techniques notables

1. **Arbre de décision hiérarchisé** : Les trois bornes de repli sont priorisées : (1) invalidation prix → abandon (signal mort), (2) budget/timeout → repli marché (objectif non atteint, sauver la position), (3) remplissage partiel → enregistrement sans complétion.

2. **Utilisation de `amend` au lieu d'annuler/replacer** : Préserve la priorité de l'ordre dans le carnet. Kraken remplace atomiquement le prix et quantité sans casser la position.

3. **Rejet post-only non-fatal** : Kraken répond `200 OK` avec un champ `error` dans la réponse JSON — géré explicitement plutôt que de compter sur une exception, sinon le prix aurait été mis à jour localement alors que l'amend avait réellement échoué.

4. **Exécution partielle sans complétion taker** : Si le maker se remplit partiellement puis que le budget/timeout arrive, le reliquat n'est PAS complété par un BUY MARKET immédiat — évite de mélanger deux prix d'entrée dans une même position. Le SL protège la quantité remplie.

5. **Suppression de `order_type`** : Clé config jamais lue par le code (vérifiée par grep). Remplacée par l'interrupteur explicite `maker_entry_enabled` qui contrôle directement le flux phase5.

6. **État persistant du watcher** : `state/maker_watcher_state.json` enregistre télémétrie (ticks, fills, fallbacks, dernier tick, status, erreur) sur le même patron que `tp_watcher_state.json`, permettant un `/status` enrichi.

## Impact sur l'architecture

**Avant** : Phase 5 (exécution) → BUY MARKET → enregistrement direct → fin de cycle
**Après** : Phase 5 (exécution) → LIMIT post-only → enregistrement en attente → daemon watcher → remplissage/repli/abandon asynchrone

La Phase 5 reste synchrone et rapide (pose l'ordre, enregistre en `maker_pending_orders.json`, notifie en Telegram, passe au coin suivant). Le watcher tourne en parallèle, vérifie l'état toutes les 20s (configurable), ajuste et enregistre les positions au fur et à mesure.

Le changement est **isolé à la couche d'entrée** : une fois la position ouverte (que ce soit via maker ou taker), les phases 0 (clôture), 6 (OCO), 7 (log), 8 (cycle_log) restent identiques. Seul le champ `maker_or_taker` diffère dans l'historique (impact lecture dans `/perf`, nécessaire pour tracer l'économie réelle de frais).

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : tous les chemins utilisent `os.path.join(PROJECT_DIR, ...)` — compatible Mac et VPS.
- **Règle 3 (agent `binance-dev`)** : modifié via branche `feat/issue-388-*` et PR standard.
- **Règle 4 (Telegram via curl)** : `send_telegram()` continue d'utiliser curl, pas urllib.
- **Règle 5 (stdout/stderr capturés)** : les logs du watcher (erreurs, transitions) vont dans `loguru` et `daemon.log`, accessible via SSH VPS.
- **Règle 6 (UTC interne, local affichage)** : timestamps stockés en UTC avec suffixe `Z`, affichage notif en heure locale via `fmt_local()` au besoin.
- **Règle 7 (auto-scheduler)** : le watcher s'ajoute en tant que daemon thread dans la loop de polling Telegram — pas de cron séparé.

## Tests

- **Test coverage** : 130/130 tests PASS (117 pré-existants inchangés + 13 nouveaux)
  - `test_maker_watcher.py` (8 tests) : tick, amend, budget épuisé, timeout, prix invalidé, cancel externe
  - `test_phase5_execution_maker.py` (3 tests) : pose limite, repli, exécution partielle
  - `test_trade_helpers.py` (+4) : helpers load/save `maker_pending_orders`
  - `test_webhook_server_routing.py` (mocker) : le thread daemon est mocké en tests unitaires
  
- **Linting** : `ruff check` propre sur tous les fichiers modifiés/créés
- **Syntaxe** : `python -c "import ast; ast.parse(...)"` → 0 sur tous les `.py` touchés

