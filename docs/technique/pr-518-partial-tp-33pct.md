# PR #518 — [STRAT] Profit partiel à +3 % (33 %) et laisser courir le reste

> **Mergée le** : 2026-10-05
> **Branche** : `feat/issue-514-partial-tp-3pct-33pct`
> **Issues** : #514

## Contexte

Après un rejeu sur 77 trades (PR #514) montrant une amélioration mitigée avec le break-even seul (#513), l'utilisateur choisit d'implémenter une stratégie de profit partiel : vendre 33 % de la position dès que +3 % de gain est atteint, laisser 67 % courir vers le take-profit normal (1.5x le risque). Cela diminue l'exposition au drawdown précoce tout en conservant le potentiel d'upside sur le reliquat.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/tp_watcher.py` | Ajout + modification | +102 lignes : implémente `_apply_partial_tp()` — logique du profit partiel dans le watcher 2min |
| `binance-bot/core/maker_exit_watcher.py` | Ajout significatif | +207 lignes : nouvelles fonctions pour sorties partielles, logique `_finalize_partial()`, abandon `_settle_partial()` |
| `binance-bot/core/position_helpers.py` | Ajout | +22 lignes : `fold_partial_trades()` — replie les partials dans le parent pour `/perf` |
| `binance-bot/commands/perf.py` | Modification | -4/+6 lignes : utilise `fold_partial_trades()` pour comptabiliser 1 position = 1 gagnant/perdant |
| `binance-bot/core/dashboard_state.py` | Modification | -2/+5 lignes : idem `/perf` + inclut `parent_trade_id` |
| `config.json` | Ajout | +4 lignes : clés `partial_tp_enabled` (true), `partial_tp_trigger_pct` (0.03), `partial_tp_fraction` (0.33) |
| `docs/strategie.html` | Mise à jour | +65 lignes : documente la mécanique + formules sous-section 04/10 |
| `docs/strategie.md` | Régénération | +73 lignes : généré depuis `.html` via `scripts/strategie_to_md.py` |
| `scripts/partial_tp_replay.py` | AJOUTÉ | +120 lignes : replay local de la stratégie partielle sur l'historique (usage ad-hoc) |
| `tests/test_partial_tp.py` | AJOUTÉ | +484 lignes : 34 tests couvrant déclenchement, skips, reposés, comptabilité parent/enfant, `/perf` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_apply_partial_tp(pos, current_price, cfg)` | Ajoutée | Vérifie si le partiel doit déclencher (prix > entry × (1 + 3 %)), annule stop du parent, repose stop sur reliquat, pose limite post-only de la fraction |
| `attempt_partial_maker_exit(pos, fraction_qty, reliquat_qty, cfg, notify)` | Ajoutée | Pose la vente LIMIT post-only de la fraction (sans toucher au stop déjà reposé) |
| `restore_total_stop(pos, reliquat_qty, notify)` | Ajoutée | Si la limite échoue, annule stop du reliquat et en repose un sur la quantité totale |
| `_finalize_partial(history, pending, exit_price, exit_fee_usdc, qty_sold)` | Ajoutée | Crée enregistrement clôturé enfant (`trade_id-partial`, `close_reason="partial_tp"`, `parent_trade_id=<id>`), réduit parent au prorata |
| `_settle_partial(pending, history, fill)` | Ajoutée | Si la limite du partiel est annulée : comptabilise ce qui a été rempli, abandonne le reliquat, reprotège la quantité totale |
| `_handle_partial_chase_end(pending, history)` | Ajoutée | Fin de chasse : annule la limite et appelle `_settle_partial()` |
| `fold_partial_trades(closed)` | Ajoutée | Replie les enregistrements `partial_tp` dans leurs parents (pour compteurs `/perf` et dashboard) |
| `_tp_watcher_tick()` | Modifiée | Enchaînement : `_apply_breakeven()` (si < TP) → `_apply_partial_tp()` (si >= 3 %) → `attempt_maker_exit()` (si TP atteint) |

## Décisions techniques notables

### 1. Fenêtre sans stop minimale entre annulation et repose
La stratégie de Kraken (hold_trade immobilise le solde sous un stop) impose l'ordre strict : annuler stop → reposer sur reliquat → poser limite. Entre annulation et repose (~1-2s), la position est nue. Accepté comme acceptable : la probabilité d'un flash crash en 2s est très faible, et c'est le même pattern qu'un break-even (#513).

### 2. Jamais de MARKET forcé pour un partiel manqué
Contrairement aux sorties normales (step 3 de maker_exit_watcher : si TP+limit timeout → marché), un partiel dont la limite échoue est **abandonnée**, jamais vendu au marché. Raison : si l'ask s'enfuit, c'est souvent signe d'une impulsion haussière qu'on veut suivre sur le reliquat. Forcer au marché les 33 % ruinerait l'avantage stratégique.

### 3. Comptabilité : trade_id-partial et parent_trade_id
Pour chaque partiel rempli :
- Enregistrement enfant : `trade_id: "<parent>-partial"`, `parent_trade_id: "<parent>"`, `close_reason: "partial_tp"`
- Frais d'entrée au prorata : `entry_fee_usdc = entry_fee_total × (qty_sold / qty_parent)`
- Enregistrement parent réduit : `quantity -= qty_sold`, `risk_usdc *= (1 - ratio)`, `entry_fee_usdc -= share`
- `/perf` compte une position = un gagnant/perdant (via `fold_partial_trades()`)

### 4. Un seul essai par position : partial_tp_done=True au premier déclenchement
Même si l'ordre limit échoue, le flag `partial_tp_done` est posé dès que le stop a été touché. Jamais de boucle cancel/replace toutes les 2 min. Raison : l'ordre ou son abandon est un évènement "maintenant", pas une opportunité renouvelable chaque tick.

### 5. Partiel sauté si quantité insuffisante : partial_tp_skipped="below_min"
Si la fraction OU le reliquat < `min_order_usdc` (9 USDC) OU < `ordermin` Kraken : flag `partial_tp_done=True` et `partial_tp_skipped="below_min"` (no-op, position continue).

## Impact sur l'architecture

### Flux watcher 2min (tp_watcher.py)
```
Pour chaque position ouvert :
  Prix < TP_price :
    → _apply_breakeven()       (si gain && stop < breakeven)
    → _apply_partial_tp()      (NEW : si gain >= 3 % && partial_tp_enabled)
         ├─ annule stop parent
         ├─ repose stop reliquat
         └─ pose limite fraction
            → attempt_partial_maker_exit()
               └─ enqueue maker_exit_pending_orders.json
    → [continue au tick suivant]
  
  Prix >= TP_price :
    → attempt_maker_exit()     (sortie normale ou post-profit-partiel)
```

### État persistant (state/)
- **Nouveau** : clés dans chaque position ouverte :
  - `partial_tp_done: bool` — profit partiel a été tenté
  - `partial_tp_skipped: str | null` — raison du skip (below_min, limit_failed, stop_failed)
- **Existing** : maker_exit_pending_orders.json étend ses enregistrements avec :
  - `partial: bool` (optionnel, defaults to false)
  - `reliquat_qty: float` — quantité restante protégée (pour restore_total_stop si abandon)
- **Existing** : maker_exit_watcher_state.json inchangé structurellement

### Comptabilité (trade_history.json)
Les partials ajoutent une deuxième étape de clôture :
1. Remplissage partiel → enregistrement enfant clôturé (`status: "closed"`, `close_reason: "partial_tp"`)
2. Parent continue jusqu'au TP ou stop, enregistrement réduit

Exemple :
```json
{
  "trade_id": "COIN_001",
  "quantity": 100,
  "pnl_usdc": 150.50
}
↓ (après partial 33/67)
{
  "trade_id": "COIN_001-partial",
  "parent_trade_id": "COIN_001",
  "quantity": 33,
  "pnl_usdc": 48.00,
  "close_reason": "partial_tp"
},
{
  "trade_id": "COIN_001",
  "quantity": 67,
  "pnl_usdc": 102.50
}
```

### Dashboard et /perf
- `fold_partial_trades()` replie les enfants dans le parent pour comptage : 1 position = 1 gagnant/perdant
- Sommes (frais, périodes) restent sur les lignes brutes (pas de double-compte)
- `parent_trade_id` inclus dans dashboard_state pour traçabilité

## Références CLAUDE.md respectées

- **Règle 3** (venv 3.11 + git-perso) : Tests lancés via `.venv/bin/python -m pytest` ✅
- **Règle 5** (logs toujours sauvegardés) : Cycle logs inchangés, format inchangé ✅
- **Règle 6** (UTC interne, affichage local) : Tous timestamps en UTC, notifications en heure locale ✅
- **Règle 8** (docs/strategie.html à jour) : Mise à jour + régénération docs/strategie.md ✅
- **Minimalisme** : Zéro abstraction hors la nécessité, zéro gestion d'erreur pour cas impossibles ✅
- **Modifications chirurgicales** : Ajout = nouvelles fonctions + clés config, pas de refactor adjacent ✅

## Limites et précautions

1. **Rejeu non concluant** : Le replay sur 77 trades ne montrait pas de gain net clair (médiane -0,01). Implémenter quand même est un choix utilisateur ; à remesurer après 30+ trades réels.
2. **Conflits potentiels** : PR #516 peut toucher `config.json` et `docs/strategie.html` — les deux diffent. Résolution attendue post-merge : regénérer le MD.
3. **Si l'annulation du stop échoue en fin de chasse** : la fraction reste sans stop (alerte Telegram, intervention manuelle).
4. **Dépendances** : Partiel dépend de `maker_exit_enabled: true` — si désactivé, pas de partiel.
5. **Limite connue** : Un partiel dont le parent est toujours ouvert apparaît comme un trade clôturé dans `/perf` jusqu'à clôture du parent (attendu, pas un bug).

## Tests

- ✅ 34 nouveaux tests dans `tests/test_partial_tp.py` :
  - Déclenchement conditions (prix, frais, breakeven)
  - Skips sous seuil (min_order, ordermin)
  - Ordres stop et limites (repose, abandon)
  - Comptabilité parent/enfant
  - Intégration `/perf` et dashboard
- ✅ `.venv/bin/python -m pytest` : 689 passés
- ✅ `scripts/strategie_to_md.py --check` : à jour
- ✅ All Kraken CLI calls mocked
