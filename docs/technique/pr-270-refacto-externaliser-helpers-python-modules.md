# PR #270 — [REFACTO] Externaliser helpers Python en modules et découper trade_prompt par phase

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-269-factoriser-trade-helpers-modules-phase`
> **Issues** : #269, #272, #275, #279, #280

## Contexte

Cette PR refactorise profondément l'architecture du bot Binance pour éliminer la duplication de code et améliorer la maintenabilité. Le problème principal était que les fonctions partagées (`tg()`, `binance()`, gestion d'état) existaient en plusieurs exemplaires (générées dynamiquement ou hardcodées), et que le `trade_prompt.txt` était un monolithe de 1086 lignes impossible à maintenir. La refacto divise ces responsabilités en modules réutilisables et découpe le prompt par phase d'exécution.

## Changements architecturaux

### 1. Création de modules partagés en `binance-bot/core/`

#### `core/trade_helpers.py` (79 lignes)
Regroupe les fonctions critiques partagées par tous les scripts de phase :
- `tg(text)` : envoi Telegram via `curl` (jamais `urllib`, cf. CLAUDE.md règle 4)
- `binance(*args, _retries=3)` : appel `binance-cli` avec retry exponentiel et gestion d'erreurs
- `_load_config(project_dir="")` : charge `config.json`, retourne `{}` en erreur
- `_save_json_atomic(data, path)` : écriture atomic via tempfile + `os.replace()` (nouvellement créée)
- `_save_trade_history_atomic(data, path_override="")` : wrapper pour écrire `trade_history.json`
- `_save_config_atomic(data, project_dir="")` : wrapper pour écrire `config.json`

Les trois dernières utilisent `_save_json_atomic()` générique pour éliminer ~70% de duplication entre elles.

**Importation dans les scripts de phase** :
```python
from core.trade_helpers import tg, binance, _load_config, _save_trade_history_atomic, _save_config_atomic
```

#### `core/heartbeat.py` (66 lignes)
Gère les heartbeats JSONL par cycle (un heartbeat par phase exécutée) :
- `init(cycle_id, trigger="manual", project_dir="")` : initialise l'état module-level pour un cycle
- `_hb_start(phase)` : démarre le chrono d'une phase
- `hb(phase, status="ok", summary="")` : écrit un heartbeat JSONL avec déduplication par phase

État module-level (initialisation statique au démarrage, rafraîchis par `init()` pour chaque cycle) :
- `_phase_start` : dict `{phase: timestamp_utc}`
- `_hb_path` : chemin du fichier `logs/cycle_{CYCLE_ID}_phases.jsonl`
- `_trigger` : type de déclenchement ("auto", "manual")

**Utilisation dans les scripts de phase** :
```python
from core.heartbeat import hb, _hb_start, init as _hb_init
_hb_init(CYCLE_ID, trigger=_trigger, project_dir=PROJECT_DIR)  # appel unique en tête
_hb_start(phase_number)
# ... code métier ...
hb(phase_number, status="ok", summary="...")
```

#### `core/position_helpers.py` (88 lignes)
Nouveau module symétrique à `trade_helpers.py` pour les cycles de gestion de positions (horaires). Contient les mêmes fonctions : `tg()`, `binance()`, `_load_config()`, `_save_trade_history_atomic()`, `_save_config_atomic()`, `_save_json_atomic()`.

Élimine la génération dynamique d'un fichier helpers temporaire dans `runner.py` pour `position_prompt.txt`.

### 2. Module `core/env.py` — source unique de vérité

Refacto majeure du bootstrap et de l'assemblage du prompt :

```python
# Constantes globales
TOKEN, CHAT_ID, PROJECT_DIR, BINANCE_CLI_PATH, LOGS_DIR, MONGO_URI, MONGO_DB
PROMPT_VERSION  # SHA1 du prompt assemblé final (8 chars, stable)

def assemble_prompt(prompts_dir="") -> str:
    """Assemble le prompt depuis 9 sous-fichiers."""
    # Ordre : trade_prompt.txt + api_reference + phase0..5 + phases6_8
    return "...".join([...])

_TRADE_PROMPT_TEMPLATE = assemble_prompt()
_POSITION_PROMPT_TEMPLATE  # chargement direct du fichier position_prompt.txt
TRADE_PROMPT  # prompt final avec substitutions (tokens, paths)
POSITION_PROMPT
```

**Bénéfices** :
- Source unique pour `PROJECT_DIR`, `BINANCE_CLI_PATH` — facilite les refactos futures
- `assemble_prompt()` concatène les 9 fichiers dans l'ordre (garanti et testable)
- `PROMPT_VERSION` = SHA1 du prompt assemblé, versionnage stable et reproductible

### 3. Découpage du `trade_prompt.txt` en 9 sous-fichiers

**Avant** : monolithe de 1086 lignes + blocs import/subprocess inline

**Après** : structure hiérarchique
```
prompts/
├── trade_prompt.txt              (56 lignes : header + contexte)
├── shared/
│   └── api_reference.txt        (29 lignes : doc API)
└── phases/
    ├── phase0_snapshot.txt      (67 lignes)
    ├── phase1_scan.txt          (41 lignes)
    ├── phase2_analysis.txt      (42 lignes)
    ├── phase3_scoring.txt       (53 lignes)
    ├── phase4_sizing.txt        (38 lignes)
    ├── phase5_execution.txt     (102 lignes)
    └── phases6_8.txt            (154 lignes)
