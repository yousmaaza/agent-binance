# PR #23 — [M2] Heartbeats par phase en JSONL (logs/cycle_<id>_phases.jsonl)

> **Mergée le** : 2026-05-21
> **Branche** : `feat/issue-5-heartbeats-par-phase-en-jsonl`
> **Issues** : #5

## Contexte

Avant cette PR, il était impossible de savoir quelle phase du cycle de trading était en cours d'exécution (ou bloquée) sans lire le flux stream-json de Claude, difficile à interpréter en temps réel. Le ticket #5 demandait un mécanisme de traçabilité phase par phase pour permettre au futur watchdog daemon (ticket #7) de détecter les phases bloquées via la `mtime` du fichier.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification (+40/-1) | Injection de deux fonctions heartbeat (`_hb_start`, `hb`) et de leurs appels dans le `_TRADE_PROMPT_TEMPLATE` |

### Fonctions ajoutées / modifiées

> Ces fonctions sont injectées dans `_TRADE_PROMPT_TEMPLATE` — elles s'exécutent dans le **sous-processus Claude**, pas dans `webhook_server.py` directement.

| Fonction | Action | Description |
|---|---|---|
| `_hb_start(phase)` | Ajoutée | Démarre le chronomètre d'une phase en mémorisant le timestamp UTC dans le dictionnaire `_hb_phase_start[phase]` |
| `hb(phase, status, summary)` | Ajoutée | Clôture une phase : calcule la durée, écrit une ligne JSON dans `logs/cycle_<id>_phases.jsonl`, flush immédiat |

### Structure du fichier JSONL produit

Chaque ligne correspond à une phase terminée. Exemple :

```json
{"ts": "2026-05-21T20:05:42Z", "phase": 0, "status": "ok", "duration_s": 3.7, "summary": "Portfolio 1234.56 USDC, 2 positions, PnL jour +12.34 USDC"}
```

| Champ | Type | Description |
|---|---|---|
| `ts` | string ISO UTC | Horodatage de fin de phase (`%Y-%m-%dT%H:%M:%SZ`) |
| `phase` | int (0–7) | Numéro de la phase terminée |
| `status` | string | Toujours `"ok"` pour l'instant (valeur étendue prévue pour le ticket #7) |
| `duration_s` | float | Durée de la phase en secondes (arrondie à 0.1s) ; `null` si `_hb_start` n'a pas été appelé |
| `summary` | string | Résumé court spécifique à la phase (nombre de candidats, ordres exécutés, etc.) |

### Chemin du fichier et substitutions

```python
_HB_PATH = "__PROJECT_DIR__/logs/cycle___CYCLE_ID___phases.jsonl"
```

- `__PROJECT_DIR__` : substitué une fois au démarrage du cycle (valeur : chemin absolu du projet)
- `__CYCLE_ID__` : substitué à chaque cycle dans `run_trade_workflow()` (format `YYYYMMDD_HHMMSS`)
- Résultat : `<project_dir>/logs/cycle_20260521_200542_phases.jsonl`

## Décisions techniques notables

- **Imports privés dans le prompt** (`import json as _hb_json`, etc.) : évite les conflits de nommage avec le code métier de l'agent Claude qui pourrait lui-même importer `json`, `datetime` ou `os` sous leurs noms standards.
- **Dictionnaire `_hb_phase_start` comme chronomètre** : `.pop()` sur clé inconnue retourne `None` → `duration_s` vaut `null` si `_hb_start()` a été oublié, sans exception.
- **Fichier en mode append** (`"a"`) : les 8 phases d'un même cycle s'accumulent dans le même fichier ; un second `/trade` ajoute 8 nouvelles lignes sans écraser les précédentes.
- **`_f.flush()` immédiat après chaque écriture** : garantit la visibilité de la `mtime` du fichier pour le watchdog externe (ticket #7) même si le processus Claude ne se termine pas proprement.
- **Aucun nouveau code dans `webhook_server.py` côté serveur** : toute la logique heartbeat est dans le prompt injecté au sous-processus — le serveur continue à capturer stdout/stderr classiquement.

## Impact sur l'architecture

Ajout d'un nouveau type de fichier dans `logs/` : `logs/cycle_<id>_phases.jsonl`. Ce fichier complète les logs existants (`logs/stdout/` et `logs/stderr/`) avec une vue structurée de l'avancement du cycle, lisible en temps réel ligne par ligne. Il constitue l'interface de communication entre le sous-processus Claude et un futur watchdog daemon (ticket #7).

## Références CLAUDE.md respectées

- **Règle 4 (stdout/stderr toujours capturés)** : les heartbeats JSONL s'ajoutent aux captures existantes sans les remplacer — les logs bruts restent intacts.
- **Règle 3 (PROJECT_DIR dynamique)** : le chemin `_HB_PATH` utilise `__PROJECT_DIR__` (substitution runtime), jamais de chemin hardcodé.
- **Règle 2 (aucun secret hardcodé)** : aucune credential dans le code ajouté.
