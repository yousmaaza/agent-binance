# PR #375 — [M5] Tests d'intégration : phases 6/7/8 + routing webhook_server.py

> **Mergée le** : 2026-07-26
> **Branche** : `feat/issue-368-tests-integration-phases-6-7-8-webhook`
> **Issues** : #368

## Contexte

Complète la suite de tests d'intégration lancée en PR #373 (phases 0 et 1), PR #374 (phases 4 et 5), et PR #372 (harness + conventions). Ajoute la couverture pour :
- **Phase 6** (next_cycle) : calcul du prochain slot 4h UTC (gestion des transitions jour/nuit, cas limite sur frontière de slot)
- **Phase 7** (mongo + heartbeats) : persistance MongoDB des cycles, détection et récupération de phases manquantes
- **Phase 8** (cycle_log) : append JSONL avec rotation exacte à 90 lignes, exécution du script bash de git commit/push
- **Routing webhook_server.py** : validation du dispatch correct des 4 commandes principales (/status, /trade, /perf, /reset) et comportement en cas de commande inconnue

Ce ticket clôt la spec `docs/superpowers/specs/2026-07-24-tests-integration-design.md` : les 5 tickets de découpage (refactor Phase 5, harness, phases 0/1, phases 4/5, **phases 6/7/8 + routing**) sont désormais tous complétés.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `tests/test_phase6_next_cycle.py` | Ajout (97 lignes) | Tests pour le calcul du prochain slot 4h UTC : avant/après un slot, à cheval sur minuit, cas limite exactement sur la frontière d'un slot |
| `tests/test_phase7_mongo.py` | Ajout (109 lignes) | Tests pour phase7_mongo.py : MONGODB_URI absent → skip sans connexion, écriture réussie → upsert avec bon document, erreur Mongo → notification tg() + exit code 1 |
| `tests/test_phase7_hb_check.py` | Ajout (105 lignes) | Tests pour phase7_hb_check.py : détection de heartbeats manquants (toutes phases présentes, une phase manquante avec recovery + notif, fichier jsonl absent) |
| `tests/test_phase8_cycle_log.py` | Ajout (161 lignes) | Tests pour phase8_cycle_log.py : append JSONL, rotation exacte à 90 lignes (89→90 sans rotation, 90→91 avec drop de la plus ancienne), subprocess.run mocké pour ne pas exécuter git réellement |
| `tests/test_webhook_server_routing.py` | Ajout (141 lignes) | Tests pour routing des commandes dans webhook_server.py::main_loop() : /status, /trade, /perf, /reset avec I/O mocks (tg_post, get_offset, send_telegram, run_* handlers) et threading.Thread remplacé par exécution synchrone |

### Fonctions testées

| Fonction / Module | Action | Description |
|---|---|---|
| `phase6_next_cycle.py` | Testé | Calcule le prochain slot 4h UTC (00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC) à partir de l'heure courante, gère les transitions entre jours |
| `phase7_mongo.py` | Testé | Connecte MongoDB (si MONGODB_URI présent), upsert le document cycle, notifie tg() en cas d'erreur, exit code 0 (succès) ou 1 (erreur) |
| `phase7_hb_check.py` | Testé | Lit logs/cycle_{CYCLE_ID}_phases.jsonl, détecte phases 0-6 manquantes, récupère via hb(status="recovered"), notifie tg() si phases manquantes |
| `phase8_cycle_log.py` | Testé | Append une ligne JSONL à state/cycle_log.jsonl, rotation à 90 lignes max (drop la plus ancienne si dépassé), génère et exécute script bash git commit/push (subprocess mocké) |
| `webhook_server.py::main_loop()` | Testé | Dispatch de commandes Telegram : /status → run_status(), /trade → run_trade_workflow(trigger="manual"), /perf → run_perf(), /reset → release_lock(), commande inconnue → aide |
| `core.trade_helpers.tg()` | Mocké | Aucun appel Telegram réel en test |
| `core.heartbeat.hb()` | Mocké partiellement | Laissé exécuter réellement pour phase7_hb_check, génère les fichiers jsonl avec cycle_id unique |

## Décisions techniques notables

- **Phase 6 : gestion du fuseau** : le test gèle l'heure UTC via un patch de `datetime.datetime.now()` avec une sous-classe custom. Le formatage final `astimezone()` sans argument reproductible localement afin de rester indépendant du fuseau de la machine exécutant les tests.

