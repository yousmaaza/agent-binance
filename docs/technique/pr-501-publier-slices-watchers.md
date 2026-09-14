# PR #501 — [BUG] Publier open_positions/closed_trades/financials depuis les watchers

> **Mergée le** : 2026-09-14
> **Branche** : `fix/issue-500-publication-slices-watchers`
> **Issues** : #500

## Contexte

Jusque-là, les slices `dashboard_state` (positions ouvertes, historique des ventes, statistiques financières) n'étaient recalculées et publiées qu'une fois par cycle complet — jusqu'à 4h d'attente entre une fermeture de position par un watcher et son apparition à l'écran du dashboard. Ce retard de visibilité ralentissait le debug et réduisait la réactivité de suivi en temps réel.

La PR #500 demandait : republier ces slices immédiatement après chaque modification de `trade_history` par les watchers (ouvertures maker, clôtures par sortie maker, clôtures sur cible atteinte) — sans attendre le prochain cycle.

## Changements

### Architecture : nouveaux modules et relocalisations

**Nouveau module `binance-bot/core/dashboard_state.py`** (165 lignes)
- Extrait 6 fonctions internes préalablement inscrites dans `phase7_mongo.py` (Phase 7) :
  - `_pnl(t)` — calcul PnL d'un trade
  - `_open_positions(history)` — projection des positions ouvertes (statut="open")
  - `_closed_trades(closed, limit=200)` — historique des ventes avec projection étroite (coin, prix, PnL, hold_hours, raison fermeture, ...)
  - `_brut_frais_net(trades)` — agrégation brut/frais/net sur un ensemble de trades
  - `_equity_curve(closed)` — courbe d'équité agrégée par jour (un point/jour = cumul final du jour)
  - `_financials(closed)` — statistiques PnL (global, par période 0-7d/8-30d/30d+, par coin, par raison de fermeture)
- **Nouvelle fonction publique** : `publish_trade_history_slices(history, label)` — republish ciblé sur `open_positions`, `closed_trades`, `financials` dans `dashboard_state`, appelable par n'importe quel watcher

**Raison de l'extraction** : `phase7_mongo.py` est un script de phase qui lit `sys.argv` et accède `/tmp/` au démarrage, ce qui le rend non-importable par les watchers (threads long-running distincts de l'orchestration Claude).

### Intégrations dans les watchers

| Watcher | Fichier | Changement |
|---|---|---|
| **Maker Watcher** | `core/maker_watcher.py` | +2 lignes : import `publish_trade_history_slices`, appel juste après `save_trade_history()` dans la main loop |
| **Maker Exit Watcher** | `core/maker_exit_watcher.py` | +2 lignes : idem |
| **TP Watcher** | `core/tp_watcher.py` | +2 lignes : idem |

Chaque watcher appelle `publish_trade_history_slices(history, "Maker Watcher" / "Maker Exit Watcher" / "TP Watcher")` juste après avoir modifié et sauvegardé `trade_history`.

### Nouvelle méthode MongoDB

**`MongoRepository.save_trade_history_slices()`** (32 lignes dans `binance-bot/storage/mongo.py:126–156`)

