# PR #404 — [M1] Commande Telegram /maker — suivi du watcher d'ordres maker

> **Mergée le** : 2026-08-22
> **Branche** : `feat/issue-389-commande-maker`
> **Issues** : #389

## Contexte

Suite à la PR #397 (watcher d'ordres limite maker), l'utilisateur avait besoin de visibilité sur l'état en temps réel du watcher et les ordres en cours de poursuite. Cette PR ajoute une nouvelle commande Telegram `/maker` qui agrège les informations depuis trois fichiers d'état (lecture seule) et les présente en 3 blocs structurés.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/commands/maker.py` | Ajouté (179 lignes) | Nouvelle commande complète : interface lecture-seule vers watcher et historique trades |
| `binance-bot/webhook_server.py` | Modification | Dispatch `/maker` dans `main_loop()` + mise à jour liste commandes |
| `binance-bot/core/maker_watcher.py` | Modification (+11 lignes) | Ajout champs `adjustments` (compteur par ordre) et `maker_fill_seconds` (délai remplissage maker) |
| `binance-bot/core/phases/phase5_execution.py` | Modification (+1 ligne) | Initialisation `adjustments: 0` à la pose d'un ordre LIMIT |
| `tests/test_maker_command.py` | Ajouté (227 lignes) | Batterie complète : 21 tests du comportement de `/maker` (3 blocs, états dégradés, alertes) |
| `tests/test_maker_watcher.py` | Modification | Test du compteur `adjustments` sur amend réussi + défense `.get("adjustments", 0)` |
| `tests/test_webhook_server_routing.py` | Modification | Test du routing `/maker` dans `main_loop()` |
| `README.md` | Modification | Ajout `/maker` à la liste des commandes |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `run_maker()` | Ajoutée | Handler complet retournant une `str` (compatible Telegram HTML) — orchestration des 3 blocs |
| `_format_health_section()` | Ajoutée | Bloc 1 : santé du watcher (statut OK/Lent/Erreur, dernier tick, compteurs cumulatifs) |
| `_format_pending_section()` | Ajoutée | Bloc 2 : ordres en cours de poursuite (coin, quantité, prix limité courant, ratio concession, compteur ajustements, durée écoulée) |
| `_format_efficiency_section()` | Ajoutée | Bloc 3 : efficacité cumulée (taux remplissage maker 24h/lifetime, frais évités, délai médian) |
| `_load_json()` | Ajoutée | Helper robuste de chargement JSON avec fallback défaut |
| `_fmt_duration()` | Ajoutée | Formatage lisible durée : `30s`, `5min`, `1h02` |
| `_fill_rate_pct()` | Ajoutée | Calcul taux remplissage maker (%), `None` si aucun trade |
| `_handle_amend_order()` | Modifiée (core/maker_watcher.py) | Incrémentation `pending["adjustments"]` après amend réussi (ligne 330) |
| `_register_open_position()` | Modifiée (core/maker_watcher.py) | Calcul `maker_fill_seconds` (différence `now - placed_at` si maker=true, sinon `None`) |

## Décisions techniques notables

### Trois champs de données ajoutés à l'état persistant

