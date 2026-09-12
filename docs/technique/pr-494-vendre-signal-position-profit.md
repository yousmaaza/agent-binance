# PR #494 — [M1] Ne vendre sur signal qu'une position en profit

> **Mergée le** : 2026-09-12
> **Branche** : `feat/issue-492-vente-signal-en-profit`
> **Issues** : #492

## Contexte

Dans le cycle de trading Phase 3, quand le signal d'une position retombe (score ≤ 3), le bot doit décider de la vendre. Jusqu'à cette PR, la vente était inconditionnelle : peu importe que la position soit en profit ou en perte, elle était liquidée. 

Une mesure sur 31 ventes sur signal en production (juillet-septembre) révèle que cette approche détruit de la valeur : à 48h, le bilan est −60,39 USDC en conservant les positions en perte et leurs stops-loss intacts, contre +33,64 USDC à l'inverse. Cette PR introduit le filtre : **ne vendre sur signal que si la position est en profit sur le prix** (arbitrage brut, frais non déduits).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase3_signal_sell.py` | Modification | Ajout du filtre profit (Step 1 : vérification prix courant > prix d'entrée) + compteur `held` |
| `docs/strategie.html` | Modification | Documentation de la règle + tableaux de mesure historique (31 ventes, 48h horizon) |
| `docs/strategie.md` | Modification | Régénération depuis HTML |
| `prompts/phases/phase3_scoring.txt` | Modification | Documentation du compteur `held` à côté de `closed` et `maker_pending` |
| `tests/test_phase3_signal_sell.py` | Modification | 3 nouveaux tests (profit, perte, cours indisponible) + 13 scénarios existants complétés avec `ticker` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `phase3_signal_sell.py` (main loop) | Modifiée | Step 1 : avant toute annulation de stop, vérifier que `current_price > entry_price`. Si perte ou cours indisponible, incrémenter `held_count` et continuer. |

### Changements de sortie

Le fichier `/tmp/cycle_{CYCLE_ID}_phase3_signal_sell_output.json` s'étend :

```json
// Avant
{"closed": N, "maker_pending": M}

// Après
{"closed": N, "maker_pending": M, "held": H}
```

Où `held` = nombre de positions conservées faute de profit sur le prix ou cours indisponible.

## Décisions techniques notables

- **Filtre précoce (Step 1)** : La vérification du prix se fait avant toute annulation de stop ou pose d'ordre. Cela garantit qu'aucun effet de bord ne se produit si on décide de conserver : `sl_order_txid` reste intact, aucun ordre n'est posé ni annulé.

- **Appel `binance("ticker", pair, "-o", "json")` recopié de Phase 0** : Même motif que `phase0_profit.py:54-56`. Le champ retenu est `c[0]` (prix courant), avec fallback sur `entry_price` si la clé est absente — jamais de prix fabriqué (#469).

- **Exception sur ticker → conservation** : Si l'appel à Binance lève (timeout, API indisponible, JSON invalide), on conserve la position sans risquer une décision sur un prix inconnu. Le stop-loss gère la sortie.

- **Compteur `held` aligné** : Traité comme `maker_pending` (position en cours, mais pas clôturée dans ce cycle) pour la synthèse des décisions. Ne jamais présenter `held` comme une vente ratée — c'est le comportement voulu.

- **Notifications Telegram** : Deux messages distincts selon le cas :
  - Perte latente : `🛡️ {coin} : signal retombé (score X/10) mais position en perte (Y %) — conservée, le stop gère la sortie`
  - Cours indisponible : `🛡️ {coin} : cours indisponible, vente sur signal annulée par précaution — position conservée`

## Impact sur l'architecture

Changement isolé au sein de Phase 3. La décision de vente est plus nuancée (score + profit sur le prix), mais le reste du flux reste inchangé :
- Les inputs de Phase 3 (`sell_candidates` de Phase 3 scoring) demeurent identiques.
- Les outputs s'étendent avec `held`, sans affecter le traitement aval (Phase 4-7).
- Les notifications Telegram sont enrichies (deux nouveaux motifs de conservation).
- Aucun impact sur les phases antérieures (Phase 0-2) ni sur les watchers (Phase 7, `maker_exit_watcher.py`, `tp_watcher.py`).

## Tests

### Nouveaux tests (3)

- `TestSignalSellProfitFilter::test_profit_position_is_still_sold_as_before` : Une position en profit avec score ≤ 3 est vendue (comportement inchangé).
- `test_loss_position_is_held_without_touching_stop_or_placing_orders` : Une position en perte est conservée, `sl_order_txid` reste inchangé, aucun ordre posé/annulé.
- `test_unavailable_price_holds_position_without_selling` : Ticker indisponible → conservation, notification Telegram, aucun ordre.

### Scénarios existants mis à jour

13 scénarios de test existants ont été enrichis avec un champ `"ticker": {pair: {"c": [price, decimals]}}` pour que le nouveau Step 1 reçoive un prix valide. Aucun d'eux ne teste le chemin perte / indisponibilité (ils testaient des cas différents), donc leurs assertions restent inchangées : comportement de vente réussie préservé.

### Couverture

- Suite complète : 546 tests (543 baseline + 3 nouveaux), tous passants.
- `ruff check .` : 108 erreurs (aucune régression ; 0 erreur dans les fichiers modifiés).
- `scripts/strategie_to_md.py --check` : à jour.

## Références CLAUDE.md respectées

- **Règle 8 — Modification de stratégie** : `docs/strategie.html` mis à jour avec la nouvelle formule et la mesure chiffrée justifiant le changement (31 ventes historiques, −60,39 vs +33,64 USDC à 48h). `docs/strategie.md` régénéré via `scripts/strategie_to_md.py`.

- **Règle 6 — Convention horaire / UTC** : Le calcul du profit utilise `entry_price` et `current_price` (données brutes, sans fuseau horaire). La date du cycle est UTC (disponible dans `CYCLE_ID`).

- **Règle 4 — Appels Telegram via curl** : Les notifications sont émises par `tg()`, qui encapsule curl. Aucun `urllib` n'est ajouté.

- **Règle 2 — PROJECT_DIR dynamique** : Aucune modification ; le `PROJECT_DIR` existant (ligne 52) reste utilisé.

- **Règle 1 — venv Python 3.11** : Aucune dépendance ajoutée. Tout reste standalone.

