# PR #134 — Qualifier les except génériques par des types spécifiques

> **Mergée le** : 2026-05-28
> **Branche** : `feat/issue-27-remplacer-bare-except`
> **Issues** : #27

## Contexte

Ticket de refactoring pour améliorer la gestion d'erreurs en remplaçant les handlers `except Exception:` généralistes par des types d'exception précis. Cela améliore la diagnostique et facilite le debugging en capturant des erreurs spécifiques selon le contexte (E/S fichier, parsing JSON, etc.) plutôt que de masquer toutes les exceptions.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/lock.py` | Modification | Qualification des exceptions pour les opérations fichier/JSON |
| `binance-bot/core/telegram.py` | Modification | Qualification des exceptions pour get_offset() et journalisation d'erreur |
| `binance-bot/orchestration/runner.py` | Modification | Qualification des exceptions dans fonctions I/O (coût API, erreur handler) |

### Fonctions modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `is_locked()` | `core/lock.py:13–32` | Modifiée | Exception handler qualifié : `(OSError, json.JSONDecodeError)` avec logging |
| `get_offset()` | `core/telegram.py:47–53` | Modifiée | Exception handler qualifié : `(OSError, json.JSONDecodeError)` avec logging |
| `_update_cost_in_mongo()` | `runner.py:122–140` | Modifiée | Exception handler qualifié : `(OSError, ValueError)` pour lectures fichier + parsing regex |
| `_handle_error()` | `runner.py:151–166` | Modifiée | Exception handler qualifié : `OSError` pour lectures fichier stderr |

## Décisions techniques notables

- **Spécificité plutôt que généralité** : `(OSError, json.JSONDecodeError)` pour les opérations JSON/fichiers, `(OSError, ValueError)` pour les lectures + parsing numérique. Les handlers `Exception` restants (ex. Mongo update fallback) sont justifiés car ils capturent des erreurs réseau ou schema imprévisibles.
- **Journalisation obligatoire** : chaque handler spécifique logue l'exception capturée avec `logger.warning()` ou `logger.error()`, facilitant le debug en production.
- **Pas de suppression de handlers généralistes** : les `except Exception` dans les handlers Mongo (`_update_billing_mode_in_mongo()`, fallback dans `_handle_error()`) restent génériques car le contexte (erreurs réseau, timeouts, schema incompatibilité) justifie de capturer large.

## Impact sur l'architecture

Changement isolé à la gestion d'erreurs : aucun impact sur le flux d'exécution, les phases de trading ou la persistance. L'amélioration est purement diagnostique — les erreurs qui auraient été silencieuses ou peu informatives sont désormais loggées avec contexte précis.

## Références CLAUDE.md respectées

- **Pas de violation des règles 1–8** : aucune modification de `webhook_server.py` (legacy), des secrets (`.env`), des chemins dynamiques ou du venv
- **Modularisation** : les handlers sont dans des modules spécialisés (`core/lock.py`, `core/telegram.py`, `orchestration/runner.py`), respectant la séparation des préoccupations
