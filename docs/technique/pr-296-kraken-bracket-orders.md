# PR #296 — Migrer les ordres OCO Binance vers bracket orders Kraken

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-287-kraken-bracket-orders`
> **Issues** : #287

## Contexte

Migration de la stratégie de protection des positions : abandon des ordres OCO (One-Cancels-Other) liés sur Binance pour un modèle plus simple avec **BUY MARKET + SELL STOP-LOSS uniquement** sur Kraken. Le TP (take-profit) n'est désormais plus géré par un ordre exchange — la détection du dépassement du TP est déléguée à `phase0_profit.py` qui scrute le prix à chaque cycle.

Closes #287.

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `binance-bot/core/phases/phase0_oco_retry.py` | Modification | Remplace la logique OCO par un mécanisme de rattrapage SL uniquement |
| `binance-bot/core/phases/phase0_trailing_stop.py` | Modification | Filtre: `sl_order_txid` à la place des champs OCO anciens |
| `binance-bot/core/phases/phase5_execution.py` | Modification | Supprime les références OCO, enregistre `sl_order_txid` |
| `prompts/phases/phase5_execution.txt` | Modification | Documente le flux BUY MARKET + SELL STOP-LOSS |

### Champs de schéma supprimés

- `order_list_id` — identifiant OCO (plus pertinent)
- `stop_order_id` — ordre de stop-loss OCO (remplacé par `sl_order_txid`)
- `tp_order_id` — ordre de take-profit OCO (plus pertinent, TP maintenant détecté en boucle)
- `orderListId`, `orderReports`, `LIMIT_MAKER`, `STOP_LOSS_LIMIT` — constantes Binance OCO (supprimées)

### Champs conservés / ajoutés

- `sl_order_txid` — identifiant unique Kraken du SELL STOP-LOSS (nouveau, remplace `stop_order_id`)
- `protection_failed` — booléen : SL n'a pas pu être placé après BUY (conservé)
- `oco_retry_count` — compteur de tentatives de rattrapage SL (conservé, sémantique identique)

## Détail des changements

### `phase0_oco_retry.py` (37 additions, 47 deletions)

**Logique de rattrapage protection_failed** :

1. Itère sur les positions ouvertes avec `protection_failed=True`
2. Pour chaque position :
   - **Idempotence** : si `sl_order_txid` existe déjà, vérifie le statut Kraken — si "open", corrige `protection_failed=False` et passe
   - **TP dépassé** : si prix actuel > TP, ferme la position en SELL MARKET, enregistre le P&L, définit `close_reason="market_above_tp"`
   - **Retry SL** : sinon, si `oco_retry_count < max_oco_retry`, place un nouvel ordre SELL STOP-LOSS via `binance("order", "sell", ...)`
     - Arrondit la quantité selon `lot_decimals` Kraken
     - Incrémente `oco_retry_count`
     - Notifie via Telegram
   - **Exhaustion** : si `oco_retry_count >= max_oco_retry`, ferme forcément au SELL MARKET, définit `close_reason="protection_exhausted"`

**Code clé** (lignes 35–46) : vérification du SL actif avant de retenter
```python
sl_txid = t.get("sl_order_txid")
if sl_txid:
    qs_raw = binance("query-orders", sl_txid, "-o", "json")
    qs_data = json.loads(qs_raw) if qs_raw.strip() else {}
    sl_status = qs_data.get(sl_txid, {}).get("status", "unknown")
    if sl_status == "open":
        tg(f"ℹ️ {coin} : SL déjà actif ({sl_txid}), protection_failed corrigé")
        for item in history:
            if item.get("trade_id") == t.get("trade_id"):
                item["protection_failed"] = False
        continue
```

⚠️ **Note observée** : appel `import time; time.sleep(1)` en ligne 57 et 82 (inline dans la boucle) — fonctionnel mais style non idéal. Évoqué dans le test plan comme "bug adjacent".

### `phase0_trailing_stop.py` (13 additions, 34 deletions)

**Simplification du filtre initial** :

Avant : vérifiait la présence d'OCO-related fields (`order_list_id`, `stop_order_id`)
Après : `if t.get("status") != "open" or not t.get("sl_order_txid"): continue`

**Mécanique identique** : tant que le SL existe, remonte le stop loss en suivant le prix (trailing).

**Code clé** (lignes 33–35) : nouveau filtre réduit
```python
for t in history:
    if t.get("status") != "open" or not t.get("sl_order_txid"):
        continue
