# PR #22 — [M1] Ajouter PROMPT_VERSION (sha1) dans Mongo cycles

> **Mergée le** : 2026-05-21
> **Branche** : `feat/issue-3-ajouter-prompt-version-sha1-dans-mongo`
> **Issues** : #3

## Contexte

Sans traçabilité de la version du prompt utilisé pour un cycle, il est impossible de savoir si deux cycles comparables ont été produits avec le même comportement Claude ou si une modification du `TRADE_PROMPT` a introduit un changement silencieux. Cette PR répond au ticket #3 (milestone M1) en ajoutant un champ `prompt_version` dans chaque document MongoDB de la collection `cycles`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification | Calcul du hash SHA-1 du template au boot + injection dans le document Mongo à chaque cycle |

### Fonctions ajoutées / modifiées

| Fonction / Variable | Action | Description |
|---|---|---|
| `PROMPT_VERSION` (variable module) | Ajoutée — ligne :373 | Constante calculée une seule fois au boot : `hashlib.sha1(_TRADE_PROMPT_TEMPLATE.encode(), usedforsecurity=False).hexdigest()[:8]` sur le template **brut** avant toute substitution |
| `run_trade_workflow()` | Modifiée — ligne :653 | Injection de `__PROMPT_VERSION__` dans le prompt via `.replace("__PROMPT_VERSION__", PROMPT_VERSION)` au même endroit que `__CYCLE_ID__` (ligne :681-682) |
| `_TRADE_PROMPT_TEMPLATE` | Modifiée (Phase 7) — ligne :314 | Ajout du champ `"prompt_version": "__PROMPT_VERSION__"` dans le document Python `doc` construit avant l'upsert MongoDB |

## Décisions techniques notables

- **Hash sur le template brut** : `PROMPT_VERSION` est calculé sur `_TRADE_PROMPT_TEMPLATE` (avant tout `.replace()`). Cela garantit que la valeur est identique entre cycles si le template n'a pas changé, indépendamment des valeurs injectées (`__CYCLE_ID__`, `__BOT_TOKEN__`, etc.).
- **Calcul au boot, pas à chaque cycle** : le hash est une constante module-level. Recalculer à chaque cycle serait équivalent mais inutilement coûteux ; en pratique le template ne change qu'avec un redémarrage du bot.
- **`usedforsecurity=False`** : paramètre explicite pour indiquer que SHA-1 est utilisé ici comme fingerprint de contenu, pas pour un usage cryptographique. Évite les avertissements liés aux vérifications FIPS sur certains systèmes Python 3.11.
- **8 caractères hex** : suffisant pour distinguer des versions de prompt en conditions normales (collision improbable sur un usage pratique), tout en gardant le champ court et lisible dans Mongo.

## Impact sur l'architecture

La PR est isolée dans le pipeline de persistance MongoDB (Phase 7 du prompt). Elle n'ajoute aucun nouveau composant externe, n'introduit pas de nouvelle dépendance (`hashlib` est un module standard Python), et ne modifie pas le flux d'exécution principal. Le seul impact observable est l'apparition du champ `prompt_version` dans chaque document de la collection `cycles`.

Note : le ticket #3 mentionne aussi l'ajout de `prompt_version` dans les heartbeats JSONL locaux (`logs/cycle_<id>.json`) — ce point est reporté au ticket #5 (milestone heartbeats).

## Références CLAUDE.md respectées

- **Règle 2 (aucun secret hardcodé)** : `hashlib` est un module standard, aucune dépendance externe ajoutée, aucune clé ou valeur sensible introduite.
- **Règle 4 (stdout/stderr toujours capturés)** : non impacté — la capture des logs cycle reste inchangée dans `run_trade_workflow()`.
- **Règle 3 (`PROJECT_DIR` dynamique)** : non impacté — aucun chemin absolu introduit.
