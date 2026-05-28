# PR #141 — Documenter les TYPE_A/B/C/D de skip_type en CLAUDE.md

> **Mergée le** : 2026-05-28
> **Branche** : `feat/issue-128-documenter-skip-types`
> **Issues** : #128

## Contexte

À chaque cycle de trading, le bot classe chaque coin candidat par une décision (BUY, HOLD, SKIP, SELL) et un `skip_type` si le coin est skippé. Ces informations sont persistées dans MongoDB (`cycles.skip_type`, `cycles.skip_detail`) et listées dans `state/cycle_log.jsonl`. Jusqu'à présent, les 4 types de skip (TYPE_A, TYPE_B, TYPE_C, TYPE_D) n'étaient pas documentés dans CLAUDE.md, ce qui rendait difficile le debug des cycles échoués pour un opérateur non-technique.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `CLAUDE.md` | Documentation (ajout section) | Ajoute 29 lignes documentant les skip_types et leur utilité |

### Contenu ajouté

Nouvelle section "Cycles de trading : skip_type et skip_detail" dans CLAUDE.md (après la section sur le `TRADE_PROMPT`) :

1. **Les 4 types de skip** : tableau explicatif avec phase, déclencheur et explication pour chaque type :
   - **TYPE_A** (Phase 3 — Scoring) : Score insuffisant, positions max, ou corrélation excessive
   - **TYPE_B** (Phase 4 — Sizing) : Montant < 11 USDC ou prix_stop invalide
   - **TYPE_C** (Phase 5 — Exécution) : Drift prix, solde insuffisant, ou fill partiel MARKET
   - **TYPE_D** (Phase 1 — Scan) : Paire non tradable USDC ou volume 24h insuffisant

2. **skip_detail associé** : exemples de texte libre pour chaque type, montrant le motif exact du skip dans le contexte du cycle

3. **Utilité pour le debug** : trois cas d'usage pratiques :
   - Distinguer les skips volontaires (TYPE_A) des skips techniques (TYPE_C/D)
   - Tracer les pertes d'opportunité systématiques
   - Optimiser la stratégie en analysant la distribution des skip_types

## Décisions techniques notables

- **Placement dans CLAUDE.md** : la section est insérée après "Quand modifier le `TRADE_PROMPT`" et avant "Toute modification du code passe par l'agent `binance-dev`", car elle décrit une propriété du système de classification du bot (métadonnée persistée dans MongoDB)
- **Format tableau + exemples** : les 4 types sont présentés en tableau pour clarté, avec des exemples concrets de `skip_detail` pour chaque type, rendant la documentation immédiatement utile pour un débogageur
- **Cible : opérateur non-technique** : la documentation évite le jargon interne (ex. "scoring" vs "rating"), utilise des formulations vulgarisées, et explique l'utilité pratique (debug, optimisation)

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. La PR ne modifie aucun code applicatif (`scripts/webhook_server.py`, `config.json`), ne change aucun flux de données, et n'introduit pas de nouvelles dépendances ou fonctions. Elle **clarifie uniquement** la sémantique d'une métadonnée existante (`skip_type`) qui est déjà persistée dans MongoDB et listée dans les logs de cycle. Cela rend la documentation de CLAUDE.md plus complète sans altérer le comportement du système.

## Références CLAUDE.md respectées

- **Règle 8** (Modifications de code via `binance-dev`) : Cette PR est une modification de CLAUDE.md lui-même, qui est explicitement exclue de cette règle (exception autorisée pour "Mise à jour de `CLAUDE.md` lui-même (méta-règles, pas de code)")
- Pas de modification de code applicatif (`scripts/webhook_server.py`, `config.json`) — la documentation est purement informationnelle
