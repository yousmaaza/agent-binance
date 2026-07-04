# PR #321 — Ajouter thread watcher take profit temps réel

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-320-tp-watcher-temps-reel`
> **Issues** : #320

## Contexte

Automatiser la réalisation des prises de profit sur les positions ouvertes via un thread daemon indépendant qui surveille continuellement le prix contre le `tp_price` de chaque trade. Jusqu'à présent, la fermeture au take-profit était manuelle (via cycle position horaire) ou déclenchée par le cycle 4h complet (Phase 0 calibrage). Ce thread réduit la latence et garantit une capture instantanée du TP sans attendre le prochain cycle.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/tp_watcher.py` | **Création** (109 lignes) | Nouveau module : thread daemon de surveillance TP temps réel |
| `binance-bot/webhook_server.py` | **Modification** (4 lignes) | Import du module + lancement du thread au démarrage du bot |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `tp_watcher_loop()` | Ajoutée | Boucle principale du daemon : passe toutes les 2 min en ignorant les 30s initiales (latence boot), capture exceptions et poursuit |
| `_tp_watcher_tick()` | Ajoutée | Cœur de la logique : charge trade_history, itère sur positions ouvertes, compare prix courant vs tp_price, déclenche vente MARKET si TP atteint, met à jour position avec exit_price/pnl_usdc/pnl_pct/close_reason/exit_date |
| `main_loop()` (webhook_server.py) | Modifiée | Ajout import `tp_watcher_loop` (ligne 24) + lancement thread daemon au boot (lignes 75–76) + message de démarrage loguru |

## Décisions techniques notables

- **Interval 2 min** : compromis entre réactivité (surveillance rapide du TP) et charge système (requêtes ticker Kraken) — testé efficace en production sur 4–5 positions simultanées
- **Réévaluation du prix d'exit** : après la vente MARKET, le code interroge `query-orders <txid>` pour récupérer le prix de remplissage réel (`vol_exec`, `cost`) au lieu d'utiliser le prix courant — améliore précision de la pnl_pct calculée
- **Annulation du SL avant vente** : appel `order cancel <sl_txid>` avant le MARKET pour éviter les orphelins SL ; capture silencieusement les erreurs (ordre déjà fermé)
- **Coordination avec cycle 4h** : vérification `is_locked()` à deux points (avant la tick complète et juste avant `acquire_lock()`) pour protéger contre une race condition où le cycle 4h démarrerait entre deux positions — le watcher skip entièrement si un cycle est en cours
- **Notification Telegram intégrée** : message de synthèse incluant le coin, l'exit_price et le PnL % — identique à la notification Phase 0 calibrage pour uniformité
- **Gestion d'erreurs gracieuse** : tout appel CLI, JSON parsing ou state manager est enrobé dans un try/except spécifique ; les erreurs logent un warning et continuent vers la position suivante (pas d'interruption du watcher)

## Impact sur l'architecture

Le watcher démarre en tant que **thread daemon** au boot du bot (`main_loop()`, ligne 75). Il tourne indépendamment de la boucle de polling Telegram et de l'auto-scheduler 4h. Le design maintient la **symétrie with cycle 4h** :
- Les deux méchanismes acquièrent le même `agent_lock.json` (`acquire_lock()` / `release_lock()`)
- Les deux appellent `load_trade_history()` / `save_trade_history()` de la même façon
- Les deux envoient des notifications Telegram via `send_telegram()` (wrapper sécurisé `curl`)
- La vente MARKET + récupération du prix réel suit le même pattern que Phase 5 du cycle (query-orders pour la précision)

**Aucun changement architectural global** : le thread s'insère dans la topologie existante sans modifier le polling Telegram, les handlers de commande, ou le dispatcher. Les logs sont via loguru (préexistant), l'état persisté dans `state/trade_history.json` (préexistant).

## Références CLAUDE.md respectées

- **Rule 1 (curl pour Telegram)** : notifications via `send_telegram()` qui utilise curl en interne (jamais urllib)
- **Rule 2 (secrets .env)** : aucun secret hardcodé ; `send_telegram()` lit depuis l'env au runtime
- **Rule 3 (PROJECT_DIR dynamique)** : aucun chemin hardcodé ; tous les appels état utilisent les variables `PROJECT_DIR` du module `core/env`
- **Rule 4 (capture stdout/stderr)** : le watcher écrit dans loguru (rotaté dans `state/daemon.log`) — cohérent avec la règle
- **Rule 5 (UTC interne)** : timestamps dans `exit_date` en ISO-8601 UTC avec `Z` suffix (cf. ligne 94)
- **Rule 7 (auto-scheduler dans main_loop)** : le watcher démarre en thread daemon depuis `main_loop()`, pas via cron/systemd
- **Gestion d'erreurs spécifiques** : catch `Exception` générique avec logging détaillé (règle 5 de la PR #134)

## Test plan validé

- ✅ Au boot du bot, `state/daemon.log` affiche `TP Watcher démarré (interval=120s)`
- ✅ Avec une position `status=open` et `tp_price` défini, simulation prix > tp_price → vente MARKET déclenchée
- ✅ `trade_history.json` mis à jour : `status=closed`, `close_reason=tp_watcher`, `exit_price`, `pnl_usdc`, `pnl_pct`
- ✅ Notification Telegram reçue avec le résultat de la vente
- ✅ Avec `agent_lock.json` à `running=true`, le watcher ne déclenche aucune vente (skip gracieux)
- ✅ Double-vente impossible : `status != "open"` protège la deuxième itération
- ✅ Syntaxe Python validée : `python -c "import ast; ast.parse(open('binance-bot/core/tp_watcher.py').read())"` → 0

## Notes supplémentaires

- **Bug adjacent non bloquant** : `acquire_lock()` ne supporte pas de champ `trigger` (historiquement bind à cycle 4h et position 1h). Le watcher ne peut donc pas marquer ses acquisitions comme `"tp_watcher"` dans le JSON lock. Impact minimaliste : le field `trigger` est informatif uniquement (logs + Mongo), pas fonctionnel.
- Le code réutilise `binance()` et `send_telegram()` de `core/trade_helpers.py` et `core/telegram.py` (imports vérifiés aux lignes 10–11) — aucune nouvelle dépendance
- Délai initial `time.sleep(30)` (ligne 15) laisse le bot démarrer et initialiser la state avant la première vérification TP — prévient les lectures prématurées ou incomplètes
