# PR #394 — fix(backfill): pnl_gross_usdc reprend la valeur stockée + garde-fou de cohérence

> **Mergée le** : 2026-08-22
> **Branche** : `fix/backfill-pnl-gross-coherence`
> **Issues** : #382 (post-mortem)

## Contexte

La PR #391 a introducé le script `scripts/backfill_fees.py` pour recopier dans `pnl_gross_usdc` le PnL brut **déjà stocké** dans les trades historiques (avant déduction des frais Kraken), avant de calculer le PnL net `pnl_usdc = pnl_gross_usdc - fees_usdc`. 

Lors de l'exécution en production sur la VPS, le script a rencontré un trade legacy Binance (SYN, trade_id `38515bab`, datant du 2026-06-26) dont le `pnl_usdc` stocké (-1.165 USDC) ne correspondait pas à `(exit_price - entry_price) * quantity` (calcul donnant +42.823 USDC pour ce trade). Le script recalculait au lieu de reprendre l'ancien calcul → injection de ~44 USDC fictifs.

Ce trade legacy porte des marqueurs Binance (`entry_order_id` entier, champs `order_list_id`/`stop_order_id`/`tp_order_id`) et des prix incohérents : `close_reason: "sl_hit"` mais `exit_price` 61% au-dessus de `entry_price` (un stop-loss ne peut pas sortir en gain). Le `pnl_usdc` original (-1.165) était correct, mais les champs prix/quantité ne permettaient pas de le reconstituer — d'où le bug de #391.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/backfill_fees.py` | Modification | Correctif du calcul de `pnl_gross_usdc` + nouveau garde-fou de cohérence |
| `tests/test_backfill_fees.py` | Ajout | Tests des cas limites et du garde-fou |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_coherence_diagnostic(trade)` | Ajoutée (ligne 142) | Compare `pnl_usdc` stocké vs `(exit_price - entry_price) * quantity`. Retourne un diagnostic détaillé si l'écart relatif dépasse 1% (COHERENCE_REL_TOLERANCE), `None` sinon. Gère aussi les trades fermés sans `pnl_usdc` stocké. |
| `backfill(history, fills, force)` | Modifiée | Signature de retour passée de `(history, stats)` à `(history, stats, incoherent_trades)`. Ajoute un appel à `_coherence_diagnostic()` pour chaque trade candidate : si le diagnostic signale une incohérence, le trade n'est **pas modifié** et est ajouté à `incoherent_trades`. |
| `main()` | Modifiée | Affiche en résumé la liste complète des trades incohérents avec détails (trade_id, coin, pnl_usdc_stored, pnl_recomputed_from_prices, écart relatif %), tant en `--dry-run` qu'en mode réel. |

## Décisions techniques notables

- **Reprendre, ne pas recalculer** : `pnl_gross_usdc` prend la valeur de `pnl_usdc` déjà stockée (ligne 233 : `pnl_gross_usdc = trade["pnl_usdc"]`), jamais `(exit_price - entry_price) * quantity`. C'est le contrat du ticket #382 : « pnl_gross_usdc — l'ancien calcul ». Cette décision priorise la cohérence historique sur la reconstitution mathématique, car les données legacy Binance ne sont pas fiables (champs prix/quantité potentiellement incohérents).

- **Seuil de tolérance 1% relatif** : La constante `COHERENCE_REL_TOLERANCE = 0.01` (ligne 49) défait le seuil à partir duquel un trade est considéré comme « incohérent » et non modifiable. Ce seuil tolère les petites divergences (arrondis, rounding de volume) tout en capturant les incohérences majeures comme SYN (écart >600%, bien au-delà du seuil). Le seuil est aisément ajustable si besoin.

- **Diagnostic exhaustif, pas de crash** : La nouvelle fonction `_coherence_diagnostic()` couvre aussi le cas edge d'un trade fermé sans `pnl_usdc` stocké. Au lieu de crasher sur `trade["pnl_usdc"]` plus tard, elle retourne un diagnostic avec `pnl_usdc_stored: None`, qui signale le problème sans modifier le trade.

- **Tests des cas limites** : Une nouvelle classe `TestBackfillCoherenceGuard` reproduit exactement le bug de prod (trade SYN), teste le case edge (closed sans pnl_usdc), et valide qu'un trade cohérent est toujours modifié normalement.

## Impact sur l'architecture

Changement isolé au script de backfill, aucun impact sur l'architecture globale. Le script `backfill_fees.py` est un outil CLI pour maintenance historique, non invoqué pendant le cycle de trading. L'ajout du retour `incoherent_trades` (tuple 3-uple au lieu de 2-uple) aurait pu casser le code client du backfill, mais le script `main()` est autonome et ne dépend pas d'importateurs externes.

## Références CLAUDE.md respectées

- **Minimalisme** : Ajout de deux nouvelles fonctions/branches + une constante = changement chirurgical limitant à la logique de backfill.
- **Modifications non spéculatives** : Le seuil COHERENCE_REL_TOLERANCE = 0.01 est documenté en commentaire et ajustable sans code business critique.
- **Tests unitaires** : Trois nouveaux tests couvrent les scénarios clés (bug prod SYN, case edge closed, cas nominal cohérent).

## Test plan

| Test | Résultat |
|---|---|
| `test_incoherent_legacy_trade_preserved_and_flagged` | ✅ Trade SYN non modifié, signalé avec écart >600% |
| `test_closed_trade_without_stored_pnl_flagged_not_crashed` | ✅ Pas de crash, diagnostic `pnl_usdc_stored: None` |
| `test_coherent_trade_within_tolerance_is_updated_normally` | ✅ Trade cohérent modifié sans problème |
| Suite complète (`python -m unittest discover -s tests`) | ✅ 113/113 tests OK |
| `ruff check` | ✅ Pas d'erreur de linting |
| `--dry-run` sur la VPS | À laisser à l'utilisateur après merge |

---

*Closes #382 (post-mortem et correction définitive de la recomputation de PnL brut).*
