# PR #391 — Traçabilité des frais Kraken et PnL net

> **Mergée le** : 2026-08-22
> **Branche** : `feat/issue-382-tracking-frais`
> **Issues** : #382

## Contexte

Avant cette PR, `pnl_usdc` (et `pnl_pct`) reflétait le **profit brut** (différence de prix uniquement), sans déduire les frais d'entrée et de sortie facturés par Kraken. Ceci rendait impossible le calcul réel du profit net reçu, et faussait les rapports `/perf` (affichage du PnL du portefeuille).

**Root cause** : les frais Kraken n'étaient jamais capturés lors des fills BUY/SELL. Les cycles futures/historiques accusaient un PnL brut théorique, pas le PnL net encaissé.

**Solution déployée** : capture des frais à chacun des 5 points de clôture (Phase 5 BUY fill, Phase 0 TP + SL + OCO retry, TP Watcher), stockage séparé (`entry_fee_usdc`, `exit_fee_usdc`, `fees_usdc`), recalcul du PnL net via une fonction partagée `compute_net_pnl()`, et backfill de l'historique existant via un script Python.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/trade_helpers.py` | Modification | Ajout deux fonctions `compute_net_pnl()` et `maker_or_taker_from_ordertype()` |
| `binance-bot/core/phases/phase5_execution.py` | Modification | Capture `entry_fee_usdc` au fill BUY, calcul PnL net, ajout champs fee à trade_history |
| `binance-bot/core/phases/phase0_oco_retry.py` | Modification | Utilise `compute_net_pnl()` pour les closes OCO et SL détectés en Phase 0 |
| `binance-bot/core/phases/phase0_profit.py` | Modification | Utilise `compute_net_pnl()` pour les prises de profit Phase 0 TP |
| `binance-bot/core/tp_watcher.py` | Modification | Utilise `compute_net_pnl()` pour les closes TP en temps réel (daemon) |
| `prompts/phases/phase0_snapshot.txt` | Modification | Mise à jour doc et variable `entry_fee_usdc` transmise aux phases descendantes |
| `prompts/shared/api_reference.txt` | Modification | Clarification ordres Kraken : uniquement market/stop-loss (jamais limit) |
| `scripts/backfill_fees.py` | Ajout | Rapprochement historique avec `kraken trades-history`, backfill + estimation |
| `tests/test_backfill_fees.py` | Ajout | 170 lignes : tests rapprochement entrée/sortie, estimation paliers, idempotence |
| `tests/test_phase0_oco_retry.py` | Modification | 48 lignes : ajout tests frais net OCO + SL détecté différé |
| `tests/test_phase0_profit.py` | Modification | 27 lignes : ajout tests frais net take profit |
| `tests/test_phase5_execution.py` | Modification | 85 lignes : ajout tests frais net BUY fill + TP dépassé au fill |
| `tests/test_tp_watcher.py` | Ajout | 64 lignes : tests frais net TP Watcher |
| `tests/test_trade_helpers.py` | Ajout | 59 lignes : tests `compute_net_pnl()`, `maker_or_taker_from_ordertype()` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Fichier | Description |
|---|---|---|---|
| `compute_net_pnl()` | Ajoutée | `trade_helpers.py` | Retourne dict avec `pnl_gross_usdc`, `fees_usdc`, `pnl_usdc`, `pnl_gross_pct`, `pnl_pct` |
| `maker_or_taker_from_ordertype()` | Ajoutée | `trade_helpers.py` | Dérive "taker" depuis `descr.ordertype` de query-orders, retourne None pour les autres types |
| `(phase5_execution.py — ligne 100+)` | Modifiée | `phase5_execution.py` | Capture `entry_fee_usdc`, appel `compute_net_pnl()` au fill et exit |
| `(phase0_oco_retry.py — ligne 74+)` | Modifiée | `phase0_oco_retry.py` | Utilise `compute_net_pnl()` pour les closes OCO et SL |
| `(phase0_profit.py — ligne 65+)` | Modifiée | `phase0_profit.py` | Utilise `compute_net_pnl()` pour les closes TP |
| `_tp_watcher_tick()` | Modifiée | `tp_watcher.py` | Utilise `compute_net_pnl()` avec capture `exit_fee_usdc` du fill |
| `backfill()` | Ajoutée | `backfill_fees.py` | Rapproche fills de `kraken trades-history`, estime si absent, retourne stats |

