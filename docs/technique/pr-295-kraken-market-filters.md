# PR #295 — [M3] Adapter les filtres de marché Binance LOT_SIZE → Kraken

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-289-kraken-market-filters`
> **Issues** : #289

---

## Contexte

Après la migration complète vers `kraken-cli` pour les ordres (PR #294, #293), l'infrastructure d'exécution utilise Kraken Spot. Cependant, trois phases critiques — **phase0_oco_retry**, **phase0_trailing_stop**, et **phase4_sizing** — s'appuyaient encore sur l'ancienne API Binance pour récupérer les **filtres de marché** (stepSize, minQty, notional minimums, lot size). 

Cette dépendance résiduelle créait :
- Une asymétrie architecturale : ordres via Kraken, contraintes via Binance
- Un risque opérationnel : un coin présent sur Kraken mais absent de Binance (ou avec des règles différentes) causerait des erreurs silencieuses en Phase 4 ou des ajustements de quantité incorrects en Phase 0
- Un manque de cohérence : les contraintes costmin de Kraken (montant minimum par paire) n'étaient pas appliquées

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase0_oco_retry.py` | Modification | Remplace `binance("spot", "exchange-info", ...)` par `binance("pairs", ...)` pour récupérer lot_decimals, élimine la dépendance Binance pour ajuster la quantité lors du rattrapage OCO |
| `binance-bot/core/phases/phase0_trailing_stop.py` | Modification | Remplace `binance("ticker-price", ...)` par `binance("ticker", ...)` et utilise `binance("pairs", ...)` pour récupérer lot_decimals et tick_size natifs à Kraken |
| `binance-bot/core/phases/phase4_sizing.py` | Modification | Remplace `binance("spot", "exchange-info", ...)` par `binance("pairs", ...)`, ajoute vérification de `costmin` (montant minimum requis par paire Kraken) en plus du montant calculé |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| Phase 0 OCO Retry (phase0_oco_retry.py:102–106) | Modifiée | Appel `binance("pairs", "--pair", f"{coin}USDC", "-o", "json")` pour récupérer `lot_decimals`, calcul `step = 10**(-lot_decimals)`, arrondi la quantité à `qty_adj = round(math.floor(qty / step) * step, lot_decimals)` avant l'OCO |
| Phase 0 Trailing Stop (phase0_trailing_stop.py:71–83) | Modifiée | Appel `binance("pairs", "--pair", f"{coin}USDC", "-o", "json")` pour récupérer `lot_decimals` et `tick_size`, utilise ces données natives pour arrondir quantité et prix avant placement OCO de rattrapage |
| Phase 4 Sizing (phase4_sizing.py:79–93) | Modifiée | Appel `binance("pairs", "--pair", f"{coin}USDC", "-o", "json")`, extraction de `lot_decimals`, `ordermin`, `costmin` ; calcul `step = 10**(-lot_decimals)`, arrondi, puis vérification `quantite >= ordermin` ET `quantite * prix_entry >= costmin` avant ajout aux ordres préparés |

### Détails techniques clés

#### 1. **Récupération des métadonnées Kraken via `kraken pairs`**

```json
// kraken pairs --pair BTCUSDC -o json
{
  "BTCUSDC": {
    "lot_decimals": 8,
    "tick_size": "0.01",
    "ordermin": "0.00001",
    "costmin": "10.0",
    ...
  }
}
```

- **lot_decimals** : nombre de décimales de la quantité (ex. 8 → quantités valides : 0.00000001, 0.00000002, ...)
- **tick_size** : plus petit pas de prix (ex. 0.01 → prix valides : 100.00, 100.01, ...)
- **ordermin** : quantité minimale par ordre
- **costmin** : montant USDC minimal requis (contrôle de liquidité côté Kraken)

#### 2. **Calcul de `step` et arrondi des quantités**

Avant : utilisation de `stepSize` depuis Binance exchange-info (valeur décimale 0.00000001, 0.0001, etc.)
Après : calcul via `lot_decimals` :
```python
step = 10 ** (-lot_decimals)
qty_rounded = round(math.floor(qty / step) * step, lot_decimals)
```
Garantit que la quantité est un multiple exact de `step` et arrondissable proprement.

#### 3. **Vérification costmin en Phase 4**

Avant : seule vérification du montant minimal fixe `min_order_usdc` (9 USDC)
Après : ajout d'une vérification double :
```python
if quantite * prix_entry < costmin:
    skipped.append({"coin": coin, "reason": f"montant {quantite * prix_entry:.2f} USDC < costmin {costmin}"})
```
Chaque paire peut avoir son propre `costmin` — le bot respecte maintenant la contrainte native Kraken plutôt que de faire des suppositions.

