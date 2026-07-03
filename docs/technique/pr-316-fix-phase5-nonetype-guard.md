# PR #316 — [BUG] Fix phase5_execution.py crash TypeError quand trade=None (0 ordres)

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-315-fix-phase5-nonetype-guard`
> **Issues** : #315

## Contexte

Phase 5 (`binance-bot/core/phases/phase5_execution.py`) écrit chaque trade exécuté dans `state/trade_history.json` en lisant l'input depuis `phase5_input.json`. Quand **aucun BUY n'est exécuté en Phase 4**, l'orchestrateur passe `{"trade": null}` en input. Dans ce cas, le code original tentait d'accéder `trade["coin"]` sans vérifier la nullité, ce qui provoquait un `TypeError: 'NoneType' object is not subscriptable`.

Cette situation est légitime : quand tous les candidats sont filtrés (risque insuffisant, positions maxées, ou aucun candidat), Phase 5 doit simplement signaler que 0 ordres ont été exécutés et retourner proprement.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase5_execution.py` | Ajout garde NoneType | Évite crash et gère proprement le cas zéro ordres |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| Module-level (lignes 41-45) | Ajoutée | Garde `if not trade:` qui retourne `PHASE5_DONE|executed=0|skipped=0` et exit(0) quand trade est None |

### Changement détaillé

**Avant (ligne 41)** :
```python
trade = inp.get("trade", {})
```

Problème : avec `{}` comme défaut, si la clé `"trade"` existait avec valeur `null`, le `.get()` retournait quand même `None` (l'entrée existait). Le code ensuite tentait `trade["coin"]` sur `None`.

**Après (lignes 41-45)** :
```python
trade = inp.get("trade")

if not trade:
    print("PHASE5_DONE|executed=0|skipped=0")
    sys.exit(0)
```

Logique : 
1. `inp.get("trade")` sans défaut retourne `None` si la clé existe mais contient `null`.
2. La garde `if not trade:` capture cet état et signale proprement une exécution vide (0 ordres).
3. Le reste du code (sauvegarde dans `trade_history.json`) n'est atteint que si `trade` est non-null et valide.

## Décisions techniques notables

- **Pas de défaut `{}` dans le `.get()`** : la distinction entre "clé absent" et "clé présent mais null" est intentionnelle ici. L'orchestrateur envoie explicitement `{"trade": null}`, donc il faut le détecter et le gérer, pas le masquer par un défaut.
- **Exit code 0 (succès)** : Phase 5 considère "0 ordres exécutés" comme un succès du cycle, non une erreur. Le cycle continue vers Phase 6 (rapport) et Phase 7 (MongoDB).
- **Message stdout standard** : `PHASE5_DONE|executed=0|skipped=0` suit le format établi pour les phases (`PHASE5_SAVE_DONE|coin=...|trade_id=...`), permettant à l'orchestrateur de parser la sortie uniformément.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. Phase 5 devient plus robuste face aux states vides, ce qui était un gap mineur mais présent depuis l'introduction de la Phase 5 en PR #39.

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : le script utilise déjà `PROJECT_DIR` correctement calculé, inchangé.
- **Règle 3 (Aucun secret hardcodé)** : aucun secret dans ce script, inchangé.
- **Règle 5 (Capture stdout/stderr)** : la sortie est captée normalement par `run_trade_workflow()`, inchangé.

---

**Closes #315**
