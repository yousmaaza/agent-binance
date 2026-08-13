# PR #379 — [BUG] Arrondir le prix stop-loss au tick_size avant pose Kraken

> **Mergée le** : 2026-08-13
> **Branche** : `feat/issue-378-arrondir-stop-loss-tick-size`
> **Issues** : #378

## Contexte

Lors de la pose d'ordres stop-loss (SL) via `kraken order --type stop-loss --price`, Kraken rejette les prix qui ne respectent pas le `tick_size` (écart minimum de prix acceptable) pour la paire donnée. Par exemple, SOL a un `tick_size` de 0.01 USDC, donc un prix comme 42.5678 sera rejeté.

Cette PR corrige le bug en arrondissant systématiquement le prix stop-loss au `tick_size` supporté **avant** de placer l'ordre, tant en Phase 5 (première pose du SL) qu'en Phase 0 (retry OCO).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase5_execution.py` | Modification | Arrondir `actual_stop` au `tick_size` avant appel `kraken order --type stop-loss` |
| `binance-bot/core/phases/phase0_oco_retry.py` | Modification | Arrondir `stop_calc` au `tick_size` avant appel `kraken order --type stop-loss` sur retry |
| `tests/test_phase5_execution.py` | Ajout test | Test que `actual_stop` est arrondi au `tick_size` (`TestStopLossPriceRoundedToTickSize`) |
| `tests/test_phase0_oco_retry.py` | Ajout test | Test que `stop_calc` est arrondi au `tick_size` sur retry (`TestOcoRetryStopPriceRoundedToTickSize`) |

### Fonctions modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `main()` (Phase 5) | `phase5_execution.py:167` | Modification | Ligne ajoutée après calcul de `actual_stop` : arrondir au `tick_size` via `round(round(stop_calc / tick) * tick, 8)` |
| `main()` (Phase 0 retry) | `phase0_oco_retry.py:152` | Modification | Ligne ajoutée après fetch du `tick_size` : arrondir `stop_calc` au `tick_size` avant retry de pose SL |

## Décisions techniques notables

- **Pattern d'arrondi** : réutilisation du même pattern déjà en place dans `phase0_trailing_stop.py` (`round(round(p / tick) * tick, 8)`). Ce pattern arrondit au tick le plus **proche**, pas systématiquement vers le bas.
  - Exemple SOL (tick 0.01) : 42.5678 → 42.57 ✅
  - Exemple LINK (tick 0.00001) : 9.123456 → 9.12346 ✅
  - Gère correctement les artefacts de précision flottante.

- **Pas de nouvel helper partagé** : le pattern est copié (duplication mineure) plutôt que factoriser en fonction, conforme à la philosophie du projet (minimalisme, pas d'abstraction pour un usage isolé à l'époque).

- **Fetch `tick_size` dans le même appel** : la Phase 5 récupère déjà `lot_decimals` via `binance("pairs", ...)`, donc le `tick_size` vient gratuitement du même appel API, sans surcharge.

- **Timing critique** : l'arrondi se fait **après** le calcul du SL (basé sur `actual_entry` et `stop_distance_pct`), mais **avant** la pose de l'ordre. Aucune modification de logique de gestion de risque.

## Impact sur l'architecture

Changement isolé, sans impact sur l'architecture globale :
- La Phase 5 continue de poser des ordres BUY MARKET suivi d'un OCO SL.
- La Phase 0 continue de rattraper les protections échouées.
- Aucune modification du flux de données, des états persistants, ou des composants externes.

## Références CLAUDE.md respectées

- **Règle 4 — Appels Kraken CLI via subprocess** : l'arrondi valide les prix **avant** l'appel `kraken order`, conformément au besoin de respecter les contraintes d'exchange.
- **Règle 6 — Convention horaire** : pas de logique horaire impactée.
- **Minimalisme** : changement chirurgical, une ligne par fichier, sans fonctionnalité spéculative.
- **Tests** : deux cas de test couvrent l'arrondi en Phase 5 et Phase 0, intégrés à la suite existante (79 tests verts).

## Vérifications effectuées

- ✅ Syntaxe Python : `python -c "import ast; ast.parse(...)"` sur les 4 fichiers modifiés.
- ✅ Suite de tests : 79 tests verts (pas de régression sur `lot_decimals`, autres phases).
- ✅ Tests spécifiques ajoutés : `TestStopLossPriceRoundedToTickSize` (Phase 5), `TestOcoRetryStopPriceRoundedToTickSize` (Phase 0).
