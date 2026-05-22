# PR #50 — [M1] Fallback abonnement→API Sonnet si ressource insuffisante

> **Mergée le** : 2026-05-22
> **Branche** : `feat/issue-49-fallback-abonnement-api-sonnet`
> **Issues** : #49

## Contexte

Lorsque le bot tourne en mode abonnement Claude Code, le subprocess Claude primaire peut échouer avec des erreurs de type "Credit balance is too low", "rate_limit_error" ou "overloaded_error" — des erreurs de ressource temporaires qui ne dépendent pas de la logique de trading. Plutôt que de laisser le cycle en erreur, cette PR ajoute un mécanisme de retry automatique via l'API Sonnet payante (`claude-sonnet-4-6`) dès qu'une telle erreur est détectée et que `ANTHROPIC_API_KEY` est disponible dans `.env`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification | +52 lignes : nouvelle constante, nouvelle fonction, logique de fallback dans `run_trade_workflow()`, message de mode dans `main_loop()` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_RESOURCE_ERROR_PATTERNS` | Ajoutée (constante module) | Liste des 6 patterns de chaîne indiquant une erreur de ressource Claude (credit insuffisant, rate limit, surcharge) — déclarée au niveau module pour être facilement extensible |
| `_is_resource_error(stdout_path)` | Ajoutée | Lit le fichier `logs/stdout/cycle_*.log` et retourne `True` si l'un des patterns de `_RESOURCE_ERROR_PATTERNS` y apparaît — gère silencieusement les erreurs de lecture (fichier absent, permissions) |
| `run_trade_workflow()` | Modifiée | (1) Construit `sub_env` en retirant `ANTHROPIC_API_KEY` avant de lancer le subprocess primaire pour forcer le mode abonnement Claude Code. (2) Après la fin du subprocess primaire, si `exit_code != 0` et `_is_resource_error()` est vrai et `ANTHROPIC_API_KEY` est présent, lance un retry avec `--model claude-sonnet-4-6` et l'env complet (API key incluse), en réutilisant le même `cycle_id` et les mêmes fichiers log (écrasés). (3) Si erreur ressource mais `ANTHROPIC_API_KEY` absent : warning logger uniquement, pas de retry |
| `main_loop()` | Modifiée | Le message de log `Subprocess Claude : {claude_mode}` reflète maintenant le mode réel : `"abonnement (fallback API Sonnet si ressource insuffisante)"` si `ANTHROPIC_API_KEY` est présent, `"abonnement Claude Code"` sinon |

## Décisions techniques notables

- **Isolation du subprocess primaire de l'API key** : le subprocess primaire reçoit un `sub_env` dont `ANTHROPIC_API_KEY` a été retiré (`sub_env.pop`), même si le process parent l'a chargé via `_load_env()`. Cela garantit que le mode abonnement est utilisé par défaut, quelle que soit la présence de la clé dans `.env`. L'API key reste disponible dans `os.environ` du process parent pour le fallback.

- **Réutilisation du `cycle_id` et écrasement des logs au retry** : le retry ne crée pas de nouveau `cycle_id`, ne repose pas de lock et ne relance pas le watchdog — conformément au ticket. Les fichiers `logs/stdout/` et `logs/stderr/` sont ouverts en mode `"w"`, effaçant la sortie du premier essai. Cette approche simplifie le suivi Mongo (un seul document par `cycle_id`) mais signifie que la sortie brute de l'essai primaire est perdue.

- **Détection basée sur le contenu stdout** : la détection d'erreur de ressource se fait en lisant le fichier stdout déjà écrit, et non via le code de retour seul. Cela permet de distinguer une erreur de ressource Claude d'un autre type d'échec (bug réseau, erreur Binance) qui aurait aussi `exit_code != 0`.

- **Condition `elif` pour le warning** : si la condition de fallback n'est pas remplie faute de clé API, un `logger.warning()` est émis sans notification Telegram — l'absence de clé est un état de configuration connu, pas une alerte urgente.

## Impact sur l'architecture

Le flux `run_trade_workflow()` ajoute une nouvelle branche conditionnelle après la fin du subprocess primaire :

```
subprocess primaire (sub_env sans ANTHROPIC_API_KEY)
    │ exit_code != 0 ET _is_resource_error()
    │ ET ANTHROPIC_API_KEY présent
    ▼
subprocess fallback (os.environ.copy() avec ANTHROPIC_API_KEY)
    --model claude-sonnet-4-6
    même cycle_id / mêmes logs écrasés
```

Le comportement nominal (exit_code = 0 ou erreur non-ressource) est inchangé. La branche fallback est optionnelle et conditionnée à la présence de `ANTHROPIC_API_KEY` dans l'environnement runtime — le bot reste fonctionnel sans cette clé.

## Références CLAUDE.md respectées

- **Règle 2 — Secrets via `.env`** : `ANTHROPIC_API_KEY` est lu via `os.environ.get()`, jamais hardcodé. La clé est chargée par `_load_env()` au démarrage dans `os.environ`.
- **Règle 4 — Stdout/stderr toujours capturés** : le subprocess de retry ouvre aussi `stdout_path` et `stderr_path` en buffering=1, garantissant la capture même en cas d'échec du retry.
- **Règle 3 — `PROJECT_DIR` dynamique** : le `cwd=PROJECT_DIR` du subprocess de retry utilise la même variable calculée dynamiquement.
