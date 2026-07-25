# PR #373 — [M3] Tests d'intégration : phases 0 et 1

> **Mergée le** : 2026-07-25
> **Branche** : `feat/issue-366-tests-integration-phases-0-1`
> **Issues** : #366

## Contexte

La suite de tests du projet manquait de couverture réelle sur les décisions automatiques des **phases 0 et 1** du cycle de trading. La phase 0 gère des décisions critiques (snapshot des positions, clôture au profit cible, retry OCO en cas d'échec du stop-loss, recalcul du trailing stop), et la phase 1 filtre l'univers tradable par le volume et mappings d'échanges. 

Cette PR complète le harness de test (établi par #372) en ajoutant **5 nouveaux fichiers de test d'intégration** couvrant ces phases, et en étendant le test du trailing stop avec des cas d'intégration réels (montée du prix, récalcul du stop, skips conditionnels).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `tests/fixtures/test_harness.py` | Création | Harness partagé : factorisation des patterns de test (fake_open, gestion scénario kraken, exec script via importlib) |
| `tests/test_phase0_snapshot.py` | Création | Tests d'intégration pour phase0_snapshot.py — snapshot des positions ouvertes, distinction bot/manuel, calcul P&L |
| `tests/test_phase0_profit.py` | Création | Tests d'intégration pour phase0_profit.py — clôture auto si profit latent >= seuil `min_profit_pct_take` |
| `tests/test_phase0_oco_retry.py` | Création | Tests d'intégration pour phase0_oco_retry.py — idempotence SL actif, force-close au-dessus TP, retry normal, fallback épuisement |
| `tests/test_phase1_scan.py` | Création | Tests d'intégration pour phase1_scan.py — filtre `min_volume_usdc`, inclusion forcée `portfolio_coins`, mapping Kraken→TradingView (XBT→BTC, XDG→DOGE) |
| `tests/test_phase0_trailing_stop.py` | Modification (+120/-4) | Extension des tests unitaires (_round_price, _round_qty) avec 4 tests d'intégration sur le recalcul réel du trailing stop : montée suffisante du prix, skip si nouveau stop trop proche du stop courant, skip si trop proche du prix, skip si position sans `sl_order_txid` |

### Fonctions testées (couverture par phase)

| Fonction / Domaine | Phase | Fichier de test | Description |
|---|---|---|---|
| Snapshot des positions | 0 | `test_phase0_snapshot.py` | Lecture trade_history.json, calcul P&L latent, distinction position bot vs manuelle, notification Telegram |
| Clôture au profit cible | 0 | `test_phase0_profit.py` | Vérification `profit_latent >= min_profit_pct_take`, ordre SELL market, mise à jour status/close_reason/exit_price/pnl_usdc |
| Retry OCO | 0 | `test_phase0_oco_retry.py` | Idempotence (SL déjà actif → pas de nouvel ordre), force-close si prix > TP, retry si prix < TP + retry_count < max, fallback si retry_count >= max |
| Recalcul trailing stop | 0 | `test_phase0_trailing_stop.py` | Prix suffisamment élevé → annulation ancien SL + pose nouveau + mise à jour `stop_price`, skips conditionnels (nouveau stop trop proche du courant ou du prix) |
| Filtre volume 24h | 1 | `test_phase1_scan.py` | Exclusion des paires avec volume < `min_volume_usdc`, inclusion forcée des `portfolio_coins` malgré un volume bas |
| Mapping Kraken→TradingView | 1 | `test_phase1_scan.py` | Remapping des symboles Kraken internes vers TradingView : XBT→BTC, XDG→DOGE, autres passent inchangés |

## Décisions techniques notables

### Harness partagé (`tests/fixtures/test_harness.py`)

- **Interception ciblée de builtins.open** : uniquement `state/trade_history.json` (lue par le script de phase) est redirigée vers un StringIO en mémoire — les écritures de sortie (`/tmp/cycle_*_output.json`) passent par le vrai système de fichiers. Cela évite toute pollution du vrai fichier d'état.
- **Gestion automatique du scénario kraken** : `write_kraken_scenario()` utilise `tempfile.NamedTemporaryFile` pour générer des chemins imprévisibles et garantir l'isolation entre tests. Les chemins `/tmp/` des **scripts de phase** (input/output) restent contrôlés par le script lui-même (non modifiables ici sans exécution complète du script).
- **Exécution via importlib** : `exec_phase_script()` charge le script comme un module distinct à chaque invocation, positionne `sys.argv = [nom_script, cycle_id]`, capture les appels `SystemExit`, puis restaure `sys.argv`. Cela permet l'exécution sans modifier l'état global du test runner.

### Mocking multidimensionnel

- `core.trade_helpers.tg()` (notifications Telegram) : mockée dans **tous** les tests (aucun appel réseau réel)
- `core.trade_helpers._EXCHANGE_CLI` : pointée vers le stub `tests/fixtures/fake_kraken.py` (mock local de kraken-cli)
- `core.trade_helpers._save_trade_history_atomic()` : mockée pour vérifier que les mises à jour d'état sont bien tentées, et capturer l'état enregistré pour assertion
- `core.trade_helpers._load_config()` : mockée pour injecter des configs testables (`min_profit_pct_take`, `max_oco_retry`, `min_volume_usdc`, `portfolio_coins`)
- `core.trade_helpers.log_phase0_event()` : mockée pour éviter les écritures fichier inattendues

### Cas d'intégration distincts pour les skips du trailing stop

Le test distingue trois motifs de "skip" du recalcul du trailing stop :
1. **Nouveau stop trop proche du stop courant** (< 20% de la distance trail) → pas d'annulation de l'ordre, pas d'ordre nouveau
2. **Nouveau stop trop proche du prix courant** (>= 98% du prix) → protection inefficace, skip
3. **Position sans `sl_order_txid`** (pas de SL actif) → position non concernée par le trailing stop

Chaque cas bénéficie d'un test indépendant qui valide l'invariant : `mock_save.assert_not_called()` et `mock_tg.assert_not_called()`.

## Impact sur l'architecture

**Changement isolé, pas d'impact sur l'architecture globale.** Les tests ne modifient ni les scripts de phase (`binance-bot/core/phases/`), ni le webhook_server, ni l'orchestration. Ils fournissent uniquement une **couverture de vérification** pour les décisions existantes. 

- **Stabilité** : les 5 fichiers de test + 1 harness relancent la suite `python -m unittest discover tests/` (47 tests, auparavant 42), tous passants.
- **Maintenabilité** : le harness factorisant 150 lignes de duplication, les futurs tests de phases additionnelles (2, 3, 4, 5, 6) réutiliseront les mêmes helpers.

## Références CLAUDE.md respectées

- **Règle 1 — venv .venv Python 3.11 + git-perso** : tous les tests s'exécutent via `python -m unittest`, qui hérite du venv activé. Les scripts de phase s'exécutent via `importlib`, isolés du contexte du test runner.
- **Règle 2 — PROJECT_DIR dynamique** : le harness calcule `PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` à partir du chemin du harness lui-même (sous `tests/fixtures/`), **pas en dur**. Les chemins des scripts de phase sont dérivés à partir de PROJECT_DIR.
- **Règle 3 — aucune modification directe sur main** : tous les tests ont été implémentés via l'agent `binance-dev` sur une branche `feat/issue-366-tests-integration-phases-0-1`, qui s'ouvre via PR et se merge après review (cet historique n'est visible qu'en git).
- **Règle 4 — secrets et .env** : aucun secret hardcodé. Les tests mockent `_load_config()` pour injecter des configs fictives.
- **Règle 5 — appels Telegram via curl** : les tests mockent **entièrement** `tg()` — aucun appel curl réel n'est généré.

## Ligne de changement clé au changelog technique

> Tests d'intégration PR #366 : phases 0 (snapshot, profit, OCO retry, trailing stop) et 1 (volume filter, portfolio_coins, Kraken→TV mapping) avec harness partagé factorisant fake_open/scénario kraken/exec via importlib.
