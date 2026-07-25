# PR #372 — [M2] Harness de test kraken-cli + conventions tests/ + CI

> **Mergée le** : 2026-07-25
> **Branche** : `feat/issue-365-harness-test-kraken-cli-ci`
> **Issue** : #365

## Contexte

Pose les fondations du testing du bot : introduce un harness (`fake_kraken.py`) qui imite `kraken-cli` avec injection de scénarios JSON, établit les conventions `tests/test_<module>.py` en `unittest` stdlib (pas `pytest`), et ajoute la CI GitHub Actions qui exécute les tests sur chaque PR. C'est la base (milestone M2) qui débloque les tickets suivants : tests des phases 0/1, 4/5, 6/7/8 + routing `webhook_server.py` (tickets #366-#368 dépendent de ce harness).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/tests.yml` | Ajout | Workflow GitHub Actions sur les PR : installe Python 3.11 + dépendances, exécute `python -m unittest discover tests/ -v` |
| `tests/fixtures/fake_kraken.py` | Ajout | Stub exécutable remplaçant `kraken-cli` — reçoit `FAKE_KRAKEN_SCENARIO` (chemin JSON), parse la commande, retourne les données du scénario correspondantes |
| `tests/test_phase3_scoring.py` | Ajout | Tests de démonstration (29 tests total) : validation formule score, seuils `min_signal_score` et mode dégradé, exigence `signal_4h` BUY/STRONG_BUY, contraintes `max_open_positions` et `max_correlated_positions` (groupe SOL/SUI/STX/ETH), décision SELL, et validation du stub fake_kraken lui-même |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `fake_kraken.main()` | Ajoutée | Point d'entrée du stub ; parse `sys.argv`, charge le scénario depuis `FAKE_KRAKEN_SCENARIO`, dispatch vers `ticker`/`balance`/`pairs`/`order`/`query-orders`, retourne JSON stdout |
| `fake_kraken._load_scenario()` | Ajoutée | Charge et parse le fichier JSON scénario ; exit 1 si env var non définie |
| `fake_kraken._positional_args()` | Ajoutée | Filtre les arguments positionnels (non-flags) de la ligne de commande |
| `_run_phase3()` | Ajoutée (test helper) | Exécute `phase3_scoring.py` via `importlib` avec injection input JSON dans `/tmp/`, mock `tg()` sur `subprocess.run`, retourne output JSON ; chaque invocation génère un `cycle_id` distinct pour isoler les fichiers temporaires |

## Décisions techniques notables

- **Unittest stdlib plutôt que pytest** : projet existant sans pytest dans `requirements-dev.txt`, unittest natif + pas de dépendance supplémentaire, aligné avec la philosophie minimaliste du bot
- **Scénarios JSON en fichier, pas en code** : permet de modifier un scénario sans relancer Python, futur : paramétrisation des tests
- **Import via `importlib.util.spec_from_file_location` pour `phase3_scoring.py`** : script top-level sans fonctions exportées, ré-exécution du vrai module à chaque test (pas mock/patch du module), garantit une validité contre les changements de `phase3_scoring.py`
- **`tg()` mockée sur `core.trade_helpers.subprocess.run`** : pas d'appels réseau réels, isolé aux limits du contexte test-phase3 (autres phases mettront en place leurs propres mocks)
- **Fichiers temporaires en `/tmp/cycle_<cycle_id>_*.json`** : convention en dur dans `phase3_scoring.py` lui-même (voir note), test reste synchronisé sans introduire de dépendance `tempfile.gettempdir()` qui divergerait sur macOS

## Impact sur l'architecture

Architectural : ajout du répertoire `tests/` et convention de test, mais **aucun changement au code applicatif** (`webhook_server.py`, phases, helpers). Les tests fonctionnent en isolation via le harness, sans modifier le flux de production.

Flux de dépendances : PR #372 débloque les trois tickets suivants (M2a/M2b/M2c) qui implémenteront les tests des autres phases en suivant la même convention.

## Références CLAUDE.md respectées

- **Minimalisme (Règle « Réfléchir avant de coder »)** : stub fait strictement ce qu'il faut, aucune feature spéculative
- **Modifications chirurgicales** : ajout uniquement du répertoire `tests/`, aucune modification du code existant
- **Python venv 3.11** : tests exécutés dans le contexte venv du projet via la CI
- **Pas de secret hardcodé** : scénarios JSON contiennent uniquement des données synthétiques (pas de credentials)
- **Conventions de test** : `tests/test_<module>.py` alignées avec le pattern `PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` pour portabilité

## Notes

- **Effet de bord non corrigé** : `binance-bot/core/env.py:assemble_prompt()` ouvre les fichiers prompts sans context manager (`open(p).read()`), génère des `ResourceWarning: unclosed file` dans la sortie `unittest -v` (cosmétique, pas un échec fonctionnel — hors scope de cette PR)
- **Dépendance critique** : les trois tickets suivants (M2a/b/c, #366-#368) dépendent de ce harness et de la convention `unittest` établie ici ; l'ordre de merge doit respecter cet ordre de blocage
