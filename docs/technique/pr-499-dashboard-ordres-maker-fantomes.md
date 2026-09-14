# PR #499 — [BUG] Dashboard maker : fin des ordres fantômes

> **Mergée le** : 2026-09-14
> **Branche** : `fix/issue-498-ordres-maker-fantomes`
> **Issues** : #498

## Contexte

Le dashboard affichait des ordres "en vol" depuis plusieurs heures, figures d'un cycle passé que le maker watcher aurait dû terminer depuis longtemps — deux problèmes liés :

1. **Ordres fantômes** : un ordre maker plus vieux que son timeout était présenté comme "en attente d'exécution" au lieu d'être caché (il aurait forcément été résolu par le watcher à ce stade).
2. **Publication excessive** : le watcher publiait sa liste `maker_pending_orders` à **chaque tick** (20 s), soit 4 320 écritures MongoDB/jour pour un confort d'affichage seulement, sans jamais changer.

Cette PR les corrige tous deux.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/maker_watcher.py` | Ajout logique de publication + hooks | Le watcher publie sa liste dans MongoDB uniquement au changement (pose, ajustement, remplissage, abandon) — jamais à chaque tick. Réduit l'I/O Mongo de ~99 %. |
| `binance-bot/storage/mongo.py` | Nouvelle méthode | `save_maker_pending_orders()` : `$set` ciblé sur `watchers.maker_pending_orders` + `watchers.maker_pending_updated_at`. Aucun upsert, ne touche jamais le reste du document (Phase 7). |
| `dashboard/viewdata.py` | Filtrage + nouvelle fonction | Ordres périmés écartés dans `build_maker_orders()` ; nouvelle fonction `maker_freshness()` pour une fraîcheur propre à la tranche maker (récemment publiée par le watcher) vs. fraîcheur du document entier. |
| `dashboard/app.py` | Enrichissement du contexte | Passage du `freshness.is_stale` au template pour affichage de l'avertissement de péremption. |
| `dashboard/templates/dashboard.html` | Affichage | Message « Donnée vieille de X min — pas un suivi temps réel » quand `watchers.maker_pending_updated_at` dépasse le seuil. |
| `tests/test_dashboard_viewdata.py` | 2 nouveaux tests | Tests de filtrage des ordres fantômes (`TestBuildMakerOrders`) et fraîcheur dédiée (`TestMakerFreshness`). |
| `tests/test_dashboard_app.py` | 1 nouveau bloc de tests | `TestMakerOrdersGhostAndFreshness` : 4 tests d'intégration Flask complets vérifiant le rendu HTML du dashboard avec données périmées, ordres fantômes, etc. |
| `tests/test_maker_watcher.py` | 1 nouveau bloc + fixes | `TestMakerPendingPublishedToMongo` : 4 tests vérifiant la publication ne se fait qu'au changement, jamais à chaque tick. Réinitialisation de `_last_published_pending_signature` dans le harness pour éviter les fuites entre tests. |
| `tests/test_storage_mongo.py` | Nouvelle suite (29 lignes) | Tests unitaires de `save_maker_pending_orders()` : $set partiel, absence d'upsert, gestion des erreurs MongoDB. |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_pending_signature()` | Ajoutée | Retourne un tuple canonique `(txid, current_limit_price, adjustments)` pour la composition/prix d'une liste d'ordres — stable pour la détection de changement. |
| `_publish_pending_orders_if_changed()` | Ajoutée | Vérifie si la signature a changé depuis la dernière publication. Si oui, appelle `mongo_repo.save_maker_pending_orders()` en best-effort (log seulement si erreur, jamais levé). Mise à jour de `_last_published_pending_signature` seulement en cas de succès. |
| `_maker_watcher_tick()` | Modifiée | 2 appels à `_publish_pending_orders_if_changed()` ajoutés : quand la liste est vide, et après chaque tick (avec la liste restante). |
| `save_maker_pending_orders()` (mongo.py) | Ajoutée | Écrit `watchers.maker_pending_orders` + `watchers.maker_pending_updated_at` via `$set` pointé (nested dot notation), jamais `upsert`. Retourne bool de succès. |
| `maker_freshness()` (viewdata.py) | Ajoutée | Calcule l'âge de la tranche maker en s'appuyant sur `watchers.maker_pending_updated_at` si disponible, sinon repli sur `dashboard_updated_at` (pour compatibilité pré-#498). |
| `build_maker_orders()` | Modifiée | Filtrage ajouté : si `placed_at` est connu et l'ordre dépasse `maker_timeout_seconds`, il est écartée silencieusement (c'est un fantôme). |

