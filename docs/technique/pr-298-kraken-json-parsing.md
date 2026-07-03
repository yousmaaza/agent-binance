# PR #298 — Migrer parsing réponses JSON Binance → Kraken (phase0_profit)

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-288-kraken-json-parsing`
> **Issues** : #288

## Contexte

Continuation de la migration Binance → Kraken (T4 de la M4). Phase 0 (`phase0_profit.py`) était encore en attente de migration pour le bloc **SELL MARKET** — réalisation des profits quand le TP est atteint. Cette PR remplace le parsing des réponses JSON Binance (`executedQty`, `cummulativeQuoteQty`, `orderId`) par les champs Kraken équivalents (`vol_exec`, `cost`, `txid`).

Closes #288.

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `binance-bot/core/phases/phase0_profit.py` | Modification | Remplace parsing Binance SELL MARKET par Kraken ; ajout `time.sleep(1)` pour stabilisation fill |

### Bloc SELL MARKET : avant / après

**Avant (Binance)** :
```python
sell_raw = binance("order", "sell", f"{coin}USDC", str(qty), "--profile", "agent-profile", "-o", "json", "--yes")
sell_resp = json.loads(sell_raw)
executedQty = float(sell_resp.get("executedQty", 0))
cummulativeQuoteQty = float(sell_resp.get("cummulativeQuoteQty", current_price * qty))
exit_price = cummulativeQuoteQty / executedQty if executedQty else current_price
```

**Après (Kraken)** :
```python
sell_raw = binance("order", "sell", f"{coin}USDC", str(qty), "--type", "market", "-o", "json", "--yes")
sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
sell_txid = sell_resp.get("txid", [None])[0]
if sell_txid:
    time.sleep(1)  # laisser le fill se propager
    fill_raw = binance("query-orders", sell_txid, "-o", "json")
    fill_data = json.loads(fill_raw) if fill_raw.strip() else {}
    fill = fill_data.get(sell_txid, {})
    vol_exec = float(fill.get("vol_exec", qty))
    cost = float(fill.get("cost", current_price * qty))
    exit_price = cost / vol_exec if vol_exec else current_price
```

### Champs de réponse modifiés

| Concept | Binance | Kraken | Note |
|---|---|---|---|
| Commande SELL | `--profile agent-profile` | `--type market` | Paramètre exchange changé |
| Identifiant ordre | `orderId` (dans `sell_resp`) | `txid` (liste, premier élément) | Kraken retourne liste d'IDs |
| Quantité exécutée | `executedQty` | `vol_exec` (dans query) | Kraken exige un appel `query-orders` séparé |
| Coût total | `cummulativeQuoteQty` | `cost` (dans query) | Idem, récupéré en deux temps |

## Décisions techniques notables

- **Séparation en deux appels** : SELL retourne le TXID, puis `query-orders(txid)` retourne les détails du fill. Ceci reflète la sémantique Kraken (ordre lancé → état requêté séparément). Binance fusionnait les deux dans la réponse initiale.

- **Stabilisation avec `time.sleep(1)`** : entre le `order sell` et le `query-orders`, on attend 1s pour que le fill se propage dans le state Kraken. Sans ce délai, `query-orders` peut retourner des champs vides ou `vol_exec=0`. C'est un pattern déjà utilisé ailleurs en Phase 0 (ex. `phase0_oco_retry.py`).

- **Fallback sur prix courant** : si `vol_exec == 0` ou `cost == 0` (fill inexistant ou partiellement remisé), on utilise `current_price` pour le calcul. Cohérent avec la logique Binance existante.

- **Pas de change sur le commentaire ligne 81** : l'erreur `except` capture désormais les échecs spécifiques Kraken (timeout query, JSON vide) mais le message reste générique : "Fermeture P&L échouée (OCO annulé, position non protégée)".

## Schéma trade_history : pas de changement

L'écriture en `trade_history.json` (Phase 5 et Phase 0 réalisation) n'a pas changé :
- Les champs `exit_price`, `pnl_usdc`, `pnl_pct`, `exit_date` restent identiques.
- Les anciens trades Binance avec `cummulativeQuoteQty` dans l'historique sont **conservés tels quels** — ils ne sont jamais relus après migration.
- `state/trade_history.json` reste la source de vérité pour `/perf` ; les nouvelles entrées sont purement Kraken.

## Impact sur l'architecture

**Impact très localisé** :
- **Phase 0 (profit)** : bloc SELL MARKET remplacé, reste fonctionnellement identique (même détection du TP, même mise à jour trade_history).
- **Dépendances** : suppression de `--profile agent-profile` (spécifique Binance) ; plus aucune référence à Binance CLI dans ce contexte.
- **Pas d'impact sur Phase 5, 6, 7** : ceux-ci ne touchent pas au bloc SELL MARKET de phase0_profit.

**Cohérence globale** : Phase 0 est maintenant 100% Kraken CLI, alignée avec Phases 1, 4, 5. La migration M4 est complète.

## Références CLAUDE.md respectées

- **Rule 2 (PROJECT_DIR dynamique)** : aucun changement de chemins, déjà respecté.
- **Rule 3 (via .venv)** : pas de new imports, `import time` était déjà présent (ligne 12).
- **Rule 4 (Telegram via curl)** : appel `tg()` existant inchangé (ligne 79).
- **Rule 5 (stdout/stderr)** : logs du cycle écrits comme avant dans `logs/stderr/`.
- **Rule 6 (UTC)** : l'`exit_date` est maintenu en UTC ISO 8601 (ligne 75).

## Test plan initial (selon PR body)

- ✅ `python -c "import ast; ast.parse(open('binance-bot/core/phases/phase0_profit.py').read()); print('OK')"` → OK
- ✅ Grep : aucune référence restante à `executedQty`, `cummulativeQuoteQty`, `orderId`, `--profile agent-profile`
- ⚠️ Redémarrage bot manuel + `/trade` : à valider par utilisateur avant merge
