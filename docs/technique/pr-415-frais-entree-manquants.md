# PR #415 — [BUG] Frais d'entrée manquants sur positions ouvertes et trades clôturés

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-409-frais-entree-manquants`
> **Issues** : #409

## Contexte

Deux catégories de trades manquaient de frais d'entrée mesurés (`entry_fee_usdc`) :
1. **Positions encore ouvertes** (ex. ADA, BNB) : pas d'entrée, donc impossible d'afficher le PnL intermédiaire ou estimer frais totaux
2. **Trades déjà clôturés avec exit capté** (ex. XBT `616ab13c`, LINK `e3004b5a` en prod) : l'exit avait été pris en direct à la vente (Phase 5 capture immédiate), mais l'entrée avait échoué (rapprochement introuvable à ce moment) → incomplet

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/backfill_fees.py` | Modification (75 ajouts, 22 suppressions) | Logique de backfill raffinée : trois flux désormais distincts (positions ouvertes, trades clôturés incomplets, trades ordinaires) |
| `tests/test_backfill_fees.py` | Modification (70 ajouts, 1 suppression) | 4 tests nouveaux + 1 fixture ajustée pour couvrir les 3 cas |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_resolve_entry_fee()` | Ajoutée | Centralise le calcul des frais d'entrée (mesuré via `entry_order_id` OU estimé au taux du palier Kraken) — incrémente les compteurs `entries_measured`/`entries_estimated` de façon cohérente, retourne tuple `(entry_fee, estimated)` |
| `backfill()` | Modifiée | Gestion des trois flux : (1) positions ouvertes reçoivent seule l'entrée sans jamais estimer, (2) trades clôturés avec `exit_fee_usdc` présent mais `entry_fee_usdc` manquant → appel `compute_net_pnl()` pour recalculer tous les champs PnL nets, (3) flux nominal inchangé. Nouveau compteur `open_entries_backfilled` dans stats |
| `_coherence_diagnostic()` | Modifiée | Docstring enrichie, logique changée ligne 177 : **compare `pnl_gross_usdc` en priorité** (si le champ existe — trade dont l'exit a déjà été capté), sinon fallback sur `pnl_usdc` (comportement legacy #382). Évite faux positif sur ces trades où `pnl_usdc` stocké est déjà partiellement net |

### Logique de flux

#### 1. Position ouverte (status="open")

```python
if trade.get("status") != "closed":
    if trade.get("entry_fee_usdc") is not None and not force:
        stats["trades_skipped_already_done"] += 1
        continue
    entry_fee = _match_entry_fee(trade, fills, consumed)  # rapprochement uniquement
    if entry_fee is None:
        stats["trades_skipped_not_closed"] += 1  # pas d'entrée trouvée
        continue
    trade["entry_fee_usdc"] = entry_fee
    stats["open_entries_backfilled"] += 1
    continue  # NB: pas de champ de clôture touché (exit_price, exit_fee_usdc, fees_usdc, pnl_usdc, pnl_pct)
```

Invariants :
- Jamais d'estimation (entrée rapportée par Kraken = fiable)
- Jamais de champs de clôture ajoutés
- Compteur dédié `open_entries_backfilled`

#### 2. Trade clôturé avec exit présent, entrée manquante

```python
if not entry_fee_present and trade.get("exit_fee_usdc") is not None:
    # L'exit a été capté en direct, recompute l'entrée + PnL
    entry_fee, estimated = _resolve_entry_fee(trade, fills, consumed, stats)
    net = compute_net_pnl(
        float(trade.get("entry_price", 0) or 0),
        float(trade.get("exit_price", 0) or 0),
        float(trade.get("quantity", 0) or 0),
        entry_fee,
        float(trade["exit_fee_usdc"]),  # jamais re-matché, réutilisé
    )
    # Mise à jour complète champs liés au PnL net
    trade["entry_fee_usdc"] = entry_fee
    trade["fees_usdc"] = net["fees_usdc"]
    trade["pnl_gross_usdc"] = net["pnl_gross_usdc"]
    trade["pnl_usdc"] = net["pnl_usdc"]
    trade["pnl_gross_pct"] = net["pnl_gross_pct"]
    trade["pnl_pct"] = net["pnl_pct"]
    trade["fees_estimated"] = estimated
    stats["trades_updated"] += 1
    continue
```

Sécurité : `exit_fee_usdc` n'est **jamais re-matché** — le fill de sortie ne se reproduit jamais, la valeur stockée est définitive.

#### 3. Trade ordinaire (flux nominal, unchanged)

Deux côtés (entrée + sortie) rapprochés indépendamment, calcul PnL nominal.

### Amélioration du garde-fou cohérence

Avant : comparaison statique toujours sur `pnl_usdc`
Après (ligne 177, `_coherence_diagnostic`) :

```python
stored_pnl = trade.get("pnl_gross_usdc", trade.get("pnl_usdc"))
```

**Raison** : trades dont l'exit a déjà été capté en direct (Phase 5) contiennent `pnl_gross_usdc` (l'ancien PnL brut pré-backfill) et `pnl_usdc` déjà partiellement net (frais exit présents). Comparer contre `pnl_usdc` donnerait faux positif. Comparaison sur le brut `pnl_gross_usdc` (ou fallback `pnl_usdc` si absent) identifie les incohérences réelles.

## Décisions techniques notables

- **Séparation flux** : plutôt qu'une seule condition complexe, trois chemins distincts (open → positions ouvertes, `exit_fee_usdc` présent → recompute case, sinon → nominal) rend le code lisible et maintenable.
- **Extraction `_resolve_entry_fee()`** : évite duplication entre le cas "trade clôturé incomplet" et "nominal", centralise statistiques.
- **Appel `compute_net_pnl()` pour recompute** : réutilise la logique métier de Phase 5 (frais nets) au lieu de réimplémenter, garantit cohérence.
- **Pas d'estimation pour positions ouvertes** : entrée rapportée par Kraken via `entry_order_id` est l'unique source fiable ; l'estimateur par palier (taux historiques) n'aurait aucun sens pour une position active.

## Impact sur l'architecture

Changement isolé à `backfill_fees.py` et ses tests. Aucun impact architectural :
- Script reste un outil d'administration (lancé manuellement après merge + déploiement, jamais en production en boucle).
- États persistants (`trade_history.json`, `maker_pending_orders.json`, etc.) restent inchangés en structure.
- Fonctions publiques (`compute_net_pnl`, `_save_trade_history_atomic`) inchangées — réutilisées comme avant.

Bénéfice observé en prod : positions ADA/BNB ouvertes et trades XBT/LINK clôturés reçoivent entrée mesurée complète, `/perf` peut afficher PnL correct dès qu'on relance le script.

## Références CLAUDE.md respectées

- **Minimalisme** : ajout uniquement du strict nécessaire (une fonction, une condition, une stat), zéro abstraction spéculative
- **Modifications chirurgicales** : trois flux logiques séparées, chacun isolé, pas de `if` imbriquée monstrueuse
- **Tests** : 4 cas nouveaux couvrant les 3 flux (position ouverte seule entrée, skip déjà fait, trade clôturé complet, fixture ambiguë corrigée), suite intégration 155 PASS
- **Convention de backfill** : réutilisation des patterns #382 (paliers, consumed set, rapprochement window), extension cohérente
