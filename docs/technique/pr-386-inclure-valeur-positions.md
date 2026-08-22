# PR #386 — [BUG] Inclure la valeur des positions dans portfolio_total

> **Mergée le** : 2026-08-22
> **Branche** : `feat/issue-385-portfolio-total`
> **Issues** : #385

## Contexte

Phase 0 calcule `portfolio_total` comme simple solde USDC en espèces (`balance.get("USDC", 0)`), ce qui sous-estime le portefeuille lorsque des positions sont ouvertes. Par exemple, avec 100 USDC libres et 5000 USDC en positions ouvertes (ETH, SOL, etc.), le bot rapportait un portefeuille de 100 USDC au lieu de 5100 USDC, affectant le calcul de `budget_disponible` et du check `daily_loss_limit_pct`.

Cette PR corrige le bug en ajoutant la **valeur au marché de toutes les positions ouvertes** au calcul de `portfolio_total`, via une accumulation dans le script de snapshot (`phase0_snapshot.py`) qui iterate déjà sur les positions ouvertes pour afficher le P&L.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase0_snapshot.py` | Modification | Ajouter accumulation `positions_value` dans la boucle P&L ; exposer via stdout + JSON output |
| `prompts/phases/phase0_snapshot.txt` | Modification | Utiliser `positions_value` dans le calcul de `portfolio_total` |
| `tests/test_phase0_snapshot.py` | Modification | Ajouter assertions `positions_value` aux tests existants |

### Fonctions modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `main()` | `phase0_snapshot.py:20-72` | Modification | Initialiser `positions_value = 0.0` (ligne 25) ; accumuler `current_usdc` (ligne 46) ; retourner via stdout (ligne 64) et JSON (ligne 66) |

## Décisions techniques notables

- **Réutilisation de la boucle P&L existante** : au lieu de refaire une requête `kraken ticker` pour chaque position, l'accumulation se fait dans la même boucle qui calcule déjà le P&L (ligne 32-57). Aucune surcharge API.

- **Format de retour** : le script expose désormais `PHASE0_SNAPSHOT_DONE|open_positions=N|positions_value=X` (ajout du champ `positions_value`), et le JSON output inclut `{"open_positions": N, "positions_value": X}` — les deux formats garantissent que Phase 0 du prompt peut extraire `positions_value` via parsing regex et réassigner la variable.

- **Pas de nouvelle variable globale Phase 0** : le prompt Phase 0 (`phase0_snapshot.txt` ligne 24) remplace simplement `portfolio_total = float(balance.get("USDC", 0))` par `portfolio_total = float(balance.get("USDC", 0)) + positions_value`, utilisant la valeur déjà présente au scope du prompt (elle-même issue du stdout du script).

- **Timing : avant OCO retry et trailing stop** : `positions_value` est calculé en début de Phase 0, avant les modifications éventuelles de positions (OCO retry, trailing stop, profit prise). Aucun risque de double-comptage.

- **Tests additionnels** : deux assertions ajoutées pour couvrir les deux cas limites :
  - Cas 1 : positions ouvertes (ETH 0.5 @ 1900 + SOL 2 @ 90) → `positions_value = 1130.0`
  - Cas 2 : aucune position ouverte → `positions_value = 0.0`

## Impact sur l'architecture

Changement isolé, sans modification du flux d'exécution ou des composants externes :
- Phase 0 continue de fonctionner comme avant (3 étapes : snapshot, OCO retry, trailing stop, etc.)
- Phase 4 (sizing) consomme `portfolio_total` via le même mécanisme que avant (via variable du prompt).
- Aucune modification de la persistance (state/) ni des appels Kraken.
- Le reste des phases (1–8) n'est pas affecté.

## Références CLAUDE.md respectées

- **Minimalisme** : changement chirurgical limité aux fichiers nécessaires (script + prompt + tests) ; une ligne modifiée par fichier (+ initialisation).
- **Convention horaire (Règle 6)** : pas de logique horaire impactée ; `positions_value` est calculé immédiatement au snapshot.
- **Tests** : suite de tests existante étendue, pas de création de nouveau fichier de test.

## Vérifications effectuées

- ✅ Syntaxe Python : `python -c "import ast; ast.parse(open('binance-bot/core/phases/phase0_snapshot.py').read())"` → 0
- ✅ Tests unitaires : `python -m unittest tests.test_phase0_snapshot` → OK (3 tests)
- ✅ Tests Phase 4 (consommateur) : `python -m unittest tests.test_phase4_sizing` → OK (6 tests, pas de régression)
- ✅ JSON output : vérification que le fichier `/tmp/cycle_{CYCLE_ID}_phase0_snapshot_output.json` contient bien `{"open_positions": N, "positions_value": X.XX}`