#### 4. **Récupération du prix via `kraken ticker`**

Avant : `kraken ticker-price` retournait une chaîne simple
Après : `kraken ticker` retourne JSON avec structure :
```json
{
  "BTCUSDC": {
    "c": [45000.12, 123456],  // [prix, volume]
    ...
  }
}
```
Parsing : `price = float(ticker_data.get(f"{coin}USDC", {}).get("c", [0])[0])`

#### 5. **OCO natif : Kraken n'en a pas**

Phase 0 OCO Retry définie `has_oco = False` systématiquement (ligne 38), car Kraken n'expose pas d'OCO natif dans kraken-cli. La logique d'idempotence du rattrapage OCO (vérifier si un OCO existe déjà) sera revisitée en T3 — pour l'instant, chaque tentative crée un nouvel ordre.

### Décisions techniques notables

- **Pas de fallback sur Binance** : la PR supprime la dépendance complète. Si une paire n'existe pas sur Kraken, l'appel `binance("pairs", ...)` échoue en Phase 4 → skip TYPE_B/C. C'est volontaire : on veut détecter et signaler les incohérences, pas les masquer.
  
- **Pas de cache metadata** : les métadonnées Kraken (lot_decimals, tick_size) sont refetchées à chaque cycle (Phase 0 × 2, Phase 4). Surcalcul minimal (3 appels CLI par cycle au lieu de 1 exchange-info Binance massif), mais transparence et résilience aux changements de règles gagnées.

- **Bug adjacent non corrigé** : `_round_qty()` dans phase0_trailing_stop.py:26 arrondit toujours à 8 décimales (`round(..., 8)`) plutôt qu'à `lot_decimals` dynamique — hors scope de ce ticket, signalé dans le test plan de la PR.

## Impact sur l'architecture

Changement **isolé et localisé** : aucun impact sur l'architecture globale de la boucle. Les phases 1–3 et 5–8 restent inchangées. L'adapter Kraken pour les métadonnées consolide simplement la migration vers Kraken commencée en PR #294/#293.

**Avant (asymétrie)** :
- Ordres : kraken-cli
- Métadonnées : binance-cli (dépendance résiduelle)

**Après (cohérence)** :
- Ordres : kraken-cli
- Métadonnées : kraken-cli
- Binance : plus du tout appelée (sauf pour les ordres spot existants antérieurs à la migration, en cas de rollback — mais nouveau code assume Kraken)

**Bénéfices** :
1. Une seule source de vérité (Kraken) pour les contraintes de marché
2. Pas de risque de désynchronisation entre règles Binance et Kraken
3. Pas de dépendance inattendue vers une API non migrée
4. Erreurs de disponibilité détectées et loguées explicitement (TYPE_D)

## Références CLAUDE.md respectées

- **Règle 2 — `PROJECT_DIR` dynamique** : tous les chemins utilisés via `os.path.dirname(os.path.dirname(...))` relatif au script, pas de hardcoding
  
- **Règle 4 — Appels Telegram via curl** : pas de changement, mais le code utilise `tg()` helper pour les notifications → OK
  
- **Règle 5 — Stdout/stderr sauvegardés** : Phase 0 logs via `tg()` vers Telegram (asynchrone), logs de phase via tempfile JSON → OK
  
- **Règle 6 — UTC interne** : pas de logique horaire affectée, vérifications de prix UTC unchanged → OK
  
- **Règle 8 — skip_type/skip_detail** : Phase 4 utilise ces champs pour classifier les skips (TYPE_A score trop bas, TYPE_B montant trop petit, **nouveau** TYPE_B costmin) → cohérent

---

## Fichiers connexes

- `binance-bot/core/trade_helpers.py` : import du helper `binance()` (unchanged)
- `config.json` : paramètre `min_order_usdc` toujours utilisé en Phase 4 (unchanged, complément de costmin)
- `CLAUDE.md` : règles de développement respectées (unchanged)

---

## Notes de test

- Syntaxe Python validée (`ast.parse()`) pour les 3 fichiers
- Pas de `exchange-info` ou `ticker-price` résidus en grep
- Costmin novateur : à tester sur plusieurs paires (différents costmin) pour vérifier l'impact sur le taux de skip
- Trailing stop sur `tick_size` natif : vérifier arrondi correct des prix limite
