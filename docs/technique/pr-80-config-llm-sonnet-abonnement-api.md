# PR #80 — [M79] Forcer claude-sonnet-4-6 sur abonnement et API fallback

> **Mergée le** : 2026-05-23
> **Branche** : `feat/issue-79-config-llm-sonnet-abonnement-api`
> **Issues** : #79

## Contexte

Le CLI Claude, lorsqu'il est utilisé sous abonnement Max, sélectionne Opus par défaut — modèle plus puissant mais aussi plus lent et plus coûteux. La PR #50 avait introduit le fallback API vers `claude-sonnet-4-6`, mais le subprocess primaire (mode abonnement) restait en Opus. Ce ticket force explicitement Sonnet 4.6 via le flag `--model` dans `CLAUDE_CLI_FLAGS`, garantissant que les deux chemins d'exécution (abonnement et API fallback) utilisent le même modèle.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/config/llm.py` | Modification | `CLAUDE_CLI_FLAGS` inclut désormais `--model claude-sonnet-4-6`, forçant Sonnet sur l'abonnement Max |

### Fonctions ajoutées / modifiées

| Élément | Action | Description |
|---|---|---|
| `CLAUDE_CLI_FLAGS` (constante) | Modifiée | Ajout de `"--model", "claude-sonnet-4-6"` — le subprocess primaire utilise Sonnet au lieu d'Opus (défaut du CLI Max) |
| `CLAUDE_MODEL_FALLBACK` (constante) | Inchangée | Déjà `"claude-sonnet-4-6"` — confirmé aligné avec le flag primaire |

## Décisions techniques notables

- **Flag `--model` dans `CLAUDE_CLI_FLAGS`** : choix de configurer le modèle via le flag CLI plutôt que via une variable d'environnement, pour cohérence avec les autres flags déjà gérés dans cette liste (`--print`, `--verbose`, `--output-format`, `--dangerously-skip-permissions`).
- **Uniformité des deux chemins** : après cette PR, le subprocess primaire (abonnement) et le subprocess de fallback (API `ANTHROPIC_API_KEY`) utilisent tous les deux `claude-sonnet-4-6`, évitant toute divergence de comportement entre les deux modes.
- **Ajout d'un commentaire explicatif** : le commentaire `# --model force Sonnet sur l'abonnement (le CLI choisit Opus par défaut sur Max)` documente le pourquoi de ce flag — sans lui, le comportement du CLI Max serait opaque.

## Impact sur l'architecture

Le subprocess Claude primaire dans `run_trade_workflow()` invoque désormais `claude --print --verbose --output-format stream-json --dangerously-skip-permissions --model claude-sonnet-4-6`. L'architecture reste inchangée — seul le modèle LLM effectivement utilisé change. Le fallback API était déjà Sonnet (via `CLAUDE_MODEL_FALLBACK`) ; le subprocess primaire l'est maintenant également.

## Références CLAUDE.md respectées

- **Règle 8 (workflow ticket → branche → PR)** : ticket #79 créé, branche `feat/issue-79-config-llm-sonnet-abonnement-api`, PR ouverte puis mergée — aucun commit direct sur `main`.
- **Règle 2 (pas de secrets hardcodés)** : le nom du modèle n'est pas un secret, mais il est centralisé dans `binance-bot/config/llm.py` pour éviter la dispersion.