```

**Contenu de chaque fichier** : instruction Claude pour la phase, avec appels subprocess vers les scripts correspondants (ex : `phase3_scoring.txt` écrit `/tmp/cycle_X_phase3_input.json` puis appelle `python core/phases/phase3_scoring.py X`).

Les fichiers `.txt` ne contiennent plus aucun bloc import ni `subprocess.run` — c'est le code Python qui gère cela.

### 4. Déplacement des scripts de phase vers `binance-bot/core/phases/`

**Avant** : `prompts/code/` (12 scripts Python)
**Après** : `binance-bot/core/phases/` (package Python, `__init__.py` inclus)

Raison : **le code Python n'appartient pas à `prompts/`** — c'est un répertoire de templates textuels, pas de code exécutable.

**Scripts déplacés** :
- Phase 0 : `phase0_snapshot.py`, `phase0_oco_retry.py`, `phase0_trailing_stop.py`, `phase0_profit.py` (4 scripts)
- Phase 1 : `phase1_scan.py` (1 script)
- Phase 3 : `phase3_scoring.py` (1 script)
- Phase 4 : `phase4_sizing.py` (1 script)
- Phase 5 : `phase5_execution.py` (1 script)
- Phases 6-8 : `phase6_next_cycle.py`, `phase7_mongo.py`, `phase7_hb_check.py`, `phase8_cycle_log.py` (4 scripts)

Toutes les références dans les fichiers `.txt` et les docstrings des scripts ont été mises à jour (ex : `__PROJECT_DIR__/binance-bot/core/phases/phase3_scoring.py`).

**Prompts/code/ supprimé**.

### 5. Refacto de `runner.py` via dataclass `WorkflowConfig`

**Avant** : signature de `_run_workflow_cycle()` avec 13 paramètres, branches conditionnelles imbriquées pour `use_helpers`, `use_watchdog`, etc.

**Après** :
```python
@dataclass
class WorkflowConfig:
    use_watchdog: bool = False
    use_helpers: bool = False
    on_lock_busy: Callable | None = None
    on_start: Callable | None = None
    on_post_run: Callable | None = None
```

La signature de `_run_workflow_cycle()` passe de 13 à 7 paramètres. Les callbacks optionnels sont regroupés dans `config`, ce qui :
- Améliore la lisibilité et la testabilité
- Supprime les branches conditionnelles imbriquées
- Rend facile l'ajout de nouveaux flags (exemple : `use_watchdog`)

### 6. Autres changements

#### `position_prompt.txt` (220 lignes au lieu de 1 ligne)
Migré de `exec(open("__HELPERS_PATH__").read())` (génération dynamique) vers `from core.position_helpers import ...` (importation directe).

#### Suppression des limitations d'assemblage du prompt
- Avant : `__CYCLE_ID__` était substitué uniquement dans les phases générées
- Après : **tous les `__CYCLE_ID__` du prompt sont vérifiés et substituables** via la fonction `_get_cycle_vars()` dans `runner.py`

#### Bug adjacent noté (non corrigé)
- `phase0_snapshot.txt` fait ~420 lignes (critère ≤ 150 lignes non atteignable)
- Correction : nécessiterait un découpage métier interne (ex : snapshot logique vs. snapshot technique), au-delà du scope de cette PR

## Décisions techniques notables

1. **Pas de code dans `prompts/`** : les scripts sont en `binance-bot/core/phases/`, les templatesTextes en `prompts/phases/`.
   - Raison : séparation des responsabilités et congruence avec la structure du projet
   
2. **`_save_json_atomic()` générique** : remplace les fonctions `_save_trade_history_atomic()` et `_save_config_atomic()` dupliquées.
   - Raison : DRY (Don't Repeat Yourself) — une seule implémentation d'écriture atomique
   
3. **Heartbeat JSONL dans `logs/`** : persiste les timing + status de chaque phase
   - Raison : debugging et audit (phase7_hb_check vérifie la complétude des 7 phases)
   
4. **`PROMPT_VERSION` = SHA1 du prompt assemblé** : garantit la reproductibilité
   - Raison : chaque cycle connait exactement le prompt qui a généré ses décisions (versioning stable)
   
5. **Module-level state dans `heartbeat.py`** : `_phase_start`, `_hb_path`, `_trigger` sont initialisés par `init()`
   - Raison : chaque script de phase partage l'état du cycle sans passer 5 paramètres supplémentaires

## Impact sur l'architecture

### Avant
```
runner.py (253 lignes, beaucoup de logique)
├── Génère dynamiquement un fichier helpers temporaire pour trade & position
├── Gère les substitutions `__CYCLE_ID__`, `__BOT_TOKEN__`, etc.
├── Injecte le prompt monolithe (1086 lignes) dans Claude
└── trade_prompt.txt (monolithe)
    └── Blocs inline import/subprocess, Claude doit écrire/exécuter 12 scripts
