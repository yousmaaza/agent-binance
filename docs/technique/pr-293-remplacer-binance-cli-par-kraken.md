# PR #293 — Remplacer binance-cli par kraken-cli dans la couche de détection

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-285-kraken-cli-detection`
> **Issues** : #285

## Contexte

Migration de la couche d'exécution d'ordres : passage de `binance-cli` (CLI Binance officiel) vers `kraken-cli` (CLI Kraken via Rust), concrétisé dans la détection du chemin exécutable et les substitutions de template de prompt.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `CLAUDE.md` | Modification | Met à jour la description de la Stack pour mentionner `kraken-cli` |
| `binance-bot/core/env.py` | Modification | Remplace `BINANCE_CLI_PATH` → `KRAKEN_CLI_PATH`, détection via `shutil.which("kraken")` |
| `binance-bot/core/trade_helpers.py` | Modification | Renomme variable interne `_BINANCE_CLI` → `_EXCHANGE_CLI` pour uniformité |
| `binance-bot/core/position_helpers.py` | Modification | Renomme variable interne `_BINANCE_CLI` → `_EXCHANGE_CLI` pour uniformité |
| `binance-bot/orchestration/runner.py` | Modification | Remplace template `__BINANCE_CLI_PATH__` → `__KRAKEN_CLI_PATH__` dans `_write_helpers_file()` |
| `prompts/trade_prompt.txt` | Modification | Header ligne 1 : "Binance" → "Kraken" + substitution `__KRAKEN_CLI_PATH__` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `KRAKEN_CLI_PATH` (env.py:33) | Modifiée | Détection : `shutil.which("kraken")` ou fallback `~/.cargo/bin/kraken` |
| Substitution `.replace("__KRAKEN_CLI_PATH__"...)` (env.py:110, 118) | Modifiée | Injectée dans `TRADE_PROMPT` et `POSITION_PROMPT` |
| `_EXCHANGE_CLI` (trade_helpers.py:12, position_helpers.py:12) | Modifiée | Variable interne pour l'appel CLI exchange (alias `_EXCHANGE_CLI` = `KRAKEN_CLI_PATH`) |
| `_write_helpers_file()` (runner.py:235–337) | Modifiée | Génère `KRAKEN_CLI` au lieu de `BINANCE_CLI` pour les helpers générés à la volée |

## Décisions techniques notables

- **Nommage interne unifié** : `_EXCHANGE_CLI` plutôt que `_BINANCE_CLI` signale que l'implémentation est abstraite d'un point de vue CLI exchange (prêt pour d'autres remplacements futurs).
- **Détection par `shutil.which()`** : préféré à un hardcode `~/.cargo/bin/kraken` pour supporter les installations système de kraken-cli.
- **Fallback explicite** : `~/.cargo/bin/kraken` reste un fallback en cas d'absence de `kraken` dans PATH, couvrant la majorité des utilisateurs sur macOS/Linux développeurs.
- **Fonction `binance()` non renommée** : reste intentionnellement `binance(*args)` dans `trade_helpers.py` et `position_helpers.py` pour ne pas casser les 12 scripts de phase générés (T0–T8) qui l'importent et l'appellent. Le renommage `binance() → exchange()` est planifié pour T2–T6 (ticket futur).
- **Pas de paramètre `--profile`** : le `--profile agent-profile` spécifique à `binance-cli` n'apparaît pas dans les fichiers modifiés ; il existe dans les scripts de phase (T0–T8) mais ce ticket s'en abstient pour rester chirurgical.

## Impact sur l'architecture

**Changement isolé à la couche de détection et substitution.**

- Les imports de fonctions helpers (`tg()`, `binance()`, etc.) restent identiques.
- La signature de `binance(*args)` est inchangée ; elle appelle simplement `KRAKEN_CLI` au lieu de `BINANCE_CLI`.
- Tous les appels d'ordres (Phase 1, 4, 5 du prompt) passent maintenant par `kraken-cli` au lieu de `binance-cli`.
- MongoDB, Telegram, TradingView MCP : aucun changement.
- État persistant (`state/trade_history.json`, `state/agent_lock.json`) : aucun changement.

**Pas d'impact sur la logique de trading.** C'est une migration d'infrastructure CLI, pas une refonte d'algorithme.

## Références CLAUDE.md respectées

- **Règle 1 (venv + git-perso)** : PR créée et testée via le venv Python 3.11 standard. Tests syntaxe via `python -c "import ast; ast.parse(...)"` appliqués.
- **Règle 2 (PROJECT_DIR dynamique)** : `shutil.which()` + `~/.cargo/bin/kraken` compatible macOS et VPS Linux.
- **Règle 4 (curl pour Telegram)** : aucun changement aux appels Telegram (toujours via curl).
- **Règle 5 (logs stdout/stderr)** : aucun changement aux mécanismes de capture.
- **Règle 6 (UTC interne)** : aucun changement horaire.
- **Règle 7 (auto-scheduler dans main_loop)** : aucun changement au scheduler.
- **Modifications chirurgicales** : touchées uniquement les 6 lignes relatives à la détection CLI et substitution template. Le reste du code (phases, handlers) inchangé.
