# PR #457 — Étendre la stratégie maker aux sorties de position

> **Mergée le** : 2026-09-05  
> **Branche** : `feat/issue-390-maker-sorties`  
> **Issues** : #390

---

## Contexte

Avant cette PR, seules les entrées de position employaient la stratégie maker (ordre LIMIT post-only suivi par `maker_watcher.py`). Les sorties (réalisation de profit, take-profit, etc.) étaient systématiquement exécutées par SELL MARKET direct, sans possibilité d'optimiser les frais ou d'ajuster la limite en temps réel pour rester compétitif.

La PR #390 demande d'étendre ce patron aux sorties discrétionnaires **vers le haut** uniquement (c.-à-d. sorties qui cherchent à réaliser un profit) : lorsque le TP watcher ou la Phase 0 décident de clôturer une position, au lieu de vendre au marché, elles posent désormais une limite LIMIT post-only à l'ask courant, suivie d'une chasse du marché via le nouveau watcher `maker_exit_watcher.py`. Les stops, protections épuisées et ventes sur signal retombé conservent la vente au marché immédiate.

Contrainte clé : Kraken immobilise le solde dès qu'un stop-loss est en place (`hold_trade == volume du stop`). Impossible donc de laisser le stop pendant qu'une limite chasse le marché. La solution imposée : **annuler le stop AVANT de poser la limite** ; en cas d'échec ultérieur (annulation de la limite, vente au marché de repli), **reposer immédiatement un nouveau stop** — une position ne doit jamais rester à la fois non protégée ET non vendue.

