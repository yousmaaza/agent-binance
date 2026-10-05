# PR #515 — Remonter le stop au prix d'entrée dès que le trade est en gain

> **Mergée le** : 2026-10-05
> **Branche** : `feat/issue-513-breakeven-stop-entree`
> **Issues** : #513

## Contexte

Les stops suiveurs (#56) et les recalibrages TP (#344) calculent leur distance d'ajustement depuis le **stop d'origine** du trade. Lorsque le tp_watcher remonter un stop au break-even (entrée + frais), ce nouveau stop devient supérieur au stop d'origine, ce qui rend la distance négative ou quasi-nulle. Cela fige le trailing stop et déduit les cibles TP (piège du recalibrage TP identifié dans le PR body).

Pour garantir une gestion dégradée du stop une fois en profit, il faut :
1. Persister le **stop d'origine** (initial_stop_price) dès la création du trade.
2. Offrir une stratégie break-even : détection du déclenchement, remplacement du stop avec gestion d'erreur.
3. Adapter le trailing stop et le recalibrage TP pour utiliser le stop d'origine, pas le stop courant.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/tp_watcher.py` | Modification majeure | Ajout de `_apply_breakeven()` et intégration au tick principal |
| `binance-bot/core/trade_helpers.py` | Ajout fonction | Nouvelle fonction `initial_stop_price()` pour retrouver/reconstuire le stop d'origine |
| `binance-bot/core/phases/phase0_trailing_stop.py` | Modification | Utilise `initial_stop_price()` au lieu de `stop_price` courant pour la distance |
| `binance-bot/core/phases/phase5_execution.py` | Modification mineure | Stocke `initial_stop_price` lors de la création du trade |
| `binance-bot/core/maker_watcher.py` | Modification mineure | Stocke `initial_stop_price` lors de l'enregistrement d'une position maker |
| `prompts/phases/phase0_snapshot.txt` | Modification | Référence `initial_stop_price` dans le recalibrage TP |
| `config.json` | Ajout clés | 3 nouvelles clés : `breakeven_enabled`, `breakeven_trigger_pct`, `breakeven_include_fees` |
| `scripts/breakeven_replay.py` | Nouveau | Script de rejeu sur les trades fermés pour mesurer l'impact break-even |
| `tests/test_breakeven.py` | Nouveau | 19 tests : déclenchement, pièges, recalibrage TP, erreurs de placement |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `initial_stop_price(trade, fee_round_trip_pct)` | Ajoutée | Récupère ou reconstruit le stop d'origine d'un trade. Priorité : champ `initial_stop_price` ; sinon reconstruction via `risk_usdc` ; sinon stop courant. |
| `_apply_breakeven(pos, current_price, cfg)` | Ajoutée | Détecte le déclenchement (prix >= entry × (1 + trigger_pct)), annule l'ancien stop et pose le nouveau au niveau break-even (entry, ou entry × (1 + fee_round_trip_pct) si frais inclus). Gère les erreurs : si nouveau stop échoue, repose l'ancien ; sinon flagge `protection_failed` pour rattrapage Phase 0. |
| `_place_sl_safe(pair, qty, price)` | Ajoutée | Wrapper autour de `_place_stop_loss()` qui capture toute exception et retourne `(txid, failed, err_msg, price_rounded)`. |
| `tp_watcher._tp_watcher_tick()` | Modifiée | Appel à `_apply_breakeven()` avant la vérification TP ; sauvegarde histor immedite si break-even appliqué (l'ancien txid est annulé). |
| `phase0_trailing_stop.py (boucle)` | Modifiée | Utilise `trail_dist = entry - initial_stop_price(trade)` au lieu de `stop_price` courant. Stocke `initial_stop_price` après chaque ajustement. |
| `phase0_snapshot.txt` | Modifiée | Bloc RECALIBRAGE TP utilise `stop_distance_pct = (entry_price - stop_origine) / entry_price` via l'importation `initial_stop_price` du trade. |

## Décisions techniques notables

- **Persévérance du stop d'origine via deux chemins** : (1) Champ direct `initial_stop_price` posé à l'entrée (Phase 5 + maker_watcher) ; (2) Reconstruction depuis `risk_usdc` pour les trades existants avant cette PR (formule inverse du dimensionnement Phase 4). Cela assure qu'aucun ancien trade ne casse à cause de l'absence de ce champ.

- **Pas de double application du break-even** : Le champ `breakeven_applied` empêche le déclenchement une seconde fois, même si le prix remonte au-dessus du trigger.

- **Lock de cycle respecté** : `_apply_breakeven()` détecte si un cycle 4h est en cours (via `is_locked()`) avant de tenter l'annulation/remplacement, pour éviter une course avec les phases.

- **Gestion d'erreur progressive** : Si le nouveau stop échoue → tentative repose de l'ancien. Si les deux échouent → `protection_failed=True` et notification d'alerte ; la Phase 0 (OCO retry) reprend le relais au cycle suivant.

- **Nivellement de frais optionnel** : `breakeven_include_fees=true` (par défaut) pose le stop à `entry × (1 + fee_round_trip_pct)` pour un vrai break-even net ; sinon au-delà de `entry` uniquement.

- **Étude de rejeu** : Script `scripts/breakeven_replay.py` teste le break-even sur les trades fermés (bougies publiques Kraken) pour mesurer le gain moyen vs la stratégie sans break-even. Résolution mixte (15 min sur 7j, 1h sur 30j, 4h sinon) pour coller à la réalité des données disponibles. Paramètre retenu : déclencheur 1,5 % + niveau entry+frais (6–10 USDC gagnés vs la réalité).

## Impact sur l'architecture

- **TP Watcher enrichi** : Ajout de `_apply_breakeven()` en-dehors du lock principal, avec gestion d'erreur fine et notifications Telegram.
- **Trailing stop déplafonné** : Le trailing stop n'est plus figé une fois le break-even appliqué, grâce à la mémorisation du stop d'origine.
- **Recalibrage TP préservé** : Le recalibrage utilise le stop d'origine, pas le stop courant, évitant la dégradation des cibles attendues.
- **Pas de nouvel état persistant** : Les champs `initial_stop_price`, `breakeven_applied`, `protection_failed` vivent dans `state/trade_history.json` sans nouveau fichier.

## Références CLAUDE.md respectées

- **Minimalisme** : `_apply_breakeven()` est isolée, repose sur les fonctions existantes (`_place_stop_loss`, `is_locked`, `acquire_lock`) et n'ajoute pas de classe ou abstraction supplémentaire.

- **Pas de gestion d'erreur sur scénarios impossibles** : Les trois clés config sont injectées avec des defaults sensibles (`breakeven_enabled=true`, `breakeven_trigger_pct=0.015`, `breakeven_include_fees=true`) ; les erreurs réseau ou de Kraken restent captées au niveau le plus bas.

- **UTC interne, affichage local** : Les dés ne changent rien aux horaires internes (tout reste UTC). Les notifications Telegram sont envoyées sans conversion (le message lui-même est en français vulgarisé, l'heure n'est pas affichée dans le message break-even).

- **Pas de modification CLAUDE.md** : Aucune règle métier touchée, juste une stratégie enrichie.

- **Tests via `unittest` stdlib** : 19 tests en `tests/test_breakeven.py`, aucune dépendance externe au-delà de ce qui est déjà en place.

## Notes futures

- Bug adjacent non corrigé (#513 PR body) : dans `phase0_trailing_stop.py`, si l'annulation du SL réussit mais la pose du nouveau échoue, la position reste sans stop et sans `protection_failed`. Prioriser en Phase 0 OCO retry (#514).
- PR #514 (prise de profit partielle) non traitée — à traiter indépendamment.
- Limites du rejeu : ignore le stop suiveur et les ventes sur signal ; à remesurer après 30+ trades réels en production.