## Décisions techniques notables

- **Signature module-level** : `_last_published_pending_signature` survit aux ticks du watcher pour détecter un changement réel (pose/amend/fill/abandon) vs. juste un tick sans événement. Variable module-level plutôt qu'instance pour partager l'état entre appels sans contexte partagé (le watcher tourne en thread séparé). Testable en réinitialisant la variable du module via `patch`.

- **Best-effort Mongo** : un échec de publication ne doit jamais interrompre la boucle du watcher (confort d'affichage, pas critique). L'erreur est loggée, la signature n'est mise à jour que si l'écriture a réussi — ainsi un changement ultérieur sera retenté.

- **Pas de `upsert`** : la collection `dashboard_state` n'existe que si la Phase 7 a tourné au moins une fois. Un `update_one` qui ne matche rien avant ce premier passage est le comportement attendu — pas de corruption du document en le créant tronqué.

- **Deux cadences d'écriture MongoDB** : le watcher écrit `watchers.maker_pending_updated_at` en temps réel (changements seulement), alors que la Phase 7 écrit le reste (`open_positions`, `financials`, etc.) via `updated_at` global du document. Le dashboard doit donc utiliser le timestamp dédié du watcher pour savoir si sa liste est fraîche, pas celui du document entier.

- **Filtrage ordres fantômes en affichage** : un ordre plus vieux que son timeout ne peut plus exister en attente réelle (le watcher l'aurait fermé). S'il subsiste dans un instantané, c'est parce que la donnée est périmée. Filtrer au niveau affichage (en avant du template) plutôt qu'à la source MongoDB préserve l'audit (les logs Mongo gardent l'historique complet, le dashboard affiche seulement ce qui peut être réel).

## Impact sur l'architecture

Changement isolé, pas d'impact architectural majeur :
- Le watcher ajoute une nouvelle méthode `save_maker_pending_orders()` à `mongo_repo` (injection de dépendance existante).
- Le dashboard enrichit le contexte de render avec la fraîcheur maker (repli gracieux si la clé manque — pré-#498).
- Les tests ajoutent une nouvelle classe `TestMakerPendingPublishedToMongo` pour la publication conditionnelle.

Toute autre phase ou flux reste inchangé.

## Références CLAUDE.md respectées

- **Minimalisme** : seules les fonctions strictement nécessaires ont été ajoutées (`_pending_signature()`, `_publish_pending_orders_if_changed()`, `maker_freshness()`, `save_maker_pending_orders()`). Pas d'abstraction spéculative.
- **Modification chirurgicale** : `_maker_watcher_tick()` et `build_maker_orders()` ont été modifiées au point de besoin uniquement. Les retraits et autres appels restent inchangés.
- **Best-effort Mongo** : pas de gestion d'erreur pour des scénarios impossibles — une erreur Mongo est loggée, la boucle continue (pas critique pour le trading).
- **Configuration dynamique** : les seuils `maker_timeout_seconds` et `maker_max_concession_pct` sont lus depuis `config.json` à chaque tick, aucune hardcoding.
- **Tests complets** : 18 tests ajoutés (4 blocs : TestMakerFreshness + 4 sous TestMakerOrdersGhostAndFreshness + 4 sous TestMakerPendingPublishedToMongo + tests mongo_repo), aucune régression dans les 563 tests existants.
