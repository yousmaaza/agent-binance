# PR #433 — Publier l'état du bot dans MongoDB pour le dashboard

> **Mergée le** : 2026-08-28
> **Branche** : `feat/issue-431-dashboard-state-mongo`
> **Issues** : #431

## Contexte

Construction d'un instantané d'état du bot à chaque cycle, destiné à un dashboard externe (consommateur : page web qui affiche l'état en temps réel, pas de liaison directe dans cette PR). L'instantané est stocké dans une collection MongoDB `dashboard_state` unique, distinct de `cycles` (qui enregistre un doc par cycle exécuté). Cet instantané dérivé reconstitue l'état global du bot à partir des fichiers state/ (trade_history.json, maker_watcher_state.json, tp_watcher_state.json) et config.json — jamais une source de vérité, qui reste `state/trade_history.json`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase7_mongo.py` | Modification majeure | Ajout de la reconstruction du document `dashboard_state` lors de chaque Phase 7 (persistance MongoDB) |
| `tests/test_phase7_mongo.py` | Modification majeure | Ajout de 10 tests unitaires couvrant la structure et les agrégations du document `dashboard_state` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_build_dashboard_state()` | Ajoutée | Reconstruit le document unique `dashboard_state` à partir de state/ + config.json (lignes 155–177) |
| `_open_positions()` | Ajoutée | Filtre les positions ouvertes de trade_history.json (lignes 66–79) |
| `_brut_frais_net()` | Ajoutée | Calcule gross/fees/net pour une liste de trades, sans fabrication de frais estimés (lignes 82–88) |
| `_financials()` | Ajoutée | Agrégats PnL par période (0-7j, 8-30j, 30j+), par coin, par close_reason + courbe d'équité (lignes 91–130) |
| `_equity_curve()` | Ajoutée | Réduit la courbe d'équité à un point par jour (dernier cumul du jour) au lieu de 84 trades bruts (lignes 133–152) |
| `_load_json()` | Ajoutée | Chargement JSON sûr avec fallback sur défaut (lignes 54–59) |
| `_pnl()` | Ajoutée | Extracteur de PnL avec valeur par défaut 0 (ligne 62–63) |
| Phase 7 main | Modifiée | Après upsert `cycles`, appelle `db.dashboard_state.update_one({"_id": "current"}, {"$set": dashboard_doc}, upsert=True)` (ligne 186) |

## Décisions techniques notables

- **Document unique avec _id fixe "current"** : L'upsert toujours sur `_id: "current"` garantit qu'un seul document existe dans `dashboard_state`. Le timestamp `updated_at` en ISO 8601 UTC (règle CLAUDE.md #6) indique la fraîcheur pour le consommateur.

- **Instantané DÉRIVÉ jamais source de vérité** : Un commentaire explicite en tête du script rappelle que `state/trade_history.json` fait foi en cas de divergence. Utile pour le debug dashboard si jamais les deux divergent.

- **Équité réduite à un point par jour** : Au lieu de garder les 84 trades individuels (~41 jours distincts en production), on agrège à un cumul par jour. Suffisant pour un tracé lisible, réduit la taille du document ~50%.

- **Frais sans fabrication** : Même logique que `/perf` — si un trade n'a pas `fees_usdc` (ex. SYN, PENDLE backfillés), le gross est dérivé comme `net + frais connus`, jamais de frais estimés. Champ spécial `trades_without_fees` pour tracer ces cas.

- **Sous-ensemble whitelisté de config.json** : Seules 12 clés pilotant le comportement (seuils scores, limites positions, ratios, pourcentages) sont incluses, pas la config entière. Défini par `_CONFIG_KEYS` (lignes 47–51).

- **Watchers et ordres maker pending** : État brut des deux surveillants + ordres maker en attente, réutilisant `load_maker_pending_orders()` existant. Fallback gracieux si fichiers absents.

## Impact sur l'architecture

**Changement isolé dans la Phase 7 (persistance MongoDB)** : Aucun impact sur l'orchestration des phases 0–6 ni sur le polling Telegram. L'upsert `dashboard_state` ajoute un appel MongoDB supplémentaire (~1–2 ms) par cycle, négligeable.

**Impact secondaire positif** : La logique d'agrégation (financials, equity_curve) est maintenant testée et centralisée — peut être réutilisée ultérieurement pour d'autres endpoints.

## Références CLAUDE.md respectées

- **Règle #2 — PROJECT_DIR dynamique** (ligne 21) : Utilise `os.path.dirname(...)` pour localiser les fichiers state/, fonctionne sur Mac et VPS.
- **Règle #6 — UTC interne / affichage local** (ligne 166) : `datetime.now(timezone.utc).isoformat()` pour `updated_at`, ISO 8601 UTC.
- **Règle #5 — Stdout/stderr toujours sauvegardés** : Aucune modification, Phase 7 continue d'écrire les logs cycles.
- **Aucun secret hardcodé** : Config lue depuis `config.json` du PROJECT_DIR, pas de clé API dans le script.
- **Pas de regroupement récursif** : Lecteur JSON (`_load_json`) simple et défensif, gracieux sur erreur.

## Test coverage

**Tests ajoutés (10 nouveaux)** :
- `TestDashboardStateUpsert` : upsert sur `_id="current"`, métadonnées cycle + timestamp récent
- `TestDashboardStateOpenPositions` : champs des positions ouvertes (coin, entrée, stop, cible, qty, frais, maker_or_taker)
- `TestDashboardStateNoOpenPositions` : historique vide ou uniquement clos → liste vide sans erreur
- `TestDashboardStateFinancials` : agrégats global/par période/par coin/par close_reason, equity_curve réduite à 1 point/jour
- Tests d'edge cases : trades sans `fees_usdc`, fichiers watcher manquants, config vide

**Suite totale** : 236 tests (226 avant + 10 nouveaux), tous verts. Aucune régression.
