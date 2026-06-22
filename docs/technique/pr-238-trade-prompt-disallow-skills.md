# PR #238 — Disallows skill invocation in TRADE_PROMPT

> **Mergée le** : 2026-06-22
> **Branche** : `feat/issue-237-trade-prompt-disallow-skills`
> **Issues** : #237

## Contexte

Un cycle de trading (20260622_080501) a invoké le skill `start-agent` au lieu d'exécuter les 9 phases de trading, causant une durée anormale (57s vs 400-600s attendus). Root cause : le `TRADE_PROMPT` ne définissait pas explicitement quels outils étaient interdits, et Claude a choisi d'invoquer un skill disponible au lieu de s'exécuter par phases via Bash et les helpers partagés. Cette PR ajoute un bloc d'instructions critiques au début du prompt pour interdire sans ambiguïté tous les skills et clarifier que seuls Bash, Read, Write, Edit et Grep sont autorisés.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Modification | Ajout section "RÈGLES D'EXÉCUTION CRITIQUES" en début de prompt (23 lignes) |

### Structure du nouveau bloc d'instructions

**Ligne 3–11 (⚠️ RÈGLES D'EXÉCUTION CRITIQUES)** :
- Liste des outils **INTERDITS** : tous les skills (`start-agent`, `start-trading`, `query-token-info`, etc.), CronCreate/CronDelete/ScheduleWakeup, DesignSync, EnterPlanMode, ExitPlanMode, Workflow, Agent, TaskCreate/TaskGet, NotebookEdit, tout outil non-Bash/Read/Write/Edit/Grep.
- À la suite, énumération répétée pour éviter toute ambiguïté.

**Ligne 12–17 (✅ OUTILS AUTORISÉS UNIQUEMENT)** :
- Bash (exécution shell et Python)
- Read (lecture fichiers config/state)
- Write (écriture fichiers helpers)
- Edit (modification fichiers existants)
- Grep (recherche texte optionnelle)

**Ligne 19–22 (📋 TA MISSION)** :
- Rappel : exécuter 9 phases (0–8)
- Chaque phase = script Python écrit en `/tmp`, lancé via Bash
- Clarification : "Tu n'as pas besoin de skill pour cela."

### Autres ajustements existants conservés

Le reste du prompt (notamment les sections sur l'exécution Python, les helpers, les commandes binance-cli, les pièges courants) sont inchangés — cette PR touche **exclusivement** aux lignes de garde initiales (3–22).

## Décisions techniques notables

- **Placement du bloc au **très début** (ligne 3 après titre/contexte)** : force Claude à lire les restrictions avant toute autre instruction, éliminant le risque qu'elles soient "oubliées" par une continuation ou une relecture à la fin du contexte.
- **Énumération exhaustive des outils interdits** : plutôt qu'une règle du type "ne fais pas de skills génériquement", on liste tout ce qui est interdit, y compris les outils anciens ou rares, pour maximiser la clareté.
- **Rappel des outils autorisés** : distinction claire : seuls 5 outils sur les ~25 disponibles dans Claude Code sont autorisés.
- **Changement instruction-only** : aucune modification du code applicatif (`webhook_server.py`, `orchestration/runner.py`), de la logique des phases, ou de la configuration MongoDB. C'est une clarification du contrat entre le serveur et le sous-processus Claude.

## Impact sur l'architecture

**Aucun impact architectural** — changement isolé au prompt. Le flux de données, les composants externes (Telegram, Binance CLI, MongoDB) et la structure des phases restent identiques. Ce changement améliore la **robustesse** du système en prévenant que Claude ne se perd dans une invocation de skill — il oblige une exécution disciplinée des 9 phases en tant qu'orchestration par Bash/helpers.

## Références CLAUDE.md respectées

- **Principe : minimalisme** — ajout de 23 lignes de description et de garde-fous au prompt existant, aucune abstraction ou restructuration inutile.
- **Principe : clarity before implementation** — la règle était implicite ("Claude orchestre les phases") ; elle est maintenant explicite dans le prompt. Cela prévient les cycles qui déraillent.
- **Configuration : aucun secret hardcodé** — le prompt ne contient pas d'identifiants ; les substitutions `__PROJECT_DIR__`, `__CYCLE_ID__` restent en place et sont remplacées par le serveur au runtime.

## Notes de debug

Avant cette PR, dans un cas échouant, les logs ressemblaient à :
```
$ cat logs/stderr/cycle_20260622_080501.log
Traceback: start-agent invoqué...
```

Après cette PR, une tentative d'invoquer un skill sera rejetée immédiatement par Claude avec un message du type :
```
"I cannot invoke this tool — it's explicitly forbidden in the TRADE_PROMPT..."
```

Les cycles qui échouent pour d'autres raisons (volatilité extrême, erreur binance-cli, MongoDB indisponible) continueront à s'exécuter correctement et seront loggés dans la Phase 7.
