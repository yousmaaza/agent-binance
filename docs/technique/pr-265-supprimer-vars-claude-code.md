# PR #265 — Supprimer vars CLAUDE_CODE_* du sous-processus claude

> **Mergée le** : 2026-06-24
> **Branche** : `fix/issue-264-claude-child-session-env`
> **Issues** : #264

## Contexte

Le bot lance un sous-processus `claude --print` pour chaque cycle de trading. Ce sous-processus héritait automatiquement les variables d'environnement du daemon parent, incluant les variables de session Claude Code (`CLAUDE_CODE_CHILD_SESSION`, etc.). 

Quand le daemon tournait dans une session Claude Code active (ex. via `nohup` lancé depuis l'IDE), le sous-processus enfant tentait de réutiliser ces variables de session parente. Or, si la session parente expirée entre la sortie du daemon et le lancement du cycle, le CLI `claude` échouait avec un code `"Not logged in"` en 1-2 secondes, stoppant le cycle avant même l'exécution du prompt de trading.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Création (nouveau module) | Nouvelle fonction `_run_claude()` avec logic de nettoyage d'env |

### Fonctions clés

| Fonction | Action | Description |
|---|---|---|
| `_run_claude()` | Ajoutée (runner.py:336–370) | Lance le sous-processus Claude en isolant l'env de session |
| `run_trade_workflow()` | Ajoutée (runner.py:23–43) | Orchestre un cycle de trading complet |
| `run_position_check_workflow()` | Ajoutée (runner.py:46–61) | Orchestre un cycle de gestion des positions ouvertes |
| `_run_workflow_cycle()` | Ajoutée (runner.py:64–154) | Cœur de l'orchestration : lock, logging, streaming Claude |

### Fix spécifique (PR #264)

**Lignes 343–349** de `_run_claude()` :

```python
env = os.environ.copy()
# Strip Claude Code parent-session vars so the child claude process authenticates
# independently instead of trying to reuse an expired parent session.
for _k in ("CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
           "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH"):
    env.pop(_k, None)
```

**Les 5 variables supprimées** :
- `CLAUDE_CODE_CHILD_SESSION` : marqueur de session enfant
- `CLAUDE_CODE_SESSION_ID` : ID de session parente
- `CLAUDECODE` : racine du répertoire Claude Code
- `CLAUDE_CODE_ENTRYPOINT` : script d'entrée parent
- `CLAUDE_CODE_EXECPATH` : chemin d'exécutable parent

En supprimant ces variables avant `subprocess.Popen`, le CLI enfant authentifie indépendamment via les credentials locaux (token API ou cache local), évitant la dépendance sur une session parente qui peut expirer.

## Décisions techniques notables

- **Purge proactive plutôt que fallback** : Au lieu de détecter l'erreur et de retry, on prévient la condition en supprimant les variables fautives **avant** de lancer le processus. Cela rend le démarrage du cycle déterministe.
- **Whitelist explicite** : On énumère les 5 variables à supprimer plutôt que d'utiliser un pattern regex — plus clair et moins risqué pour l'avenir.
- **Pas de fallback API** : La solution ne renforce pas le fallback API ; elle élimine simplement une source d'erreur transiente. Si une authentification échoue pour une raison non liée (vrai problème de credentials), la prochaine itération reste responsable de la gestion.

## Impact sur l'architecture

**Isolement des sessions** : Le sous-processus Claude exécute désormais sans héritage de session parent, rendant chaque cycle indépendant et reproductible, quelle que soit l'environnement de lancement du daemon.

**Pas d'impact sur les phases** : Le changement est limité à la couche de lancement (`_run_claude`) ; les 7 phases du TRADE_PROMPT et la logique de trading ne changent pas.

**Streaming stdout** : La fonction parse et reloie `stdout` du sous-processus vers un fichier log, préservant tous les signaux et logs pour le debug post-cycle.

## Références CLAUDE.md respectées

- **Règle 4 (Télégram via curl)** : Le helpers.py injecté dans le prompt utilise `curl` pour l'envoi Telegram, non `urllib` (évite les problèmes DNS IPv6).
- **Règle 6 (Convention horaire UTC)** : Les timestamps des cycles sont en UTC (ex. `strftime("%Y%m%d_%H%M%S")`), avec conversion locale à l'affichage Telegram.
- **Règle 5 (Capture stdout/stderr)** : Tous les logs de cycle sont sauvegardés en `logs/stdout/` et `logs/stderr/`, y compris en cas d'erreur. Aucune suppression de logs.
- **Règle 3 (Secrets via .env)** : Les variables d'env (TELEGRAM_TOKEN, MONGODB_URI, etc.) sont lues à runtime depuis `.env`, jamais baked.