---

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `binance-bot/core/maker_exit_watcher.py` | Ajouté (511 lignes) | Thread daemon pour suivre et optimiser les ventes limite maker de sortie (#390) |
| `binance-bot/core/phases/phase0_profit.py` | Modifié (+20 lignes) | Import du watcher et remplacement de SELL MARKET par `attempt_maker_exit()` |
| `binance-bot/core/tp_watcher.py` | Modifié (+24 lignes, -1) | Import du watcher et remplacement de SELL MARKET par `attempt_maker_exit()` |
| `binance-bot/webhook_server.py` | Modifié (+4 lignes) | Démarrage du thread `maker-exit-watcher` dans `main_loop()` |
| `config.json` | Modifié (+4 lignes) | Trois nouvelles clés : `maker_exit_enabled`, `maker_exit_timeout_seconds`, `maker_exit_max_concession_pct` |
| `tests/test_maker_exit_watcher.py` | Ajouté (400 lignes) | Suite de tests complète du watcher (8 cas : fill, timeout, délai, prix redescendu, echecs) |
| `tests/test_phase0_profit.py` | Modifié (+77 lignes, -17) | Tests explicites du chemin maker_exit_enabled=true/false |
| `tests/test_tp_watcher.py` | Modifié (+69 lignes, -1) | Tests compatibilité avec maker_exit |
| `tests/test_webhook_server_routing.py` | Modifié (+1 ligne) | Mock du thread maker_exit_watcher |
| `.gitignore` | Modifié (+2 lignes) | Ignorer `state/maker_exit_*.json` |

### Fonctions ajoutées / modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `attempt_maker_exit()` | maker_exit_watcher.py | **Ajoutée** | **Orchestration** : annule le stop de la position, pose une vente LIMIT post-only au prix ask courant. Repose le stop immédiatement en cas d'échec. Retourne un enregistrement à ajouter à `state/maker_exit_pending_orders.json` ou `None` si échec. |
| `maker_exit_watcher_loop()` | maker_exit_watcher.py | **Ajoutée** | **Thread daemon** : boucle infinie lancée à chaque démarrage du bot. Tous les 20s (config `maker_tick_seconds`), fait un tick du watcher pour évaluer et optimiser les ventes limite en cours. |
| `_maker_exit_watcher_tick()` | maker_exit_watcher.py | **Ajoutée** | **Cœur du watcher** : charge les ordres en attente de `state/maker_exit_pending_orders.json`, interroge chacun sur Kraken, applique l'arbre de décision (ordre rempli → clôture position ; prix redescendu/délai/concession épuisés → annule limite puis vente marché ; ask a bougé → amend limite). |
| `_finalize_position()` | maker_exit_watcher.py | **Ajoutée** | Clôture une position dans `state/trade_history.json` avec prix de sortie, frais, PnL calculé, et **champ nouveau** `exit_maker_or_taker` (distinct de `maker_or_taker` qui désigne l'ENTRÉE). |
| `_handle_filled_order()` | maker_exit_watcher.py | **Ajoutée** | Cas 1 : ordre complètement rempli → clôture position, PnL calculé, thread libéré (via lock). |
| `_handle_externally_resolved()` | maker_exit_watcher.py | **Ajoutée** | Cas 2 : ordre disparu ou rempli partiellement hors de notre fait → repose le stop sur le reliquat non vendu (jamais d'abandon côté sortie). |
| `_handle_chase_end()` | maker_exit_watcher.py | **Ajoutée** | Cas 3 : délai/concession/prix redescendu dépassé → annule la limite, compte le fill partiel, reliquat vendu au marché (échecs → repose le stop). |
| `_handle_amend_order()` | maker_exit_watcher.py | **Ajoutée** | Cas 4 : ask a bougé → amend la limite au nouvel ask (post-only, silencieux sur erreur). |
| `_place_stop_loss()` | maker_exit_watcher.py | **Ajoutée** | Arrondit qty/stop au pas de la paire Kraken et pose un ordre stop-loss. Retourne `(sl_txid, protection_failed, err_msg, stop_price_rounded)`. Réutilisé à la fois pour la pose initiale et le repose d'urgence. |
| `_repose_stop_and_alert()` | maker_exit_watcher.py | **Ajoutée** | Repose le stop et notifie Telegram en cas d'échec à une étape. Si repose échoue aussi → position flaggée `protection_failed=True`. |
| `load_maker_exit_pending_orders()` | maker_exit_watcher.py | **Ajoutée** | Charge `state/maker_exit_pending_orders.json` (tableau d'ordres en attente). Retourne `[]` si absent/corrompu. |
| `save_maker_exit_pending_orders()` | maker_exit_watcher.py | **Ajoutée** | Écriture atomique de `state/maker_exit_pending_orders.json` via fichier `.tmp` + `os.replace()`. |
| `_write_watcher_state()` | maker_exit_watcher.py | **Ajoutée** | Maj `state/maker_exit_watcher_state.json` : état du dernier tick, erreurs, compteurs (total_ticks, total_fills, total_fallbacks). |
| `phase0_profit.py:main` | phase0_profit.py | **Modifiée** | Appel à `attempt_maker_exit(pos, "profit_target_phase0", cfg, notify=tg)` quand `maker_exit_enabled=true` et `pnl_pct_net_est >= min_profit`. Sinon, chemin historique SELL MARKET inchangé. |
| `tp_watcher_loop()` | tp_watcher.py | **Modifiée** | Appel à `attempt_maker_exit(pos, "tp_trigger", cfg)` à chaque TP détecté, avec fallback SELL MARKET si échec. |

---

## Décisions techniques notables

- **Annulation du stop AVANT la limite** (pas après) : Kraken bloque le solde avec un stop ouvert. L'ordre LIMIT peut donc échouer s'il n'y a rien à débloquer — annuler d'abord garantit que le solde est libre pour la limite. Repose du stop en cas d'échec ultérieur assure que même une position orpheline (limite échouée, pas de marché) reste protégée.

- **Pas de cas "abandon" côté sortie** : à l'entrée, un maker peut être abandonné si le délai/concession s'épuisent et que personne n'achète. À la sortie, c'est inacceptable : une position DOIT être vendue. Le code repose donc toujours le stop si la limite échoue, et bascule au marché (sans délai ni concession) une fois le délai/concession épuisé.

- **Garde-fou central : prix redescendu au stop** : si le cours retombe au niveau du stop pendant la chasse, bascule immédiate au marché sans attendre le budget de concession ni le délai — c'est le signal que le marché s'est retourné et qu'on ne peut plus attendre.

- **Distinction `exit_maker_or_taker` vs `maker_or_taker`** : le nouveau champ `exit_maker_or_taker` (sur `_finalize_position()`, spécifique à la SORTIE) ne doit jamais écraser `maker_or_taker` qui désigne la classification de l'ENTRÉE. Consommés par `commands/perf.py` et `phase7_mongo.py`.

- **Config : trois nouvelles clés** :
  - `maker_exit_enabled` (bool, défaut `true`) : active/désactive la stratégie maker exit
  - `maker_exit_timeout_seconds` (int, défaut 600 = 10 min) : délai max avant bascule au marché (moins strict qu'à l'entrée : 600s vs 3600s)
  - `maker_exit_max_concession_pct` (float, défaut 0.003 = 0.3%) : concession max en pct avant bascule (réutilise la config d'entrée si omise)

- **État persistant atomique** : les ordres en attente sont sauvegardés dans `state/maker_exit_pending_orders.json` et `state/maker_exit_watcher_state.json` via écriture `.tmp` + `os.replace()`, garantissant la cohérence en cas de crash.

---

## Arbre de décision du watcher (par tick)

Pour chaque ordre dans `state/maker_exit_pending_orders.json` :

1. **Status = "closed"** → ordre rempli intégralement → clôture position (`exit_maker_or_taker = "maker"`), retrait de la liste
2. **Status = "canceled"/"expired"** → ordre disparu hors de notre fait → compte le fill partiel si présent, repose le stop sur le reliquat (jamais d'abandon)
3. **Prix redescendu au stop-price OU concession ≥ max OU délai ≥ timeout** → annule la limite, compte les fills partiels, vente marché reliquat (échecs → repose stop)
4. **Ask courant ≠ limit price courant** → amend la limite au nouvel ask (post-only), silencieux si erreur
5. **Sinon** → rien à faire ce tick

---

## Impact sur l'architecture

**Nouveau composant** : thread daemon `maker-exit-watcher` parallèle à `maker-watcher` (entrée). Lancé au démarrage du bot (`webhook_server.py`, ligne ~320 dans le déploiement initial) sous le modèle existing `threading.Thread(target=maker_exit_watcher_loop, daemon=True)`.

**Deux fichiers state/ nouveaux** :
- `state/maker_exit_pending_orders.json` : array d'ordres LIMIT en chasse, structurée identiquement au watcher d'entrée
- `state/maker_exit_watcher_state.json` : état du watcher (last_tick, status, erreurs, compteurs)

**Flux de sortie modifié** : au lieu de SELL MARKET immédiat depuis `tp_watcher.py` ou `phase0_profit.py`, la position passe par un ordonnancement intermédiaire (`attempt_maker_exit()`) qui pose la limite et remet le suivi au thread watcher.

**Impact sur les phases et commandes** : aucun changement visible à l'utilisateur dans les commandes Telegram ou la sortie des phases. La notification `/status` continuera d'afficher l'état du TP watcher ; ici on ajoute des infos sur `maker_exit_watcher_state.json` (futur PR).

---

## Références CLAUDE.md respectées

- ✅ **Règle 1** (Python via venv + profil shell) : développement via `.venv/` et tests via `python -m pytest`
- ✅ **Règle 2** (`PROJECT_DIR` dynamique) : utilisé dans `core/env.py:PROJECT_DIR` pour les chemins state/
- ✅ **Règle 3** (modifications via binance-dev workflow) : PR créée via l'agent `binance-dev` sur branche dédiée, issue #390 liée et basculée en "In review"
- ✅ **Règle 4** (pas de secrets hardcodés) : `config.json` pour la config, `.env` pour les credentials (inchangé)
- ✅ **Règle 5** (Telegram via curl) : tous les `send_telegram()` passe par `tg_post()` qui utilise curl
- ✅ **Règle 6** (logs stdout/stderr capturés) : le watcher ne crée pas de sous-processus Claude ; ses logs vont à loguru/daemon.log. Les stdout/stderr du cycle continuent d'être capturés dans `logs/stdout/cycle_*.log` et `logs/stderr/cycle_*.log`.
- ✅ **Règle 7** (UTC interne, heure locale à l'affichage) : timestamps en ISO Z dans `state/maker_exit_*.json`, conversion via `fmt_local()` uniquement pour Telegram
- ✅ **Règle 8** (auto-scheduler dans main_loop) : le watcher est un thread daemon parallèle, ne change pas l'auto-scheduler 4h

---

## Tests

Tous les cas couvert par la suite `tests/test_maker_exit_watcher.py` (400 lignes) :

| Cas | Test | État |
|---|---|---|
| Remplissage complet | `TestFullFillClosesPositionAsMaker` | ✅ PASS |
| Remplissage partiel + fallback marché | `TestTimeoutTriggersMarketFallback` | ✅ PASS |
| Prix redescendu au stop | `TestPriceRedescendedTriggersImmediateMarketFallback` | ✅ PASS (cassé délibérément 2 façons) |
| Échec annulation limite → repose stop | `TestLimitCancelFailureReposesStop` | ✅ PASS |
| Échec vente marché → repose stop | `TestMarketSellFailureReposesStop` | ✅ PASS |
| Ordre post-only sell | `TestAttemptMakerExitPostsPostOnlySellOrder` | ✅ PASS |
| Désactivation maker_exit_enabled=false | Intégré aux tests phase0 et tp_watcher existants | ✅ PASS |
| Vente signal jamais par ce chemin | `TestSignalSellNeverUsesMakerExitPath` | ✅ PASS (statique) |

**Synthèse test** : `python -m pytest tests/ -q` → **444 passed, 11 subtests passed**

---

## Fichiers d'état persistants

| Fichier | Schema | Usage |
|---|---|---|
| `state/maker_exit_pending_orders.json` | Array de { trade_id, coin, pair, txid, quantity, stop_price, close_reason, initial_limit_price, current_limit_price, adjustments, placed_at } | Liste des ordres LIMIT en chasse (watcher) |
| `state/maker_exit_watcher_state.json` | { last_tick, status, last_error, orders_checked, total_ticks, total_fills, total_fallbacks } | État du watcher pour monitoring |
| `state/trade_history.json` | Enrichi : field `exit_maker_or_taker` ajouté sur positions fermées par ce chemin | Persistance historique des trades |

---
