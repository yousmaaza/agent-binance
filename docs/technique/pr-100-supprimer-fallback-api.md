# PR #100 — Supprimer le fallback API — ne pas charger ANTHROPIC_API_KEY dans le bot

> **Mergée le** : 2026-05-24
> **Branche** : `feat/issue-99-supprimer-fallback-api`
> **Issues** : #99

## Contexte

Le projet avait auparavant un mécanisme de fallback API : en cas de dépassement de quota abonnement Claude, le bot tentait de reprendre la session avec une clé API pay-per-use. Cette approche était complexe, source de détections de patterns d'erreur fragiles, et ajoutait du code de gestion de session.

La décision prise : **abandonner ce fallback et fonctionner 100% en mode abonnement**. Le bot cesse complètement en cas de quota épuisé plutôt que de basculer vers un modèle pay-per-use.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/env.py` | Modification | Ajout du blocage d'`ANTHROPIC_API_KEY` au chargement .env |
| `binance-bot/config/llm.py` | Modification | Suppression de `CLAUDE_MODEL_FALLBACK` (unused) |
| `binance-bot/orchestration/runner.py` | Modification | Suppression du bloc fallback API (30 lignes), simplification de la logique d'erreur |
| `binance-bot/orchestration/stream_parser.py` | Modification | Suppression du paramètre `session_cb` (lié au `--resume`) |
| `.env.example` | Modification | Commentaire de `ANTHROPIC_API_KEY` avec note explicative |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_load_env()` | Modifiée | Respecte désormais `KEYS_NEVER_LOAD` — n'injecte jamais `ANTHROPIC_API_KEY` dans `os.environ` |
| `run_trade_workflow()` | Modifiée | Envoie un message Telegram dédié en cas de quota épuisé (ligne 71-74) ; suppression du fallback retry |
| `_update_billing_mode_in_mongo()` | Modifiée | Passe toujours `"abonnement"` au lieu d'une logique conditionnelle `"api"` / `"abonnement"` |
| `parse_stream_event()` | Modifiée | Suppression du paramètre `session_cb` |

## Décisions techniques notables

- **Blocage au chargement .env** : plutôt que de charger `ANTHROPIC_API_KEY` puis de l'ignorer, on l'exclut dès le loader via `KEYS_NEVER_LOAD`. C'est une barrière de sécurité qui empêche toute tentative accidentelle de l'utiliser.
- **Détection du quota conservée** : `RESOURCE_ERROR_PATTERNS` reste dans `config/llm.py` car il est utilisé par `is_resource_error()` pour détecter le message d'erreur Anthropic et envoyer une notification Telegram claire.
- **Message d'erreur user-friendly** : en cas de quota épuisé, le bot envoie un message Telegram explicite ("⛔ Quota abonnement Claude épuisé — cycle annulé") plutôt que de laisser une erreur technique.
- **Simplification de la logique** : suppression de tout le code de gestion de session `--resume` et de `fallback_used`, réduisant la surface de bug.

## Impact sur l'architecture

- **Suppression d'une branche conditionnelle dans le flux d'erreur** : `_handle_error()` est maintenant plus simple — pas de retry avec fallback.
- **Pas de changement au flux nominal** : quand le quota est suffisant, le comportement est identique.
- **Évolution de `_update_billing_mode_in_mongo()`** : elle reçoit toujours `"abonnement"` au lieu de calculer la valeur conditionnellement, ce qui simplifie les appels et la log Mongo.

## Références CLAUDE.md respectées

- **Règle 1 (Telegram via curl)** : inchangé — toujours via `curl` dans `send_telegram()`.
- **Règle 2 (Secrets via .env)** : respecté — `ANTHROPIC_API_KEY` est explicitement **exclue** du chargement au lieu d'être stockée et ignorée.
- **Règle 5 (UTC interne)** : inchangé — les timestamps restent UTC.
- **Règle 6 (Auto-scheduler dans main_loop)** : inchangé — l'auto-scheduler demeure dans `webhook_server.py`.

## Contexte additionnel

L'issue #52 ("Clarifier les conditions du fallback") devient obsolète après cette PR, car le fallback n'existe plus. Aucun changement de comportement en fonctionnement normal (quota non épuisé).
