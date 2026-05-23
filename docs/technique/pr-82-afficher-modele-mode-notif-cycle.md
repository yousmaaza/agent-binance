# PR #82 — [M81] Afficher modèle et mode (abonnement/API) dans les notifications de cycle

> **Mergée le** : 2026-05-23
> **Branche** : `feat/issue-81-mode-modele-notification-cycle`
> **Issues** : #81

## Contexte

Jusqu'ici, les notifications Telegram de démarrage de cycle n'indiquaient pas quel modèle Claude était utilisé ni dans quel mode (abonnement vs API). Lorsque le fallback API se déclenchait, le message mentionnait "Sonnet" en dur au lieu du nom réel du modèle. Cette PR rend ces informations visibles à l'utilisateur et les extrait dynamiquement depuis `CLAUDE_CLI_FLAGS` pour qu'elles suivent automatiquement tout changement de modèle dans `config/llm.py`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Modification | Les notifications de démarrage (auto et manuel) et de fallback incluent désormais le nom du modèle Claude actif |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `run_trade_workflow()` | Modifiée | Extrait le modèle depuis `CLAUDE_CLI_FLAGS` et l'injecte dans les messages Telegram de démarrage de cycle et de fallback API |

### Détail des modifications dans `run_trade_workflow()`

**Extraction dynamique du modèle** (2 lignes ajoutées) :

```python
_model_idx = CLAUDE_CLI_FLAGS.index("--model") + 1 if "--model" in CLAUDE_CLI_FLAGS else -1
_model = CLAUDE_CLI_FLAGS[_model_idx] if _model_idx > 0 else "claude (défaut)"
```

Le modèle est extrait de `CLAUDE_CLI_FLAGS` (liste définie dans `binance-bot/config/llm.py`). Si le flag `--model` est absent, la valeur de repli est `"claude (défaut)"`.

**Notifications de démarrage enrichies** (2 lignes ajoutées, une par branche auto/manuel) :

```
🧠 Modèle : claude-sonnet-4-6 (abonnement)
```

**Notification de fallback API** (1 ligne modifiée) :

Avant : `⚠️ Abonnement insuffisant — retry via API Sonnet (cycle …)…`
Après : `⚠️ Abonnement insuffisant — retry via API (claude-sonnet-4-6) (cycle …)…`

La valeur entre parenthèses provient de la constante `CLAUDE_MODEL_FALLBACK` (importée depuis `config/llm.py`) au lieu d'être hardcodée.

## Décisions techniques notables

- **Extraction via index dans une liste** plutôt que via une constante dédiée : `CLAUDE_CLI_FLAGS` est déjà la source de vérité du flag `--model` passé au CLI ; un accès par index évite de dupliquer la valeur dans une variable séparée. Si `--model` disparaît de `CLAUDE_CLI_FLAGS`, la valeur de repli `"claude (défaut)"` garantit que la notification reste valide.
- **`CLAUDE_MODEL_FALLBACK` dans le message fallback** : les deux chemins (abonnement et API) affichent désormais le modèle dynamiquement depuis `config/llm.py`, ce qui garantit la cohérence si le modèle de fallback change.

## Impact sur l'architecture

Changement isolé à la couche notification — pas d'impact sur l'orchestration du cycle, la logique de lock, les logs ou MongoDB. L'information de modèle/mode est désormais visible dans Telegram à chaque démarrage de cycle, ce qui facilite le diagnostic à distance (l'utilisateur sait immédiatement si le cycle a démarré en mode abonnement ou en fallback API).

## Références CLAUDE.md respectées

- **Règle 1 (Telegram via curl)** : les appels Telegram passent par `send_telegram()` (qui shell-out vers `curl`) — aucun `urllib` introduit.
- **Règle 2 (aucun secret hardcodé)** : le nom du modèle est lu depuis `CLAUDE_CLI_FLAGS` (variable de config), jamais hardcodé dans le code.