```

### `phase5_execution.py` (4 additions, 8 deletions)

**Suppression des champs OCO** : enregistrement du trade ne contient plus `order_list_id`, `stop_order_id`, `tp_order_id`.

**Ajout de `sl_order_txid`** (ligne 59) : persiste l'identifiant SL Kraken immédiatement après exécution.

**Structure trade_history complet** (lignes 47–66) :
```python
history.append({
    "trade_id": trade_id,
    "date": ...,
    "coin": trade["coin"],
    "side": "BUY",
    "signal_score": trade.get("signal_score"),
    "entry_price": trade.get("actual_entry"),
    "stop_price": trade.get("actual_stop"),
    "tp_price": trade.get("actual_tp"),
    "quantity": trade.get("actual_qty"),
    "risk_usdc": trade.get("risk_usdc"),
    "entry_order_id": trade.get("entry_order_id"),
    "sl_order_txid": trade.get("sl_order_txid"),  # ← NOUVEAU
    "protection_failed": trade.get("protection_failed", False),
    "status": "open",
    ...
})
```

### `phase5_execution.txt` (prompt, 66 additions, 82 deletions)

Documente le flux complet de Phase 5 :

1. **Re-fetch prix** → détecte drift > 2% → SKIP (TYPE_C)
2. **Re-fetch solde USDC** → détecte insuffisance → SKIP (TYPE_C)
3. **BUY MARKET** → récupère `entry_txid`, attend fill (3 tentatives)
4. **Recalcul TP/SL** sur prix de remplissage réel (`actual_entry`)
5. **Check TP immédiat** : si prix post-fill ≥ TP, ferme SELL MARKET (close_reason="market_above_tp_at_fill")
6. **Filtrages lot_decimals** pour SL
7. **SELL STOP-LOSS** → place la protection, capture `sl_order_txid`, détecte si `protection_failed=True`
8. **Sauvegarde** : écrit `/tmp/cycle_{CYCLE_ID}_phase5_input.json` + appel `phase5_execution.py`

**Exemple prompt** (lignes 44–45) :
```
actual_stop = actual_entry × (1 - stop_distance_pct)
actual_tp   = actual_entry × (1 + stop_distance_pct × reward_risk_ratio)
```

## Décisions techniques notables

- **SL uniquement (pas TP exchange)** : logique plus simple et moins rigide. Le TP est détecté cycliquement par `phase0_profit.py`, ce qui permet d'ajuster dynamiquement si nécessaire.
  
- **Rétro-compatibilité implicite** : les anciens trades Binance (sans `sl_order_txid`) sont ignorés naturellement par les conditions `if t.get("sl_order_txid")` → aucune migration de schéma requise.

- **Idempotence en rattrapage** : avant de retenter un SL, phase0 vérifie si un SL actif existe déjà (`query-orders`). Protège contre les doublons en cas de crash/redémarrage.

- **Utilisation de Kraken CLI uniquement** : plus besoin de Binance CLI pour la gestion OCO. Uniformité exchange.

## Impact sur l'architecture

**Impact modéré et localisé** :

- **Phase 0** : enrichissement de la logique de rattrapage (protection_failed + oco_retry_count restent structurants).
- **Phase 5** : simplification du schéma trade_history (suppression 3 champs OCO, ajout `sl_order_txid`).
- **Composants externes** : dépendance envers Binance CLI supprimée pour cette fonctionnalité (reste utilisée ailleurs). Kraken CLI devient l'unique exchange.
- **TP management** : déportée vers la logique cyclique (phase0_profit), pas d'ordre TP exchange.

**Pas d'impact majeur sur le flux global** : le pipeline Phase 0–7 reste structurellement inchangé. C'est une refonte interne de la protection de position.

## Références CLAUDE.md respectées

- **Rule 2 (PROJECT_DIR dynamique)** : tous les chemins utilisent `PROJECT_DIR = os.path.dirname(...)`, aucun chemin Mac hardcodé.
- **Rule 3 (via .venv + git-perso)** : pas d'appels système autres que `binance()` (wrapper existant) + `import` / `json`.
- **Rule 4 (Telegram via curl)** : appels `tg()` utilisent le helper existant, pas d'urllib direct.
- **Rule 5 (stdout/stderr logging)** : `phase5_execution.py` écrit à `/tmp/cycle_{CYCLE_ID}_phase5_input.json` (intermédiaire pour le sous-processus Claude).
- **Rule 6 (UTC interne, local à l'affichage)** : dates ISO 8601 en UTC (`datetime.timezone.utc`).

## Test plan initial (selon PR body)

- ✅ `python -c "import ast; ast.parse(...)"` : validé pour les 4 fichiers modifiés
- ✅ Grep sur champs supprimés (`order_list_id`, `stop_order_id`, etc.) : aucune résidu trouvé
- ⚠️ Redémarrage manuel bot + `/status` : à valider par utilisateur avant merge (done)
- ⚠️ Vérification du live trading : recommandé en papier trading d'abord
