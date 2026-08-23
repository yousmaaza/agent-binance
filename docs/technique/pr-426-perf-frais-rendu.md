# PR #426 — [M1] /perf — afficher les frais payés et rendre le gain réel plus lisible

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-396-perf-frais-rendu`
> **Issue** : #396

## Contexte

La commande `/perf` affichait le PnL net sans jamais montrer ses composantes (brut et frais), ce qui rendait impossible de comprendre le coût réel du trading. Elle affichait aussi des périodes chevauchantes (7j et 30j) créant une incohérence dans la lecture. Enfin, elle ignorait complètement la nouvelle stratégie maker (ordres LIMIT en attente, watcher) introduite par la PR #382 et suivantes.

Cette PR restructure le rapport de performance pour :
1. Afficher explicitement la décomposition **brut → frais → net** avec le poids des frais en pourcentage
2. Définir des périodes **non chevauchantes** (0-7j, 8-30j, au-delà) pour clarifier les séries chronologiques
3. Ajouter un bloc dédié aux **frais payés** avec ventilation mesurés/estimés/non calculés
4. Ajouter un bloc de suivi de la **stratégie maker** : ordres en attente, répartition maker/taker/abandonnés, économie vs tout-taker, délai médian
5. **Réconcilier** le Bloc TP Watcher : les ventes sont désormais lues depuis `trade_history.json` (source unique) au lieu d'un compteur interne qui redémarrait
6. **Ajouter les positions annulées** (status="cancelled"), jusqu'à présent invisibles
7. **Vulgariser le vocabulaire** (TYPE_A/B/C/D → score faible/trop petit/conditions dégradées/indisponible, Win rate → Gagnants, Quota Claude → Blocage quota)

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `binance-bot/commands/perf.py` | Refactoring majeur | Restructure complète du rapport avec 6 blocs au lieu de 4 + 3 nouvelles fonctions helper pour décomposition algébrique |
| `tests/test_perf_command.py` | Nouveau fichier | 338 lignes, 28 nouveaux tests unitaires pour couvrir calculs de frais et périodes non chevauchantes |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_load_json(path, default)` | Ajoutée | Utilitaire générique de chargement JSON avec fallback (remplace l'ancienne logique répétitive dans `_load_history()`, `_load_cycles_jsonl()`, etc.) |
| `_pnl(t)` | Ajoutée | Accesseur court pour `t.get("pnl_usdc") or 0` — améliore lisibilité en supprimant répétition |
| `_fees(t)` | Ajoutée | Accesseur pour `t.get("fees_usdc")` — retourne `Optional[float]` pour distinguer "frais nuls" vs "frais non calculés" |
| `_exit_dt(t)` | Ajoutée | Accesseur pour parse d'exit_date — centralise la logique parse_dt() |
| `_fmt_duration(td)` | Ajoutée | Formate une timedelta en chaîne humaine ("2h15", "30min", "45s") — utilisée par le bloc maker pour délai médian |
| `_tp_watcher_closed(closed)` | Ajoutée | Retourne les trades fermés par le TP Watcher en lisant `close_reason` — utilisée à la fois par Bloc Positions et Bloc TP Watcher pour garantir une source unique |
| `_brut_frais_net(trades)` | Ajoutée | Calcule le triplet (brut, frais, net) via l'identité algébrique : `net = pnl_usdc` (toujours connu), `frais = Σ fees_usdc` (si présent), `brut = net + frais`. Cela préserve la cohérence sans fabriquer de frais estimés supplémentaires pour les trades sans `fees_usdc` (ex. SYN/PENDLE historiques) |
| `_bloc_resultat(closed)` | Renommée de `_bloc_pnl()` | Affiche brut → frais → net avec poids frais en %, win rate ("Gagnants"), meilleur/pire trade, top 3 coins, durée moyenne (plus explicite que "Bloc 1 — P&L réalisé") |
| `_bloc_periodes(closed)` | Ajoutée | Affiche les mêmes KPIs (brut/frais/net) pour 3 périodes non chevauchantes : 0-7j, 8-30j, au-delà |
| `_bloc_frais(closed)` | Ajoutée | Bloc nouveau : total frais, coût moyen/trade, ventilation (mesurés, estimés, non calculés) — expose directement `fees_estimated` et compte les trades sans `fees_usdc` |
| `_bloc_maker(history)` | Ajoutée | Bloc nouveau : ordres LIMIT en attente + capital immobilisé, répartition maker/repli marché/abandonnées (depuis `maker_watcher_state.json`), économie vs tout-taker, délai médian de service (depuis `trade_history.json`) |
| `_bloc_cycles()` | Modifiée | Remplace "Quota Claude" par "Blocage quota" (vocabulaire vulgarisé) ; utilise `_SKIP_LABELS` pour afficher "score faible" au lieu de "TYPE_A" |
| `_bloc_positions(history)` | Modifiée | Ajoute les positions annulées (`status="cancelled"`), utilise `_tp_watcher_closed()` comme source unique au lieu de recalculer |
| `_bloc_watcher(closed)` | Modifiée | Lit `total_sales` depuis `trade_history.json` via `_tp_watcher_closed()` au lieu du compteur `tp_watcher_state.json` (qui repart à zéro au redémarrage) |
| `run_perf()` | Modifiée | Orchestre 6 blocs au lieu de 4 : resultat + periodes + frais + cycles + positions + watcher + maker |

### Constantes globales ajoutées

| Constante | Valeur | Rôle |
|---|---|---|
| `_SKIP_LABELS` | dict (TYPE_A→"score faible", ...) | Mapping vulgarisation skip_type pour affichage utilisateur (français, non-technique) |
| `_HISTORY_PATH`, `_CYCLE_LOG_PATH`, etc. | strings | Chemins constants pour les fichiers d'état — centralise les chemins au lieu de les recalculer à chaque appel |

## Décisions techniques notables

### 1. Identité algébrique brut − frais = net

Le brut n'est **pas stocké** dans `trade_history.json` — il est toujours **dérivé** de l'équation `brut = net + frais_connus`. Cette décision :
- **Garantit la cohérence** : pour les 2 trades historiques sans `fees_usdc` (SYN/PENDLE), cela suppose implicitement des frais nuls sur ces trades, mais préserve l'identité sans jamais inventer de frais estimés artificiels
- **Simplifie l'affichage** : une seule source de vérité, pas deux champs `pnl_gross_usdc` et `pnl_usdc` qui pourraient diverger
- **Évite les pièges** : aucun risque de backfill de `pnl_gross_usdc` qui contredise le calcul réel

### 2. Source unique pour les ventes TP Watcher

Avant : le Bloc Positions et le Bloc TP Watcher affichaient deux compteurs différents
- Bloc Positions : lisait `trade_history.json` (la vraie source, persiste entre redémarrages)
- Bloc TP Watcher : lisait `total_sales` depuis `tp_watcher_state.json` (repart à zéro à chaque redémarrage)

**Après** : les deux blocs lisent via `_tp_watcher_closed()`, qui filtre `trade_history.json` sur `close_reason` contenant "tp_watcher". Cela élimine la contradiction et devient maintenant une source unique.

### 3. Vocabulaire vulgarisé

Les labels internes du crypto/trading (TYPE_A, TYPE_B, TYPE_C, TYPE_D, Win rate, Quota Claude) sont traduits en français clair pour un non-crypto :
- TYPE_A → "score faible" (filtre stratégique)
- TYPE_B → "trop petit" (montant < seuil)
- TYPE_C → "conditions dégradées" (drift prix, liquidité)
- TYPE_D → "indisponible" (paire non tradable)
- Win rate → "Gagnants" (% de trades profitables)
- Quota Claude → "Blocage quota" (dépassement API/abonnement)

### 4. Bloc maker lisant l'historique complet, pas seulement les fermés

Le calcul d'économie et de délai médian itère sur **tout** `history`, pas seulement les fermés, car :
- Un ordre rempli en maker mais pas encore clôturé doit compter comme "stratégie maker active"
- C'est cohérent avec le bloc `/maker` qui aussi regarde l'historique complet

### 5. Gestion robuste des ordres abandonné

La répartition maker/repli marché/abandonnées est lue **directement** depuis les compteurs de `maker_watcher_state.json` (`total_fills`, `total_fallbacks`, `total_abandoned`), **pas recalculée** depuis `trade_history.json`, car :
- Les ordres abandonnés (annulés par le watcher sans remplissage) ne laissent **jamais de trace** dans `trade_history.json` — c'est la seule source qui les capture
- Recalculer à partir de l'historique perdrait cette information

## Impact sur l'architecture

Changement isolé au niveau de la commande `/perf` — pas de modification d'architecture, pas de nouvel état persistant (utilise `maker_watcher_state.json` qui existait déjà via PR #412). L'impact est **cosmétique et informatif** : le rapport devient plus lisible et complète pour l'utilisateur.

Cependant, la cohérence améliorée (source unique pour TP Watcher, vocabulaire clair) a des bénéfices indirects : moins de confusion pour le debugging, meilleur alignment entre `/perf` et `/maker` / `/status`.

## Références CLAUDE.md respectées

- ✅ **Lectures seules** : `run_perf()` est une fonction lecture, retourne une str HTML pour Telegram, aucune modification d'état
- ✅ **Français pour l'utilisateur** : vocabulaire vulgarisé pour Telegram (voir `_SKIP_LABELS`, `"Gagnants"` au lieu de "Win rate")
- ✅ **UTC pour la logique, local à l'affichage** : périodes calculées en UTC (`now = datetime.now(timezone.utc)`), dates affichées via `fmt_local()` (CLAUDE.md règle 6)
- ✅ **Traçabilité des données** : source unique `trade_history.json` pour les statistiques, fallback Mongo → JSONL transparent
- ✅ **Pas de side effects** : zéro modification de fichiers state/ durant `/perf`

## Tests

Nouveau fichier `tests/test_perf_command.py` avec 28 tests unitaires :
- Tests calculs brut/frais/net (identité algébrique)
- Tests périodes non chevauchantes (isolation des buckets)
- Tests ventilation frais (mesurés, estimés, non calculés)
- Tests répartition maker (divmod par zéro protégé)
- Tests gestion `maker_or_taker` = `None` (historique ancien)
- Tests tronçature message > 4000 chars Telegram

Suite complète : **213 tests** (185 existants + 28 nouveaux), tous ✅ avec `python -m unittest discover tests/`.

---

**Issue fermée** : #396 (décision de conception pour brut = net + frais + blocs étendus)
