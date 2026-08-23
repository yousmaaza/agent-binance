# PR #423 — [TECH] Test de cohérence des contrats prompt / script

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-403-test-coherence-prompt-script`
> **Issues** : #403

## Contexte

Chaque script Python de phase (`binance-bot/core/phases/phaseN_*.py`) lit et/ou écrit un fichier d'échange avec le prompt correspondant (`prompts/phases/phaseN.txt`), en utilisant un chemin en dur : `cycle_{CYCLE_ID}_phaseN_(input|output).json`. Les chemins doivent rester **synchronisés des deux côtés** — côté script avec la notation f-string `{CYCLE_ID}`, côté prompt avec la notation substituée `__CYCLE_ID__`.

Trois incidents en août 2026 (PR #391, PR #397, bug #385) révélaient une absence totale de garde-fou : des outils de review automatique (bandit B108) modifiaient les chemins temporaires sans savoir qu'ils faisaient partie d'un contrat implicite, causant des `FileNotFoundError` en plein cycle de production. Seule une relecture manuelle attrapait ces désynchronisations.

Cette PR ajoute un test d'intégration `tests/test_prompt_script_contract.py` qui **valide statiquement** ce contrat avant chaque cycle.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `tests/test_prompt_script_contract.py` | Ajout (435 lignes) | Nouveau test d'intégration validant la cohérence script ↔ prompt |
| `binance-bot/core/phases/phase0_*.py` (4 fichiers) | Modification | Ajout du marqueur `# nosec B108` + comment explicite sur les chemins `/tmp` volontaires |
| `binance-bot/core/phases/phase[134567]_*.py` (7 fichiers) | Modification | Idem |
| `.claude/MEMORY.md` | Modification | Documentation du contrat et des trois incidents du 2026-08-22 |

### Nouvelles fonctions / classes

| Élément | Type | Description |
|---|---|---|
| `test_prompt_script_contract.py` | Module test | 170 tests unitaires (5 nouveaux : `test_prompt_extraction`, `test_script_extraction`, `test_matching_paths`, `test_diverging_literal_path_is_detected`, `test_unregistered_dynamic_path_fails`) |
| `SCRIPT_TO_PROMPT` | Dictionnaire | Mapping script → prompt (11 paires) |
| `_resolve_literal()` | Fonction | Résout statiquement les expressions AST (f-string, `PROJECT_DIR`, `os.path.join`, concaténations) pour extraire les chemins |
| `_normalize()` | Fonction | Convertit notation prompt `__CYCLE_ID__` → notation script `{CYCLE_ID}` |

## Décisions techniques notables

- **Analyse AST, pas regex brute** : les chemins sont extraits en parcourant l'arbre syntaxique Python (`ast`) plutôt qu'en grattant le texte. Cela permet de résoudre les expressions composées (`os.path.join(PROJECT_DIR, "state", f"cycle_{CYCLE_ID}...` est aussi comparable que `f"/tmp/cycle_{CYCLE_ID}"`) et d'ignorer les faux positifs (variables homonymes qui ne sont pas des chemins).

- **Inversement du fardeau de la preuve** : tout chemin d'échange **non entièrement résoluble statiquement** (utilisant `tempfile.gettempdir()`, `tempfile.mkstemp()`, ou dynamique autrement) déclenche une **erreur de test sauf s'il porte explicitement le marqueur `# contract-dynamic`**. L'exemption est **à la ligne, pas au fichier** — ce choix oblige à documenter précisément chaque exception (actuellement une seule : `phase1_scan.py:121` pour le bug #414 non corrigé). Cela inverse le pattern habituel où l'absence de preuve vaut absence de culpabilité.

- **Chemins `/tmp` « volontaires » « temporaires »** : les 13 instances existantes utilisant `/tmp/cycle_...` sont marquées `# nosec B108` avec un commentaire renvoyant explicitement aux issues #392 (déplacement propre vers `state/`) et #403 (ce test). Le `# nosec` est volontairement temporaire — il est levé au jour où #392 sera traité et les chemins migrés de `/tmp` vers `state/`.

## Impact sur l'architecture

**Changement isolé, pas d'impact sur l'architecture globale.** Le test s'exécute via le CI existant (`python -m unittest discover tests/`) — pas de nouvelles dépendances, pas de modification du flux d'exécution. Il prévient des régressions futures en validant un invariant déjà implicite dans le contrat script ↔ prompt (celui-ci était simplement non testé jusqu'à présent).

### Détails de coverage

Le test vérifie :

1. **Extraction côté script** (parsing AST) : littéraux f-string, `PROJECT_DIR`, `os.path.join()`, concaténations
2. **Extraction côté prompt** (regex) : motif `cycle___CYCLE_ID___phaseN_*.json`
3. **Comparaison** : tous les chemins extraits d'un script et de son prompt associé doivent être identiques (après normalisation)
4. **Chemins non résolubles** : détection et rejet, sauf si marqués `# contract-dynamic`
5. **Faux positifs** : pas d'alertes sur les fichiers d'état persistants (`trade_history.json`, `cycle_log.jsonl`, etc.) qui suivent un autre motif et ne sont pas des fichiers d'échange éphémères

### Info découverte en implémentation (hors scope)

Plusieurs scripts Phase 0 (`phase0_snapshot.py`, `phase0_profit.py`, `phase0_oco_retry.py`, `phase0_trailing_stop.py`) et `phase6_next_cycle.py` écrivent un fichier `_output.json` que le prompt associé ne relira jamais — seuls les marqueurs stdout (`PHASE0_SNAPSHOT_DONE|...`) sont consommés. Ces fichiers ne sont pas concernés par le contrat testé (rien à comparer, pas de risque de désync) mais représentent potentiellement des sorties mortes. À vérifier pour clarification.

## Références CLAUDE.md respectées

- **Règle 2** (PROJECT_DIR dynamique) : le test résout `PROJECT_DIR` statiquement, ce qui est correct puisqu'il s'agit d'une constante connue (mentionnée en dur dans CLAUDE.md).
- **Aucune modification du code applicatif** : le test est isolé dans `tests/` et ne touche ni `webhook_server.py` ni `config.json` ni les scripts de phase (sauf les commentaires/marqueurs).
- **Pas de dépendance nouvelle** : le test utilise `unittest` (stdlib, déjà utilisé dans le projet) plutôt que `pytest` qui n'est pas installé.

---

### Résultat du test plan

- ✅ `tests/test_prompt_script_contract.py` passe sur l'état courant (165 tests avant, 170 après = +5)
- ✅ Régression PR #391 détectée (chemin `/tmp` vs `state` divergent) → test échoue comme prévu
- ✅ Chemin dynamique non documenté → test échoue en le signalant
- ✅ `bandit -q -f txt binance-bot/core/phases/*.py` : 13 findings B108 neutralisés, 0 nouveau finding
- ✅ Syntaxe Python validée sur les 11 fichiers modifiés
- ✅ Aucune divergence réelle détectée en état courant (les 3 incidents du 2026-08-22 sont corrigés ou documentés)