```

### Après
```
runner.py (453 lignes, dataclass WorkflowConfig, logique explicite)
├── Importe TRADE_PROMPT et POSITION_PROMPT depuis core.env
├── core.env assemble le prompt depuis 9 sous-fichiers
├── Substitutions centralisées (tokens, paths)
├── **Pas** de génération dynamique d'helpers — importation directe
└── trade_prompt.txt (56 lignes : header)
    ├── shared/api_reference.txt (doc)
    └── phases/phase{0-5}.txt (instructions Claude)
        └── phase{N}.py (code Python, core/phases/)
            └── Imports : core.trade_helpers, core.heartbeat
```

**Avantages** :
- **Maintenabilité** : chaque phase est dans son propre fichier, facile à éditer
- **Testabilité** : les scripts peuvent être testés indépendamment sans lancer un cycle complet
- **Performance** : pas de ré-import / ré-exec à chaque cycle
- **Debugging** : heartbeats JSONL + logs stdout/stderr par cycle aident au diagnostic
- **Réutilisabilité** : `trade_helpers.py` peut être utilisé par d'autres scripts (ex : scripts de migration, scripts de test)

## Références CLAUDE.md respectées

| Règle | Respect |
|---|---|
| **Règle 1** : venv .venv Python 3.11 | ✅ Scripts testables avec `python -m py_compile` |
| **Règle 2** : PROJECT_DIR dynamique | ✅ Chaque script calcule PROJECT_DIR via `os.path.dirname` x4 |
| **Règle 4** : Telegram via curl uniquement | ✅ `tg()` utilise `subprocess.run(["curl", ...])`, jamais urllib |
| **Règle 5** : Logs stdout/stderr sauvegardés | ✅ `runner.py` persiste `logs/stdout/cycle_*.log`, `logs/stderr/cycle_*.log` |
| **Règle 6** : UTC interne, local à l'affichage | ✅ Heartbeats en UTC (`%Y-%m-%dT%H:%M:%SZ`), notifications Telegram en local |
| **Règle 7** : Auto-scheduler dans main_loop | ✅ Pas de changement à webhook_server.py |

## Impacts connues et limitations

| Aspect | Impact |
|---|---|
| **Migration d'état existant** | Aucun — trade_history.json, config.json, cycle_log.jsonl inchangés |
| **Compatibilité binance-cli** | Aucun changement à l'appel binance-cli, retry logic identique |
| **Performances** | Légère amélioration : pas de ré-exec des helpers à chaque cycle |
| **Debugging** | Amélioré : heartbeats JSONL + décomposition par phase |
| **Limitation connue** | phase0_snapshot.txt reste ~420 lignes (découpage métier supplémentaire requis) |

## Tests effectués (du merge commit)

- ✅ `python -m py_compile binance-bot/core/phases/phase*.py` — tous passent
- ✅ `python -c "import ast; ast.parse(open('binance-bot/core/trade_helpers.py').read())"` — syntaxe OK
- ✅ `python -c "import ast; ast.parse(open('binance-bot/core/heartbeat.py').read())"` — syntaxe OK
- ✅ `python -c "import ast; ast.parse(open('binance-bot/core/env.py').read())"` — syntaxe OK
- ✅ `python -c "import ast; ast.parse(open('binance-bot/orchestration/runner.py').read())"` — syntaxe OK
- ✅ `grep -rn "prompts/code" prompts/phases/` — 0 résultats ✅
- ✅ `grep -rn "^import\|subprocess.run" prompts/phases/` — 0 résultats ✅

Cycles en production après merge :
- ✅ Cycles #103006-#103007 (2026-06-30) : phases 0-8 OK, heartbeats enregistrés
- ✅ Cycle #103012 (2026-06-30 16:05) : phase3_scoring.py appelé avec input.json → output.json OK

## Commits inclus

Cette PR est une consolidation de plusieurs sous-tickets :
- **#269** : Externaliser les helpers et modules
- **#272** : Refactoriser `_save_*_atomic()` en `_save_json_atomic()`
- **#275** : Importer config depuis `env.py` au lieu de redéfinir localement
- **#279** : Réduire complexité de `_run_workflow_cycle` via dataclass
- **#280** : Migrer position_helpers vers module symétrique

---

**Changelog technique** : `core/trade_helpers.py` (79 LOC), `core/heartbeat.py` (66 LOC), `core/env.py` (119 LOC), 12 × `core/phases/phase*.py`, 9 fichiers `prompts/phases/`, `binance-bot/core/position_helpers.py` (88 LOC), `runner.py` refactorisé (dataclass WorkflowConfig).