### Nouveaux champs dans `trade_history.json`

Chaque trade fermé reçoit désormais :

| Champ | Type | Description |
|---|---|---|
| `entry_fee_usdc` | float | Frais Kraken à l'entrée (BUY), capturés depuis fill ou estimés |
| `exit_fee_usdc` | float | Frais Kraken à la sortie (SELL), capturés depuis fill ou estimés |
| `fees_usdc` | float | Total frais = `entry_fee_usdc` + `exit_fee_usdc` |
| `pnl_gross_usdc` | float | PnL brut (ancien calcul) : `(exit_price - entry_price) * qty` |
| `pnl_gross_pct` | float | Pourcentage brut : `(exit_price - entry_price) / entry_price * 100` |
| `pnl_usdc` | float | **PnL net (nouveau)** : `pnl_gross_usdc - fees_usdc` |
| `pnl_pct` | float | **Pourcentage net (nouveau)** : `pnl_usdc / (entry_price * qty) * 100` |
| `maker_or_taker` | string ou null | "taker" pour market/stop-loss, null pour autres types (fallback phase #389) |
| `fees_estimated` | bool | true si les frais ont dû être estimés par palier Kraken (backfill) |

## Décisions techniques notables

- **Séparation brut/net** : `pnl_usdc` est dorénavant le PnL net (avec frais), jamais le brut. `pnl_gross_usdc` et `pnl_gross_pct` conservent l'ancien calcul pour audit. Cette distinction est tranchée sémantiquement — pas d'ambiguïté possible.

- **`maker_or_taker` = "taker" comme constante** : le bot ne pose que des ordres `market` et `stop-loss`, toujours exécutés en taker chez Kraken. Plutôt que d'appeler `kraken query-trades` (requête supplémentaire par fill, plus lent), la fonction `maker_or_taker_from_ordertype()` retourne "taker" de façon déterministe pour `market` et `stop-loss`, et None pour tout autre type. Ceci évite une requête API par trade et reste maintenable si #388 (ordres limit post-only) est implémenté un jour.

- **Backfill avec fallback estimé** : `scripts/backfill_fees.py` rapproche les fills réels de `kraken trades-history` :
  - **Entrées** : somme des fee de tous les fills dont `ordertxid` == `entry_order_id` (gère les fills partiels)
  - **Sorties** : fill "sell" le plus proche temporellement, même paire, même volume (tolérance 0.0001), dans une fenêtre de **48h avant** à 1h après `exit_date` (un SL peut se déclencher côté Kraken plusieurs heures avant détection)
  - **Fallback** : si aucun fill ne matche, utilise un taux estimé par palier Kraken (grille historique `_FEE_TIERS`), et marque `fees_estimated=True`
  - Chaque fill consommé ne compte qu'une fois (pas de double comptage). Trades antérieurs à la portée de l'API (~03/07/2026) sont estimés.

- **Champs propagés dans le prompt** : la Phase 0 lit `entry_fee_usdc` depuis `trade_history.json` et le passe aux phases descendantes via le snapshot. Les phases 0a, 0b, 0c utilisent alors cette valeur pour le PnL net. Pas de ré-calcul des frais dans le prompt (risque de divergence) — c'est un paramètre en entrée.

- **Exception handling resserré** : en Phase 0, les try/except génériques `except Exception:` ont été remplacées par `except (ValueError, KeyError, json.JSONDecodeError):` pour éviter de masquer des erreurs logiques (e.g., IndexError).

## Impact sur l'architecture

**Changement de sémantique du PnL : `pnl_usdc` et `pnl_pct` sont désormais nets, non bruts.** C'est une mutation du contrat d'interface pour `/perf`, les notifications Telegram, et MongoDB. Tous les consommateurs reçoivent dorénavant le PnL **net** sans modification — c'est plus utile pour l'utilisateur final (PnL réel encaissé).

- Historiquement, `/perf` affichait un Sharpe ratio basé sur `pnl_usdc` brut, surestimant légèrement la rentabilité. Après cette PR, il reflète la rentabilité nette réelle.
- Les notifications Telegram affichent le PnL net (plus pertinent pour l'utilisateur).
- MongoDB enregistre le net, avec conservation du brut en champ distinct pour audit.
- Les trades ouverts (status="open") ont `exit_fee_usdc`, `fees_usdc`, `pnl_gross_usdc`, `pnl_usdc`, `pnl_gross_pct`, `pnl_pct` à None (non clôturés).

**Pas d'impact architectural sur les phases ou les flux de données.** Les fichiers intermédiaires (phase0_input.json, phase5_output.json) conservent le même format. Les modifications sont **transversales** : capture dans chaque point de clôture, utilisation d'une fonction partagée, persistance enrichie.

## Références CLAUDE.md respectées

- **Règle 2 — Modifications chirurgicales** : seules les lignes nécessaires à la capture et au recalcul des frais ont été modifiées. Pas de refactoring adjacent. Les try/except ont été resserrés par-là (meilleure pratique), mais c'est un changement minimal aligné au ticket.
- **Pas de dépendances supplémentaires** : `compute_net_pnl()` utilise uniquement la stdlib (float, dict).
- **Python 3.11, venv, PROJECT_DIR dynamique** : backfill_fees.py respecte la même structure que les autres scripts (sys.path.insert, PROJECT_DIR dynamique).
- **Secrets depuis .env** : aucun secret n'est ajouté.

## Vérifications du merge

- ✅ Syntaxe Python : `python -c "import ast; ast.parse(...)"` sur tous les fichiers `.py` modifiés
- ✅ Suite de tests : `python -m unittest discover -s tests` → **101/101 tests PASS**, aucune régression
- ✅ Tests spécifiques :
  - `tests/test_trade_helpers.py` : `compute_net_pnl()` et `maker_or_taker_from_ordertype()`
  - `tests/test_phase5_execution.py` : capture frais BUY fill, TP dépassé au fill
  - `tests/test_phase0_oco_retry.py` : frais net OCO + SL détecté différé
  - `tests/test_phase0_profit.py` : frais net take profit Phase 0
  - `tests/test_tp_watcher.py` : frais net TP Watcher
  - `tests/test_backfill_fees.py` : rapprochement + estimation, idempotence, --dry-run, --force
- ✅ Backfill dry-run : `scripts/backfill_fees.py --dry-run` exécuté contre production historique (lecture seule) → 77 trades clôturés analysés, 42 entrées + 48 sorties mesurées, 35/29 estimées
- ⏳ Backfill réel : à lancer manuellement par l'utilisateur (`scripts/backfill_fees.py` sans `--dry-run`) après review
- ⏳ Vérification post-cycle réel : `/perf` après un prochain cycle avec frais capturés

## Notes post-merge

- **Bug pré-existant repéré** : `phase0_oco_retry.py` contient `import time; time.sleep(1)` sur une ligne de statement multiple (style `E702`, non liée à ce ticket). Signalé par `ruff check`, hors scope.
- **maker_or_taker et #388** : si des ordres limit post-only sont introduits (#388), la fonction `maker_or_taker_from_ordertype()` retournera None pour ce type (le champ "maker" n'existe que dans `query-trades`, pas `query-orders`). Le ticket #389 (commande `/maker`) doit gérer ce None.
- **Fenêtre d'exit 48h avant** : accommode les SL détectés avec retard (jusqu'à 48h après clôture côté Kraken, avant détection en Phase 0).
