# PR #65 — [hotfix] Ajouter "session limit" dans _RESOURCE_ERROR_PATTERNS

> **Mergée le** : 2026-05-22
> **Branche** : `fix/session-limit-fallback-pattern`
> **Issues** : sans ticket board — fix d'urgence déclenché par le cycle 20260522_140354

## Contexte

Le cycle automatique `20260522_140354` a échoué avec exit code 1 sans déclencher le fallback vers le modèle Sonnet via API. L'API Claude avait renvoyé le message `"You've hit your session limit · resets 6:50pm (Europe/Paris)"`, mais ce pattern n'était pas présent dans `_RESOURCE_ERROR_PATTERNS`. En conséquence, `_is_resource_error()` retournait `False`, et `run_trade_workflow()` traitait la sortie comme une erreur fatale (pas de retry Sonnet API).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Ajout de 2 patterns dans `_RESOURCE_ERROR_PATTERNS` | Le fallback vers `claude-sonnet-4-6` via API se déclenche désormais aussi sur les erreurs de limite de session |

### Constante modifiée

| Élément | Action | Description |
|---|---|---|
| `_RESOURCE_ERROR_PATTERNS` (ligne :934) | Modifiée | Ajout de `"You've hit your session limit"` (forme longue) et `"session limit"` (forme courte pour couvrir les variantes futures) |

**État avant :**

```python
_RESOURCE_ERROR_PATTERNS = [
    "Credit balance is too low",
    "rate_limit_error",
    "overloaded_error",
    "Your account has hit",
    "quota exceeded",
    "This model is currently overloaded",
]
```

**État après :**

```python
_RESOURCE_ERROR_PATTERNS = [
    "Credit balance is too low",
    "rate_limit_error",
    "overloaded_error",
    "Your account has hit",
    "quota exceeded",
    "This model is currently overloaded",
    "You've hit your session limit",
    "session limit",
]
```

## Décisions techniques notables

- **Deux patterns au lieu d'un** : la forme courte `"session limit"` est ajoutée en plus de la forme exacte `"You've hit your session limit"` pour absorber d'éventuelles reformulations futures du message Claude sans avoir à modifier ce fichier à nouveau. Risque de faux positif estimé négligeable (le message doit figurer dans un log stdout de Claude CLI).
- **Pas de regex** : la cohérence avec les 6 patterns existants (tous des sous-chaînes simples) a été maintenue — `any(p in content for p in _RESOURCE_ERROR_PATTERNS)` reste lisible et rapide sur un fichier texte de quelques Ko.

## Impact sur l'architecture

Changement isolé sur la liste de détection des erreurs de ressource Claude. La logique de fallback vers `claude-sonnet-4-6` (PR #50) est inchangée — ce hotfix étend uniquement le périmètre de déclenchement de ce fallback à la classe d'erreur "session limit".

## Références CLAUDE.md respectées

- **Règle 2 (secrets via `.env`)** : aucun nouveau secret introduit. `ANTHROPIC_API_KEY` (déjà documentée) reste la condition du fallback.
- **Règle 4 (capture stdout/stderr toujours)** : non touchée — la capture des logs reste le seul moyen de détecter a posteriori la cause d'un cycle raté.
