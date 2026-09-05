# PR #462 — Faire attendre un cycle tant qu'une chasse de sortie maker est en cours

> **Mergée le** : 2026-09-05
> **Branche** : `feat/issue-461-verrou-chasse-sortie`
> **Issue** : #461

## Contexte

Race condition critique : un cycle pose le verrou `state/agent_lock.json` pendant toute sa durée (médiane 418s, p90 609s), et si une chasse de sortie maker est en cours à ce moment-là, le thread `maker_exit_watcher` ne peut plus s'exécuter → la position reste sans stop au-delà du délai prévu (`maker_exit_timeout_seconds`, 600s).

La chasse de sortie maker (#390) est un mécanisme autonome via un thread non-daemon qui orchestre des ordres de sortie par limite progressive (maker exit path). Le verrou n'est pas réentrant (cf. `core/lock.py` : `acquire_lock()` / `release_lock()` sans notion de propriétaire), donc le watcher ne peut jamais libérer un verrou qui n'est pas le sien.

## Solution

**Faire attendre le cycle AVANT de poser le verrou**, tant qu'une chasse est en cours. Cela rend la sortie d'une position sans stop prioritaire sur le démarrage d'un cycle. L'attente est bornée à `maker_exit_timeout_seconds + 60s` (660s par défaut) pour ne jamais bloquer indéfiniment un cycle si le watcher est lui-même bloqué.

Ajout aussi d'une **garde d'ancienneté** : les ordres dont `placed_at` dépasse le seuil ne sont plus considérés comme une chasse active mais comme un résidu (signe d'une panne côté watcher : échec `query-orders` persistant, thread mort sur une exception non couverte) et génèrent une alerte Telegram ponctuelle, sans jamais retarder les cycles.

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Modification | Ajout de la fonction d'attente `_wait_for_maker_exit_chase()` et intégration dans `_run_workflow_cycle()` au-dessus du check de verrou |
| `binance-bot/core/maker_exit_watcher.py` | Modification | Traçage distinct du saut pour cause de verrou (`status: "locked"`) vs aucun travail à faire (`status: "ok"`) |
| `tests/test_maker_exit_watcher.py` | Modification | Ajout de tests validant que le watcher ne touche jamais au verrou d'un cycle |
| `tests/test_runner_maker_exit_wait.py` | Ajoutée | Suite de 11 tests : attente simple, bornage, garde d'ancienneté, alerte résidu, intégration |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_wait_for_maker_exit_chase()` | Ajoutée (runner.py:131) | Boucle d'attente : lit `state/maker_exit_pending_orders.json` toutes les `maker_tick_seconds`, retourne dès que la liste est vide ou que la borne est atteinte. Journalise entrée, résolution et sortie par borne. |
| `_active_maker_exit_orders()` | Ajoutée (runner.py:110) | Filtre les ordres en attente en ne retenant que les actifs (`placed_at` récent) ; alerte Telegram une seule fois par résidu détecté. Traite les `placed_at` malformés comme actifs par prudence. |
| `_maker_exit_stale_alert()` | Ajoutée (runner.py:94) | Alerte ponctuelle d'un ordre résidu (bloqué côté watcher). Maintient un set `_STALE_MAKER_EXIT_ALERTED_TXIDS` pour éviter de re-alerter. |
| `_run_workflow_cycle()` | Modifiée (runner.py:170) | Appelle `_wait_for_maker_exit_chase()` ligne 190, **avant** le check `is_locked()` et l'`acquire_lock()`. Impact appliqué à `run_trade_workflow()` et `run_position_check_workflow()` via ce point unique. |
| `_maker_exit_watcher_tick()` | Modifiée (maker_exit_watcher.py:414) | Écrit `status: "locked"` au lieu de "ok" quand le verrou est posé (au démarrage et en itération par-ordre), pour distinguer "je n'ai pas pu m'exécuter" de "rien à faire". Aide au debug : la courbe d'état du watcher devient traçable dans `state/maker_exit_watcher_state.json`. |

## Décisions techniques notables

- **Appel au-dessus du verrou** : placer `_wait_for_maker_exit_chase()` AVANT `acquire_lock()` dans `_run_workflow_cycle()` élimine le besoin d'introduire une notion de propriétaire du verrou (qui complexifierait la sémantique non réentrante existante). Un watcher bloqué par un cycle précédent ne peut donc pas libérer ce cycle.
  
- **Bornage par marge** : `maker_exit_timeout_seconds + 60s` plutôt que par timeout strict. La marge de 60s couvre les faux positifs (ordre juste à la limite d'expiration) et rend l'attente gracieuse : si le watcher est vraiment coincé, on démarre le cycle plutôt que d'attendre indéfiniment. Sans cette garde, un ordre bloqué persistant (echec query-orders, thread watcher mort) aurait retardé **chaque cycle** de manière silencieuse.

- **Garde d'ancienneté avec alerte** : les résidus (vieux ordres) ne retardent jamais mais génèrent une alerte Telegram unique par `txid`. Cela signale un incident côté watcher (le thread s'est-il arrêté ? query-orders en boucle d'erreur ?) sans bloquer le trading.

- **Poll via `maker_tick_seconds`** : réutilisation de la cadence existante du watcher plutôt qu'une nouvelle constante (économie de paramètre de config).

- **Tracing distinct (locked/ok)** : le champ `status` dans `state/maker_exit_watcher_state.json` passe de "ok" à "locked" quand le verrou bloque l'exécution du watcher. Permet de diagnostiquer les causes de retard de cycle dans `daemon.log` : `[Cycle Wait]` vs `[Maker Exit Watcher]` avec status.

## Impact sur l'architecture

**Hiérarchie des priorités explicitement invoquée** : une position sans stop (situation de crise du watcher) prime désormais sur le démarrage d'un cycle. Avant, c'était une race — le timing du polling Telegram déterminait qui "gagnait". Maintenant, c'est déterministe.

**Deux workflows affectés** :
- `run_trade_workflow()` (cycle 4h) → attendre les chasses avant de trader
- `run_position_check_workflow()` (cycle horaire) → attendre les chasses avant la gestion position

Cela garantit qu'aucun cycle ne démarre tant qu'une sortie d'urgence est en cours, même si c'est moins fréquent que prévu (borne atteinte régulièrement).

**Impact sur les logs** : `daemon.log` affiche maintenant une trace `[Cycle Wait]` au démarrage retardé + la durée d'attente + la sortie par borne atteinte (warn level si la borne s'est déclenchée). Un utilisateur lisant les logs verra clairement : "Cycle 20260905_040500 retardé de 42s pour laisser la chasse se résoudre".

## Références CLAUDE.md respectées

- **Règle 2** (PROJECT_DIR dynamique) : chemin absolu recalculé depuis chaque fichier `orchestration/runner.py` via `from core.env import PROJECT_DIR`
- **Règle 6** (UTC interne) : tous les timestamps `placed_at` en ISO format UTC ; différence d'âge calculée en UTC
- **Règle 7** (Auto-scheduler dans main_loop) : aucune modification du scheduler, l'attente s'applique APRÈS son déclenchement, avant l'exécution du cycle
- **Minimalisme** : 89 lignes ajoutées = 3 fonctions + 1 variable module-level + appel unique dans `_run_workflow_cycle()` ; pas d'abstraction précédant.

## Tests

Suite complète : 466 tests passent (+11 nouveaux).

- **No chase** : `TestNoChaseInProgressNeverDelays` — aucune chasse, pas de retard, pas de sleep
- **Chase resolved** : `TestChaseInProgressDelaysCycleStart` — attente jusqu'à vidage de la liste, puis démarrage
- **Bounded wait** : `TestWaitIsBoundedByTimeoutPlusMargin` — au-delà de borne, démarrage malgré chasse toujours présente
- **Stale order ignored** : `TestStaleOrderDoesNotDelayCycle` — ordre résidu (trop vieux) ne retarde jamais, mais alerte
- **Alert once per order** : `TestStaleOrderAlertedOnlyOnce` — résidu mélangé à chasse active → alerte une seule fois
- **Lock integration** : `TestRunWorkflowCycleWaitsBeforeLockCheck` — `_wait_for_maker_exit_chase()` appelée AVANT `is_locked()` et `acquire_lock()`
- **Traced wait** : `TestWaitIsTraced` — logs présents en info (entrée/résolution) et warning (borne atteinte)
- **Watcher lock safety** : `TestLockedTickNeverTouchesWatcherLock`, `TestMidLoopLockDefers` — watcher n'acquiert ni ne relâche jamais le verrou du cycle, reporte l'ordre et marque status "locked"

Syntaxe Python : ✅ `python -c "import ast; ast.parse(open('binance-bot/orchestration/runner.py').read())"` et idem pour `maker_exit_watcher.py`

Linting : ✅ `ruff check` sur fichiers touchés — clean (14 erreurs préexistantes ailleurs, non liées)