1. **`adjustments` (pending order)** : compteur initié à `0` lors de la pose (Phase 5), incrémenté à chaque amend réussi dans `_handle_amend_order()`. Défense `pending.get("adjustments", 0)` côté commande pour ordres hérités en vol au déploiement (affichage `0` jusqu'au premier amend).

2. **`maker_fill_seconds` (trade history)** : calculé uniquement pour les fills maker (`maker_or_taker == "maker"`), comme la durée écoulée entre `placed_at` et le fill. Reste `None` pour les trades taker ou legacy (sans `placed_at`). L'affichage ignore les trades sans ce champ (historique antérieur).

3. **Aucun champ supplémentaire sur `trade_history.json`** : le delta entrant est minimal, rétro-compatible. Les trades antérieurs à ce déploiement sans `maker_fill_seconds` affichent `"n/d"` (cas explicite testé).

### Stratégie lecture-seule

La commande `/maker` ne pose aucun appel réseau ni Kraken CLI — garantit réponse < 5s même en surcharge. Elle lit trois fichiers JSON (watcher_state, pending_orders, trade_history) et agrège. Aucune mutation d'état : l'historique des trades est consulté en lecture, jamais modifié.

### Fenêtre temporelle et format

- **24h glissantes** pour "aujourd'hui" : cohérent avec `_count_tp_watcher_sales_24h()` dans `status.py`, non pas un jour calendaire
- **Concession affichée** : calculée depuis `current_limit_price` (mis à jour à chaque amend réussi), non un appel ticker live
- **Délai médian** : `statistics.median()` sur les `maker_fill_seconds` des fills maker seulement, ignores les taker et les legacy sans délai

### Alerte concession

Seuil dur : ratio `concession_pct / budget_pct >= 0.8` → alerte `⚠️`. Calcul : `(current_price - initial_price) / initial_price` divisé par `maker_max_concession_pct` (défaut 0.30%). Alerte affichée en-ligne avec le coin, facilite la lecture rapide.

### Troncature propre

Maximum 8 ordres affichés (constant `_MAX_ORDERS_SHOWN`) — si plus, mention "… et N autre(s) ordre(s) non affiché(s)". Évite spam sur 20+ ordres en attente (cas pathologique).

## Impact sur l'architecture

Aucun impact architectural. La commande est isolée :
- Nouvelle fonction handler `run_maker()` en `commands/maker.py` (pattern identique à `status.py`, `perf.py`)
- Dispatch simple dans `main_loop()` (4 lignes ajoutées via `elif text.startswith("/maker")`)
- Deux champs ajoutés à l'état (retrocompatibles, défendus à la lecture)
- Zéro modification du flux de trading principal (Phase 0–8 non impactés)

Le watcher continue d'opérer de façon indépendante (PR #397). Cette commande ne fait que l'observer.

## Références CLAUDE.md respectées

- **Lecture seule** : aucun appel externes, pas de modification d'état persistant → temps de réponse < 5s garanti (critère projet)
- **Encoding UTF-8** : utilisation emojis et formatage HTML Telegram pour clarté visuelle
- **Pas de dépendances neuves** : `statistics` (stdlib Python), `datetime`, `json` (stdlib)
- **Gestion d'erreur gracieuse** : fichiers absents ou corrompus → affichage d'états gracieux ("En attente du premier tick", "Aucun ordre en attente", "Pas encore de données")
- **Tests complets** : 21 tests unitaires couvrant états dégradés (fichiers absents, watcher en erreur, ordres hérités sans compteur) + cas nominal + alertes seuils

## Test plan

- [x] `/maker` répond en moins de 5s (lecture seule, aucun appel réseau / kraken-cli)
- [x] Bloc 1 (santé) : watcher absent → "En attente du premier tick", disabled → affiche explicite `maker_entry_enabled: false`, en erreur → `🔴 Erreur` + message dernier erreur
- [x] Bloc 2 (ordres) : liste vide → "Aucun ordre en attente", ordres affichés avec ratio concession / budget, alerte ⚠️ au-delà 80%, troncature > 8
- [x] Bloc 3 (efficacité) : aucun trade classé → "Pas encore de données", taux maker 24h/lifetime calculés (ignore non-classés), frais évités somme `entry_fee_usdc` des makers, délai médian ignorant legacy sans `maker_fill_seconds`
- [x] Rétrocompatibilité : ordres hérités sans `adjustments` → `.get("adjustments", 0)` → affiche `0`, trades legacy sans `maker_fill_seconds` → ignorés en calcul, résultat `"n/d"` si aucun maker mesuré
- [x] Syntaxe Python 100% (`ast.parse`)
- [x] Suite tests : 131 existants + 21 nouveaux = 152/152 PASS (19 dans `test_maker_command.py`, 1 dans `test_maker_watcher.py`, 1 routing, 1 assertion `maker_fill_seconds` dans tests existants)
- [ ] Test manuel redémarrage bot + `/maker` en conditions réelles (aucun ordre maker rempli en prod encore → blocs 2/3 afficheront états vides/n/d, comportement attendu)

## Notes

- **Compatibilité totale** avec les phases existantes (0–8) — la commande est *pure lecture* sur l'état posé par le watcher (#397) et les trades existants
- **Bloc 3 peu informatif initialement** : tant qu'aucun trade `maker_or_taker == "maker"` n'existe en prod (déploiement #397 très récent), les trois métriques d'efficacité afficheront leurs états "vides" (0%, n/d) → comportement attendu, pas un bug
- **Pas de dépendance nouvelle** : zéro ajout dans `requirements.txt`
