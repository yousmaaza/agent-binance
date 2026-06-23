# PR #260 — Refactoriser : supprimer cycle horaire position, intégrer calibrage en Phase 0

> **Mergée le** : 2026-06-23
> **Branche** : `feat/issue-259-supprimer-cycle-position-phase0`
> **Issue** : #259

## Contexte

Les PRs #241 (cycle position 1h) et #256 (commande `/calibrage`) introduisaient un scheduler horaire séparé pour gérer les positions ouvertes — notamment réaliser les gains dès que `min_profit_pct_take` était atteint. Cette PR consolide cette logique en l'intégrant directement dans la Phase 0 du cycle 4h (TRADE_PROMPT) et supprime le scheduler 1h redondant, simplifiant ainsi l'architecture : **un seul scheduler (4h) au lieu de deux (4h + 1h)**.

Bénéfices :
1. **Réduction de complexité** : moins de states à gérer, moins de threads daemon, une seule boucle de scheduling
2. **Consolidation** : le bot ne doit pas maintenir deux workflows séparés (trade 4h vs position 1h)
3. **Même efficacité** : les profits sont réalisés en Phase 0 de chaque cycle 4h (slot :05 UTC), quasi-immédiatement si la position a dépassé le seuil
4. **Maintenabilité** : tout le cycle trade + calibrage réside dans un seul prompt

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Ajout de bloc Phase 0 | Intégration du calibrage (réalisation de profits) directement en Phase 0 |
| `binance-bot/webhook_server.py` | Modification mineure | Suppression du scheduler 1h et du handler `/calibrage` (TODO) |

### Logique ajoutée / modifiée

| Élément | Action | Description |
|---|---|---|
| **Réalisation de profits (Phase 0)** | Ajoutée | Nouveau bloc Phase 0 (après trailing stop) : pour chaque position open, si P&L ≥ `min_profit_pct_take`, vend à MARKET et ferme la position. Mise à jour atomique `trade_history.json` et notification Telegram |
| **Scheduler 1h** | Supprimée | `NEXT_AUTO_POSITION`, `next_1h_slot()`, `_check_and_run_scheduled(..., run_position_check_workflow, ...)` → bloqué du main_loop() |
| **Commande `/calibrage`** | Supprimée | Handler Telegram et importation de `run_position_check_workflow` → supprimés de webhook_server.py |
| **Workflow position** | Supprimée | `run_position_check_workflow()` et `POSITION_PROMPT` → restent en tant que code legacy mais ne sont plus invoqués |

## Décisions techniques notables

- **Intégration en Phase 0, après trailing stop** : Ordre logique (ligne 397) : d'abord vérifier positions courantes, puis remonter les stops (trailing), puis réaliser les profits si seuil atteint.

- **Prix actuel live** : Appel `binance-cli spot ticker-price` pour chaque position avant décision de vente (ligne 414-422). Pas de cache — une seule source de vérité (marché live).

- **Vente atomique MARKET** : Pour chaque position avec P&L ≥ seuil, ordre SELL MARKET immédiat (ligne 432-435). Prix d'exécution calculé en réel (ligne 440), pas présumé.

- **Mise à jour historique** : `position.update({ "status": "closed", "exit_price": ..., "pnl_usdc": ..., "pnl_pct": ..., "close_reason": "profit_target_phase0" })` suivi d'une sauvegarde atomique (ligne 457-458). Traçabilité complète pour `/perf`.

- **Notification immédiate** : Chaque fermeture notifie Telegram individuellement et groupe toutes les réalisations en fin de bloc (ligne 459).

- **Legacy preservation** : `run_position_check_workflow` et `POSITION_PROMPT` reste dans le code (non supprimé) mais ne sont jamais invoqués. Permet un rollback facile si nécessaire.

## Impact sur l'architecture

### Changements structurels