- **Phase 7 Mongo : isolation de l'import** : `pymongo.MongoClient` est importé **en interne** du script lors de son exécution, jamais avant — le test patche `pymongo.MongoClient` dans le module `pymongo` partagé avant d'exécuter le script, si bien que le `from pymongo import MongoClient` du script récupère la version mockée. Aucune connexion Atlas réelle.

- **Phase 7 Heartbeats : réalité partielle** : contrairement à Mongo (entièrement mocké), le harness **laisse hb() exécuter réellement** pour écrire les fichiers `logs/cycle_{CYCLE_ID}_phases.jsonl` avec un cycle_id unique généré par le test (`harness.new_cycle_id()`). Les fichiers générés sont nettoyés à la fin du test. Cela garantit la fidélité au comportement réel (écriture atomique JSONL, détection des fichiers manquants).

- **Phase 8 : protection du fichier de production** : `state/cycle_log.jsonl` est un fichier de production réel (jamais touché par les tests). Le test intercepte spécifiquement `os.path.exists()` et `builtins.open()` pour ce seul chemin — les écritures se font en mémoire (StringIO) ; tout le reste du système de fichiers passe par les vraies fonctions. Le script interne générant un script bash de git commit/push est simulé via `subprocess.run` mocké.

- **Phase 8 : rotation exacte à 90 lignes** : vérifie les trois cas : 89 existantes + 1 append = 90 total (aucune rotation), 90 existantes + 1 = 91 (rotation, drop C0), et échec du push git (exit code non-zéro) → notification tg() sans lever d'exception.

- **Webhook routing : arrêt synchrone de main_loop()** : `main_loop()` est une boucle `while True` de polling Telegram qui ne s'arrête jamais. Le test la lance en exécutant la vraie fonction avec tous les I/O mockés :
  - `threading.Thread` remplacé par une classe `_FakeThread` qui exécute la cible immédiatement et synchroniquement (pas de vrai thread)
  - `tg_post` mocké pour retourner une liste d'updates fictives au 1er appel, puis lever `_StopMainLoop` au 2e (une sentinelle qui hérite de `BaseException`, jamais catchée par le `except Exception` du polling)
  - Handlers réels (run_trade_workflow, run_status, etc.) mockés pour observer les appels sans exécuter réellement

- **Réutilisation du harness** : les 5 tests réutilisent intégralement `tests/fixtures/test_harness.py` — helpers `new_cycle_id`, `exec_phase_script`, factorisation de `_fake_open_factory`, `_real_open`, etc. — zéro duplication, même pattern qu'en PR #372/373/374.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale — ajout de tests sans modification du code applicatif. Complète la suite de tests lancée en PR #372/373/374 ; la structure `tests/` évolue :
- Phase 0 & 1 ✅ (PR #373)
- Phase 3 ✅ (PR #372, `test_phase3_scoring.py` existant)
- Phase 4 & 5 ✅ (PR #374)
- **Phase 6, 7, 8 ✅ NEW** (PR #375)
- **Webhook routing ✅ NEW** (PR #375)

Tous les tests de phase (0–8) sont désormais couverts, ainsi que le routing des commandes Telegram.

## Références CLAUDE.md respectées

- **Minimalisme** : tests purs, aucun code applicatif ajouté. `tests/` évolue, `binance-bot/` inchangé.
- **Modification chirurgicale** : 5 fichiers de test uniquement, réutilisent le harness sans duplication.
- **Convention horaire** : Phase 6 utilise UTC interne ; tests gèlent l'heure pour reproductibilité. Phase 7/8 n'ont pas de dépendances temporelles.
- **Pas de dépendances lourdes** : `unittest` stdlib, `unittest.mock` intégré, pas de `pytest`, `pandas`, ou librairies externes pour les tests.
- **Isolation des secrets** : aucun appel réseau réel (Mongo, Telegram, kraken-cli remplacés par des mocks locaux). `state/cycle_log.jsonl` de production jamais touché.

## Résultat

- Suite de tests augmentée : 58 → 77 tests (19 nouveaux)
- CI `tests.yml` : `python -m unittest discover tests/ -v` passe à 77 tests, OK ✅
- Linting : `ruff check` propre sur les 5 nouveaux fichiers ✅
- Aucun appel réseau réel déclenché ; `state/cycle_log.jsonl` et `state/trade_history.json` de production vérifiés inchangés après exécution (`git status` propre) ✅
- Spec `docs/superpowers/specs/2026-07-24-tests-integration-design.md` clôturée (5/5 tickets complétés) ✅

---

**Clôt** : #368
