# PR #294 — Adapter les appels CLI de lecture vers Kraken

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-286-kraken-cli-read-commands`
> **Issues** : #286

## Contexte

Suite à la migration complète vers Kraken CLI (PR #293 remplaçait `binance-cli` par `kraken-cli` dans `trade_helpers.py`), cette PR adapte les **appels de lecture** (ticker, balance, ordres ouverts) pour utiliser la nouvelle syntaxe Kraken au lieu de celle de Binance. Les commandes affectées sont :
- `ticker` : appel unifié (au lieu de deux appels séparés `ticker-price` + `ticker24hr`)
- `balance` : fetch JSON des soldes
- `open-orders` : fetch JSON avec logique de filtrage et annulation d'ordres par `descr.pair`

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/commands/status.py` | Réécriture majeure | Cmd `/status` migre vers Kraken CLI directement (plus de passage par `trade_helpers.tg`) |
| `binance-bot/core/phases/phase0_snapshot.py` | Modification | Utilise ticker Kraken unifié au lieu de deux appels Binance |
| `binance-bot/core/phases/phase1_scan.py` | Modification | Récupère volume 24h depuis la réponse Kraken (`v[1] * prix`) |
| `binance-bot/core/phases/phase0_profit.py` | Modification | Appels ticker et ordres adaptés à Kraken ; logique d'annulation d'ordres refactorisée |

### Fonctions ajoutées / modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `_fetch_account_data()` | status.py | Ajoutée | Récupère les soldes Kraken via `kraken balance -o json` |
| `_fetch_open_orders()` | status.py | Ajoutée | Récupère les ordres ouverts Kraken via `kraken open-orders -o json` |
| `_format_usdc_section()` | status.py | Modifiée | Format inchangé ; le parsing JSON est identique |
| `_format_positions_section()` | status.py | Modifiée | Format identique ; énumère les actifs non-stablecoin de la réponse balance |
| `_format_orders_section()` | status.py | Modifiée | Parse `open_orders.get("open", {})` au lieu de paramètre Binance |
| `run_status()` | status.py | Modifiée | Appelle les deux nouveaux fetchers Kraken ; signature `fmt_next_fn` inchangée |
| _(phase0_snapshot, phase1_scan, phase0_profit)_ | phases/*.py | Modifiée | Remplacent `binance("ticker-price", ...)` + `binance("ticker24hr", ...)` par `binance("ticker", ..., "-o", "json")` |

## Décisions techniques notables

- **Ticker unifié vs. deux appels** : Kraken expose une seule commande `ticker` qui retourne `c` (prix de clôture) et `v` (volume 24h en base asset), simplifiant le code. Volume USDC = `v[1]` (volume 24h en base) × prix.
- **Pas de `binance_profile` Kraken** : La commande Kraken CLI n'expose pas de paramètre `--profile` ; elle utilise directement les credentials du `.env` ou du répertoire Kraken. `status.py` passe donc `subprocess.run([str(KRAKEN_CLI_PATH), ...]` au lieu d'un wrapper `trade_helpers.binance()`.
- **Logique d'annulation d'ordres adaptée** : Phase0_profit parse désormais `open_orders.get("open", {})` et filtre par `descr.pair == f"{coin}USDC"` avant d'appeler `binance("order", "cancel", *txids, ...)`. Ancien flux Binance : `cancel-open-orders --symbol {coin}USDC` (commande dédiée).
- **Pas de distinction free/locked** : Kraken `balance` retourne un dict `{asset: amount_str}` (montant total), sans distinction free/locked comme Binance. Si la distinction est requise à l'avenir, utiliser `extended-balance` (future).

## Impact sur l'architecture

**Changement isolé, pas d'impact sur l'architecture globale.** Cette PR finalise la migration CLI :
- **Lecture complète vers Kraken** : balance, ordres ouverts, ticker — tous passent par `kraken-cli`
- **Phases 2-6 non touchées** : BUY/SELL, order placement, scoring, sizing, exécution restent inchangés
- **Flux de commandes Telegram** : `/status` fonctionne maintenant en direct sur Kraken au lieu de via `trade_helpers`

Phases concernées :
- **Phase 0** (snapshot, profit, oco-retry, trailing-stop) : ticker + balance + open-orders = **✅ Kraken**
- **Phase 1** (scan) : ticker + volume = **✅ Kraken**
- **Commande** `/status` : balance + open-orders = **✅ Kraken**

## Références CLAUDE.md respectées

- ✅ **Règle 4** (Telegram via curl) : pas d'impact sur les appels Telegram — ils restent via curl
- ✅ **Règle 3** (PROJECT_DIR dynamique) : `status.py` utilise `from core.env import PROJECT_DIR` et `cwd=PROJECT_DIR`
- ✅ **Règle 6** (UTC interne) : pas de changement horaire ou timing
- ✅ **Règle 2** (env via `.env`) : `KRAKEN_CLI_PATH` provient de `core.env` (charges depuis `.env` ou défaut)

## Notes techniques

- **Bug adjacent signalé** : Kraken `balance` ne fournit pas de distinction free/locked (montant "en use" vs. "available"). L'affichage `/status` montre le montant total. Si la distinction est requise pour des raisons de margin ou d'isolation, utiliser `extended-balance` (scope futur).
- **Phases 3-8 inchangées** : scoring, sizing, exécution, next-cycle, hb-check, mongo, cycle-log — aucun changement.
- **Prompts non modifiés** : `prompts/phases/*.txt` et `config.json` restent identiques — seule la couche Python est adaptée.

## Tableau des changements clés

| Ancienne syntaxe (Binance CLI) | Nouvelle syntaxe (Kraken CLI) | Fichier(s) |
|---|---|---|
| `binance("ticker-price", "{coin}USDC")` + `binance("ticker24hr", "{coin}USDC")` | `binance("ticker", "{coin}USDC", "-o", "json")` | phase0_snapshot, phase1_scan, phase0_profit |
| `binance("get-account")` (balance) | `kraken balance -o json` | status.py |
| `binance("get-open-orders")` (all) | `kraken open-orders -o json` | status.py, phase0_profit |
| `binance("cancel-open-orders", "--symbol", "{coin}USDC")` | Fetch + filter `descr.pair` + `binance("order", "cancel", *txids)` | phase0_profit |
| `run_status(profile="agent-profile")` | `run_status(fmt_next_fn=...)` | webhook_server → commands/status |