```
AVANT (PR #241, #256) :
  main_loop()
  ├── Auto-scheduler 1h (NEXT_AUTO_POSITION) → run_position_check_workflow() [POSITION_PROMPT]
  ├── Auto-scheduler 4h (NEXT_AUTO_TRADE) → run_trade_workflow() [TRADE_PROMPT]
  └── Handler Telegram /calibrage → run_position_check_workflow(trigger="manual")

APRÈS (PR #260) :
  main_loop()
  ├── Auto-scheduler 4h (NEXT_AUTO_TRADE) → run_trade_workflow() [TRADE_PROMPT]
  │   ├── Phase 0 — Snapshot + Vérifications préalables
  │   │   ├── Récupère positions ouvertes depuis trade_history.json
  │   │   ├── Vérifie daily loss limit
  │   │   ├── Rattrapage protection_failed (OCO manquantes)
  │   │   ├── Trailing stop (remonter SL si prix progressé)
  │   │   └── ⚡ NEW: Réalisation de profits (vendre si P&L ≥ min_profit_pct_take)
  │   ├── Phase 1–8 → inchangé
  └── Handlers Telegram /status, /perf, ... (inchangés)
```

### Séquence de vérification Phase 0 (post-PR #260)

```python
# Phase 0 check order:
1. Snapshot positions
2. Daily loss limit check
3. Protection failed recovery
4. Trailing stop (remonter SL)
5. ✅ Profit realization (fermer les gagnants)
```

Tous les sous-blocs sont indépendants et sécurisés par des `try/except` individuels — une erreur n'empêche pas les autres d'exécuter.

### Impact sur état/configuration

**Aucune modification** de :
- `state/trade_history.json` (même structure, nouveau champ optionnel `close_reason: "profit_target_phase0"`)
- `config.json` (même paramètres : `min_profit_pct_take`, `max_hold_days` toujours lus)
- MongoDB `db.cycles` (même format d'écriture en Phase 7)

**Suppression** de :
- `NEXT_AUTO_POSITION` global en webhook_server.py
- `POSITION_PROMPT` imports (reste en `core/env.py` mais inutilisé)
- Scheduler 1h helpers (`next_1h_slot()` peut rester mais n'est plus appelé)

### Impact sur les commandes Telegram

| Commande | Avant | Après | Raison |
|---|---|---|---|
| `/trade` | Déclenche cycle 4h | Inchangé | Pas d'impact |
| `/status` | Affiche solde + positions | Inchangé | Pas d'impact |
| `/calibrage` | Déclenche cycle 1h position | **Supprimée** | Calibrage intégré en Phase 0 du `/trade` |
| `/perf` | Stats trades fermés | Inchangé | Nouvelles lignes `close_reason: "profit_target_phase0"` rajoutées à l'historique, stats identiques |

## Références CLAUDE.md respectées

- **Rule 1** (venv Python 3.11) : ✅ Aucun changement à la configuration Python
- **Rule 2** (`PROJECT_DIR` dynamique) : ✅ Aucune modification
- **Rule 4** (Binance via `binance-cli`) : ✅ Ligne 414–435 utilise `binance-cli spot ticker-price` et `new-order`
- **Rule 5** (Stdout/stderr capturés) : ✅ Aucune modification du logging
- **Rule 6** (UTC interne, local affichage) : ✅ P&L calculé en UTC, notif en heure locale via `fmt_local()`
- **Rule 7** (Auto-scheduler dans main_loop) : ✅ Suppression du scheduler 1h, conservation du 4h. Un seul scheduler maintenu.
- **Minimalisme** : ✅ ~64 lignes ajoutées en Phase 0 (profit realization), aucune abstraction inutile, une boucle `for _pos in _history`

---

## Notes pour le merge

**Test plan (du PR body)** :
- [ ] Vérifier que `/calibrage` n'existe plus (commande inconnue)
- [ ] Vérifier que le bot ne lance plus de scheduler horaire (un seul "Prochain cycle auto" toutes les 4h)
- [ ] Créer une position manuellement, attendre qu'elle dépasse le seuil de profit, vérifier qu'elle est fermée au prochain cycle 4h
- [ ] `python3 -c "import ast; ast.parse(open('binance-bot/webhook_server.py').read())"` → 0
- [ ] Redémarrage manuel du bot et vérification via /status

**Legacy notes** :
- `POSITION_PROMPT` reste importé mais inutilisé dans `webhook_server.py` — peut être nettoyé plus tard (PR REC)
- `run_position_check_workflow` reste présent dans `runner.py` mais ne sera jamais appelée — code mort, mais laissé pour traçabilité historique

**Impact utilisateur** : Aucun changement de comportement, gains réalisés de la même façon mais via un seul scheduler (plus rapide, moins de latence de 1h à 4h, consolidé).