Pattern identique à `save_maker_pending_orders()` (PR #498) — écriture MongoDB **ciblée** :
- `$set` partiel : mise à jour des trois clés `open_positions`, `closed_trades`, `financials` + timestamp dédié `watchers.trade_history_slices_updated_at`
- **Jamais une reconstruction** du document entier — préserve les champs de la Phase 7 (`config`, `watchers.maker_pending_orders`, ...)
- **Sans `upsert=True`** : si `dashboard_state` n'existe pas encore (avant le premier cycle), aucun document vide n'est créé (la Phase 7 crée le document complet au premier cycle)
- **Exceptions silencieuses** : tout échecc Mongo est loggé avec `logger.warning()` mais jamais remonté à la boucle du watcher (robustesse : les watchers posent des vrais ordres, leur availability prime)

### Dashboard : fraîcheur des données par tranche

**Nouveau helper dans `dashboard/viewdata.py`** (18 lignes)
- `trade_history_freshness(watchers, dashboard_updated_at, stale_threshold_minutes)` — même patron que `maker_freshness()` #498
- Identifie l'horodatage spécifique `watchers.trade_history_slices_updated_at` (date de dernière republication par les watchers)
- Repli sur l'horodatage global si jamais aucun watcher n'a publié (avant #500, ou panne)

**Affichage du HTML** (`dashboard/templates/dashboard.html`)
- Sections "Positions ouvertes" et "Ventes" : badge "donnée périmée (mise à jour il y a Xh)" quand `is_stale: true` pour cette tranche

### Fichiers modifiés — Résumé

| Fichier | Type | Lignes | Impact |
|---|---|---|---|
| `binance-bot/core/dashboard_state.py` | **AJOUTÉ** | +165 | Module partagé de dérivation slices |
| `binance-bot/core/maker_watcher.py` | Modifié | +2 | Appel `publish_trade_history_slices` après save |
| `binance-bot/core/maker_exit_watcher.py` | Modifié | +2 | Appel `publish_trade_history_slices` après save |
| `binance-bot/core/tp_watcher.py` | Modifié | +2 | Appel `publish_trade_history_slices` après save |
| `binance-bot/core/phases/phase7_mongo.py` | Modifié | -136 / +2 | Import depuis `dashboard_state`, utilise fonctions extraites |
| `binance-bot/storage/mongo.py` | Modifié | +32 | Nouvelle méthode `save_trade_history_slices()` |
| `dashboard/app.py` | Modifié | +4 | Import + calcul fraîcheur tranche, passage aux templates |
| `dashboard/viewdata.py` | Modifié | +18 | Nouveau helper `trade_history_freshness()` |
| `dashboard/templates/dashboard.html` | Modifié | +12 | Affichage badge "périmée" si besoin |
| **Tests** | Ajoutés/Modifiés | +608 | +25 tests (609 vs 584 baseline), 0 régression |

## Décisions techniques notables

- **Extraction de fonctions plutôt que duplication** — les 6 fonctions de calcul vivaient jusque-là uniquement dans le script `phase7_mongo.py`. Les copier/coller aurait créé de la dette de sync. Elles sont donc extraites dans un module dédié importable.

- **Robustesse des watchers prioritaire** — les exceptions Mongo pendant une republication sont loggées mais jamais remontées. Les watchers posent de vrais ordres ; un bug d'affichage MongoDB ne doit jamais bloquer ou ralentir un watcher.

- **`upsert=False` obligatoire** — selon #498, créer un document `dashboard_state` amputé (sans `config`, sans `watchers.maker_pending_orders`) donnerait une fausse impression de complétude côté dashboard. Seule la Phase 7 crée le document au complet.

- **Timestamp dédié par tranche** — `watchers.trade_history_slices_updated_at` date précisément cette republication, distinct de `updated_at` global. Permet au dashboard de détecter si la tranche est " périmée " indépendamment de l'horodatage du cycle.

## Impact sur l'architecture

**Avant PR #501** :
```
Watcher modifie trade_history
    ↓ (sauvegarde locale)
trade_history.json ← mis à jour immédiatement
    ↓
dashboard_state Mongo ← attend jusqu'à 4h (Phase 7 suivante)
    ↓
Dashboard affiche les changements (retard visible)
```

**Après PR #501** :
```
Watcher modifie trade_history
    ├─ sauvegarde locale → trade_history.json
    └─ publish_trade_history_slices() → Mongo dashboard_state IMMÉDIATEMENT
        └─ Dashboard affiche les changements en temps quasi-réel (~100ms après la modification)
```

Le flux reste tributaire de la Phase 7 pour le document de cycle (`db.cycles`), mais les données affichées au dashboard sont maintenant à jour sans délai.

**Coût architectural** : minime. Les watchers importent un module de plus ; aucune nouvelle dépendance externe, aucun changement au contrat prompt/script.

## Références CLAUDE.md respectées

- **Minimalisme** : code minimum pour republier (pas de nettoyage collatéral, pas de refactoring spéculatif des watcher eux-mêmes)
- **Aucun secret hardcodé** : tous les paramètres MongoDB viennent du `.env` via `core/env.py:MONGO_URI` + `MONGO_DB`
- **Modifications chirurgicales** : trois changements identiques (+2 lignes chacun) dans les trois watchers, isolés à l'endroit du `save_trade_history()` existant
- **Robustesse des watcher** : exceptions silencieuses (pas de remontée, juste logs)
- **État persistant** : `dashboard_state` Mongo reste un document DÉRIVÉ (jamais source de vérité), la source est toujours `state/trade_history.json`

## Tests

- **PR #501 ajoute 25 nouveaux tests** (609 vs 584 baseline main) :
  - `TestDashboardStateFullDocumentUnchangedByExtraction` — caractérisation key-by-key que la Phase 7 produit exactement le même document après extraction
  - `TestMakerWatcherPublishesTradeHistorySlices` — une position ouverte par le watcher apparaît sans attendre le cycle suivant
  - `TestSaveTradeHistorySlices::test_partial_set_preserves_the_rest_of_the_document` — les écritures ne écrasent aucun champ Phase 7
  - `test_mongo_failure_during_publication_does_not_interrupt_the_watcher` — échecc Mongo ne remonte jamais dans la boucle
  - `TestPositionsAndSalesFreshness` — badge "périmée" affiché correctement en HTML produit
- **0 régression** : baseline `main` à 584 tests passants, PR #501 à 609 (108 erreurs ruff identiques)
- **Valeurs retenues** : `CLOSED_TRADES_LIMIT=200` (87 ventes en 4 mois, marge large) ; `equity_curve` agrégée par jour (84 trades → 1 point/jour, lisibilité sans gonfler le document #431)
