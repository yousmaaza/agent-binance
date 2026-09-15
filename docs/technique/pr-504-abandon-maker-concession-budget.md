# PR #504 — [M1] Abandonner l'entrée maker sur budget de concession dépassé

> **Mergée le** : 2026-09-15
> **Branche** : `feat/issue-502-abandon-maker-concession-budget`
> **Issues** : #502

## Contexte

Le budget de concession (`maker_max_concession_pct`) était historiquement interprété comme un déclencheur : dépassement = repli BUY MARKET. Mais cette logique confondait deux phénomènes distincts :
- **Dépassement de concession** : le prix a fui par rapport au prix initial, signale un changement de condition de marché (raison d'acheter invalidée)
- **Délai épuisé** : le temps maximal est écoulé, mais le prix tient toujours l'hypothèse de trade (raison d'acheter persiste)

Cette PR sépare ces deux branches : la concession devenant un **garde-fou** (abandon si dépassé), seul le délai conservant le droit au repli marché.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/maker_watcher.py` | Refactorisation | Séparation concession/timeout ; nouveau handler et callback pour les abandons |
| `binance-bot/storage/mongo.py` | Extension | Nouvelle méthode `save_maker_abandoned_entry()` pour tracer les abandons |
| `docs/strategie.html` | Mise à jour | Diagramme et note refactorisés pour clarifier le nouvel arbre de décision |
| `docs/strategie.md` | Régénération | Conséquence de la modification du `.html` |
| `tests/test_maker_watcher.py` | Extension | Nouveaux tests pour l'abandon sur concession + non-régression timeout |
| `tests/test_storage_mongo.py` | Extension | Tests de `save_maker_abandoned_entry()` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_record_concession_abandon()` | Ajoutée | Trace (Telegram + Mongo) un abandon d'entrée sur dépassement de concession. Suit le motif de `_publish_pending_orders_if_changed` : Mongo est best-effort (warning en cas d'échec, jamais d'exception remontée). |
| `_handle_concession_exceeded()` | Ajoutée | Gestionnaire spécialisé pour le dépassement de concession : annule l'ordre, résout le remplissage partiel éventuel, puis appelle le callback `_record_concession_abandon()` si abandon total. |
| `_cancel_and_resolve()` | Modifiée | Ajout du paramètre optionnel `on_abandon` (callback) pour tracer les abandons avec contexte. Toujours `None` pour les cas existants (prix invalidé). |
| `_resolve_after_cancel()` | Modifiée | Ajout du paramètre optionnel `on_abandon` propagé par `_cancel_and_resolve()`. |
| `_handle_timeout()` | Clarifiée | Appelée désormais seulement quand la concession est sous le budget ; docstring implicite du watcher clarifiée. |
| `_maker_watcher_tick()` | Modifiée | Logique de la boucle réorganisée : vérification de concession AVANT timeout (ordre de décision respectant l'arbre de priorité). Ajout du décompte `abandoned_delta` pour tracer les abandons. |
| `_write_watcher_state()` | Modifiée | Ajout du paramètre `abandoned_delta` pour persister les compteurs d'abandon dans l'état du watcher. |

### Points d'architecture notables

1. **Séparation des cas d'annulation** :
   - Cas 3 (prix invalidé) → `_handle_invalidated_price()` → pas de market fallback, pas d'abandon tracé
   - Cas 4 (concession épuisée) → `_handle_concession_exceeded()` → pas de market fallback, abandon tracé via callback
   - Cas 5 (délai épuisé) → `_handle_timeout()` → market fallback conservé si `vol_exec == 0`

2. **Persistance des abandons (Mongo)** :
   - Nouvelle table `watchers.maker_abandoned_entries` (borné à 20 entrées pour l'historique dashboard)
   - Chaque entrée contient : coin, pair, prix initial/courant, concession dépassée, quantité, notional, timestamp
   - Utilisée par le dashboard (#503) pour suivi — la donnée est séparable du statut du cycle (Phase 7) pour permettre une publication immédiate

3. **Notification utilisateur** :
   - Message Telegram cohérent pour tous les abandons : `⏭️ {coin} : signal invalidé pendant la chasse maker`
   - Détail différencié selon le motif (prix invalidé, concession dépassée, timeout+no fill)

## Décisions techniques notables

- **Callback `on_abandon` plutôt que branche if/else** : séparer la traçabilité métier (quoi et comment afficher/persister) de la logique de décision de workflow. Plus composable que des `if outcome == "abandoned"` disséminés.
- **Mongo best-effort sans upsert** : motif identique à `save_maker_pending_orders()` (PR #498). La persistance du watcher est un confort pour le dashboard ; elle ne bloque jamais l'annulation de l'ordre ni la décision fonctionnelle.
- **Décompte `abandoned_delta` dans l'état du watcher** : permet un suivi quantitatif (observable dashboard) sans charger le cycle complet en Mongo.

## Impact sur l'architecture

**Impact limité et isolé au maker watcher** :
- Le cycle complet (Phases 0-7) reste inchangé — l'arbre de décision n'affecte que le polling des ordres limite en attente
- Aucun changement dans `phase5_execution.py` (pose de l'ordre) ni dans les phases suivantes
- Les tests non liés au watcher passent intégralement (régression vérifiée : 617 passed)

**Données nouvelles pour le dashboard** :
- `watchers.maker_abandoned_entries` utilisable immédiatement pour un suivi a posteriori (#503)
- Horodatage dédié `watchers.maker_abandoned_updated_at` pour distinguer les updates du watcher et de la Phase 7

## Références CLAUDE.md respectées

- **Règle 1 — Venv + Python 3.11** : tous les tests via `.venv/bin/python -m pytest`
- **Règle 4 — Telegram via curl** : fonction existante `send_telegram()` continue d'être utilisée
- **Règle 5 — Logs stdout/stderr** : les logs du cycle sont capturés, les avertissements Mongo dans `logger.warning()` de manière cohérente
- **Règle 6 — UTC interne / local à l'affichage** : horodatages en UTC ISO (`isoformat()`), notification Telegram lisible en FR
- **Règle 8 — Mise à jour docs/strategie.html** : diagramme et note refactorisés pour clarifier le nouvel arbre de décision ; `.md` régénéré
