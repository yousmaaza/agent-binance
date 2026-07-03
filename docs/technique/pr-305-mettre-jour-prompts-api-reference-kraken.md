# PR #305 — [M5] Mettre à jour les prompts et api_reference pour Kraken

> **Mergée le** : 2026-07-03  
> **Branche** : `feat/issue-290-kraken-prompts-api-reference`  
> **Issues** : #290

## Contexte

Migration de la stack Binance CLI vers Kraken CLI. Cette PR met à jour l'ensemble des prompts injectés dans le sous-processus Claude (`TRADE_PROMPT`) pour utiliser les commandes Kraken à la place de Binance. Elle complète T3 (#296, phase 5 execution) et s'inscrit dans la transition complète vers kraken-cli (T1 #285 déjà mergé, T4 #298 en review).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/shared/api_reference.txt` | Rédaction complète | Nouvelle documentation API kraken-cli (remplace binance-cli) |
| `prompts/phases/phase0_snapshot.txt` | Modification | Migration appels balance, SL verification, trailing stop |
| `prompts/phases/phase1_scan.txt` | Modification | Migration tradabilité USDC (ticker + volume) |
| `prompts/phases/phase4_sizing.txt` | Modification | Migration sizing (lot_decimals, ordermin, costmin vs stepSize) |
| `prompts/position_prompt.txt` | Modification | Migration position management (open-orders, ticker, cancel par txid) |

### Commandes kraken-cli documentées

| Besoin | Commande | Remplace |
|---|---|---|
| Prix + volume 24h | `kraken ticker {COIN}USDC -o json` | `binance-cli ticker-price` + `ticker24hr` |
| Solde compte | `kraken balance -o json` | `binance-cli get-account` |
| Filtres marché (stepSize, min qty, costmin) | `kraken pairs --pair {COIN}USDC -o json` | `binance-cli exchange-info` |
| Ordres ouverts | `kraken open-orders -o json` | `binance-cli get-open-orders` (OCO) |
| Vérifier ordre | `kraken query-orders {TXID} -o json` | `binance-cli get-order` (par orderId) |
| Annuler ordre | `kraken order cancel {TXID} -o json --yes` | `binance-cli cancel-order` (par orderId) |
| BUY MARKET | `kraken order buy {COIN}USDC {QTY} --type market -o json --yes` | `binance-cli market-order buy` |
| SELL MARKET | `kraken order sell {COIN}USDC {QTY} --type market -o json --yes` | `binance-cli market-order sell` |
| SELL STOP-LOSS | `kraken order sell {COIN}USDC {QTY} --type stop-loss --price {SL} -o json --yes` | `binance-cli create-order sell` + OCO |

### Changements clés par phase

#### Phase 0 — Snapshot + vérifications

- **Solde portfolio** : `binance-cli get-account` → `kraken balance`
- **Vérification SL** : Utilise `sl_order_txid` (stocké en trade_history.json) + `kraken query-orders {txid}` pour vérifier si `status=="closed"`
- **Trailing stop** : Toujours exécuté via `phase0_trailing_stop.py` (pas de modification du prompt)

#### Phase 1 — Scan marché

- **Tradabilité USDC** : 
  - Vérifie que la paire `{COIN}USDC` existe : `kraken ticker {COIN}USDC`
  - Calcule volume 24h USDC : `float(v[1]) * prix` (v[1] = volume en asset base, pas USDC)
  - Filtre : volume < 5M USDC → coin rejeté (TYPE_D skip)
- **Mapping BTC** : `BTCUSDC` n'existe pas → utiliser `XBTUSDC`

#### Phase 4 — Sizing

- **Récupère filtres marché** : `kraken pairs --pair {COIN}USDC -o json`
- **Arrondit quantité** : 
  - `step_size = 10 ** (-lot_decimals)` (au lieu de `stepSize` Binance)
  - Vérifie `quantite >= ordermin` ET `quantite * prix >= costmin`

#### Phase 5 — Execution

**Non modifié dans cette PR** — déjà migré par PR #296. Les ordres BUY MARKET sont lancés comme avant.

#### Position prompt — Gestion des positions

- **Ordres ouverts** : `kraken open-orders -o json` (retourne `{"open": {TXID: {...}}}`)
- **Prix actuels** : `kraken ticker {COIN}USDC` (au lieu de binance-cli ticker-price)
- **Annulation** : `kraken order cancel {TXID}` (par txid, pas par orderId)
- **Pas d'OCO natif** : Kraken n'a pas d'OCO — le TP est géré par `phase0_profit.py`, seul le SL est posé comme ordre permanent

## Décisions techniques notables

- **Strings vs float** : Les prix et volumes Kraken sont des strings dans le JSON — toujours convertir en `float()` avant calculs (ajouté dans api_reference.txt)
- **Volume 24h Kraken** : Le `v[1]` est le volume en asset base (SOL, pas USDC) — multiplier par le prix pour obtenir le volume USDC (différence clé vs Binance)
- **Mapping BTC→XBTUSDC** : Documenté dans api_reference.txt comme piège courant. Mapping sera appliqué en Phase 1 avant chaque appel ticker
- **Open-orders sans filtre par paire** : `kraken open-orders` retourne TOUS les ordres — filtrer manuellement sur `descr["pair"]` (ajouté dans position_prompt.txt)
- **SL permanent** : Contrairement à Binance OCO, Kraken SL est un ordre standalone stocké sous `sl_order_txid` et vérifié avec `query-orders`
- **Variable KRAKEN_CLI inchangée** : Reste substituée par `runner.py` T1 — pas de modification du venv ni du shebang

## Impact sur l'architecture

**Scope** : Changement isolé aux prompts injectés au sous-processus Claude (`TRADE_PROMPT`).

**Impact architectural** : Aucun — les phases restent identiques, seules les commandes shell changent. Le flux d'exécution (`webhook_server.py`, `phases/*.py`, state/logs) n'est pas modifié.

**Dépendances résolvantes** :
- T1 #285 (kraken-cli install + config) — ✅ mergé
- T3 #296 (phase 5 execution) — en review
- T4 #298 (runner.py + variable KRAKEN_CLI) — en review

**Bloquants levés** : PR #305 débloque les phases 0-4 pour utiliser kraken-cli. Phase 5 sera prête dès que #296 est mergée.

## Références CLAUDE.md respectées

- **Règle 4 (Telegram via curl)** : Non applicable aux prompts (pas d'appel Telegram direct)
- **Règle 5 (Secrets via .env)** : Non modifié — KRAKEN_CLI reste une variable Python
- **Minimalisme** : Prompts allégés — suppression des références `binance-cli --profile agent-profile`, `--wait-for-order`
- **Modification chirurgicale** : Seules les commandes Binance CLI remplacées par Kraken CLI ; logic des phases inchangée

## Notes supplémentaires

- Phase 5 execution (BUY MARKET) : non modifiée ici, déjà migrée par PR #296
- Config.json et mapping BTC→XBTUSDC : traités en T7
- Redémarrage bot : utilisateur fait avant merge pour valider `/status`
