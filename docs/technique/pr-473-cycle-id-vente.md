# PR #473 — [M1] Enregistrer le cycle_id au moment de la vente

> **Mergée le** : 2026-09-06
> **Branche** : `feat/issue-470-cycle-id-vente`
> **Issue** : #470

## Contexte

Traçabilité des sorties : chaque position clôturée doit être liée au cycle qui l'a fermée (pour les fermetures en Phase 0) ou explicitement marquée comme « hors cycle » (pour les fermetures par le TP watcher). Permet de :
- Lier une vente visible au tableau de bord au cycle qui l'a décidée
- Distinguer les ventes « hors cycle » (TP atteint entre deux cycles) des ventes « intra-cycle »
- Identifier les ventes antérieures à cette PR (champ absent) sans erreur

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/maker_exit_watcher.py` | Modification | Ajoute paramètre `cycle_id` à `attempt_maker_exit()` et le transporte via `maker_exit_pending_orders.json` |
| `binance-bot/core/phases/phase0_profit.py` | Modification | Passe `cycle_id=CYCLE_ID` à `attempt_maker_exit()` pour fermetures Phase 0 profit |
| `binance-bot/core/phases/phase0_oco_retry.py` | Modification | Ajoute `cycle_id: CYCLE_ID` aux deux points de fermeture scriptée (force_close_above_tp, exhausted_fallback) |
| `binance-bot/core/phases/phase5_execution.py` | Modification | Ajoute `cycle_id: CYCLE_ID` quand le prix dépasse TP au moment du fill |
| `binance-bot/core/phases/phase7_mongo.py` | Modification | Publie `cycle_id` dans la projection MongoDB `closed_trades` |
| `binance-bot/core/tp_watcher.py` | Modification | Passe `cycle_id=None` explicite à `attempt_maker_exit()` car sortie hors cycle |
| `dashboard/app.py` | Modification | Collecte les `cycle_id` présents dans le journal (`known_cycle_ids`) et les transmet à `build_sales_view()` |
| `dashboard/viewdata.py` | Modification | Ajoute paramètre `known_cycle_ids` à `build_sales_view()` et `build_sales_rows()` ; marque chaque vente avec `cycle_linkable` (cycle dans le journal) ou non |
| `dashboard/templates/dashboard.html` | Modification | Affiche 4 cas distincts : lien (si `cycle_linkable`), identifiant texte (si réel mais hors journal), « hors cycle » (si `None`), « inconnu » (si absent — vente antérieure) |
| `prompts/phases/phase0_snapshot.txt` | Modification | Documente que les ventes SL hit posent `cycle_id=None` |
| `prompts/phases/phase3_scoring.txt` | Modification | Documente que les ventes sur signal posent `cycle_id="__CYCLE_ID__"` |
| `tests/test_*.py` | Modification | 8 fichiers test : 4 cas du dashboard, transport du `cycle_id` dans maker_exit, ventes Phase 0, OCO retry, Phase 5 |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `attempt_maker_exit(…, cycle_id=None)` | Modifiée | Reçoit `cycle_id` optionnel, le stocke dans l'enregistrement pending |
| `_finalize_position()` | Modifiée | Copie `cycle_id` depuis le pending vers la position finalisée |
| `build_sales_view(…, known_cycle_ids=None)` | Modifiée | Reçoit l'ensemble des `cycle_id` présents dans le journal |
| `build_sales_rows(…, known_cycle_ids=None)` | Modifiée | Marque chaque vente avec `cycle_linkable` selon si son `cycle_id` est dans le journal |

## Décisions techniques notables

- **Transport via pending orders** : Le `cycle_id` transitant par `maker_exit_pending_orders.json` garantit que les ventes décidées en Phase 0 mais exécutées ultérieurement par le watcher restent tracées au cycle qui les a décidées (sans ce transport, les ventes suivies par le watcher perdraient leur origine cycle).
  
- **4 cas distincts au dashboard** : 
  1. **Linkable** (`cycle_id` présent dans le journal) → lien HTML vers le cycle
  2. **Non-linkable** (`cycle_id` réel mais hors de la fenêtre du journal `CYCLES_JOURNAL_LIMIT`) → texte pur (jamais de lien mort)
  3. **Explicite "hors cycle"** (`cycle_id: None`) → cellule unique « hors cycle » distinguée de l'absence
  4. **Inconnu** (champ absent, ventes antérieures à cette PR) → marqueur « vente antérieure à l'enregistrement du cycle »
  
  Cette distinction évite les liens morts et permet de différencier « on ne sait pas » de « hors cycle volontaire ».

- **Modifications chirurgicales** : Phase 0 profit et OCO retry ajoutent `cycle_id` uniquement aux lignes qui ferment une position — pas de refactoring adjacent ni de cleanup du code pré-existant (notamment 2 erreurs ruff E702 pré-existantes sur `phase0_oco_retry.py` laissées intactes).

- **Cohérence TP watcher** : `cycle_id=None` explicite au lieu de l'omettre, pour clarifier que c'est une sortie hors cycle (pas un oubli).

## Impact sur l'architecture

Changement isolé, pas d'impact architectural majeur :
- Ajout d'un champ optionnel à la structure `trade` (clôturé)
- Transport via `maker_exit_pending_orders.json` existing (aucune nouvelle structure)
- Dashboard enrichi de la logique « cycle_linkable » (aucun changement de flux)
- Tous les appels à `attempt_maker_exit()` migrent le paramètre optionnel sans modification du contrat global

## Références CLAUDE.md respectées

- **Minimalisme** : Code minimum qui résout le problème — aucune abstraction spéculative, aucun refactoring adjacent
- **Modifications chirurgicales** : Toucher uniquement ce qui est nécessaire ; 2 erreurs ruff E702 pré-existantes sur `phase0_oco_retry.py` laissées intactes (modification chirurgicale)
- **Stdout/stderr capturés** : Les logs de `cycle_<id>` continuent d'être sauvegardés (aucun changement au capture)
- **État persistant JSON** : Nouveau champ `cycle_id` versé dans `trade_history.json` et `maker_exit_pending_orders.json` (JSON files existantes)
- **Toute modification via PR** : Workflow complet ticket → branche → PR → merge (règle #3)

## Tests

- ✅ `test_phase0_profit.py` : direct_close + maker_exit_handoff portent `cycle_id` non-nul
- ✅ `test_phase0_oco_retry.py` : force_close et exhausted_fallback portent `cycle_id` non-nul
- ✅ `test_phase5_execution.py` : immediate_close_above_tp porte `cycle_id` non-nul
- ✅ `test_tp_watcher.py` : watcher porte explicitement `cycle_id: None`
- ✅ `test_maker_exit_watcher.py` : 4 cas du transport (dans/hors journal) sans déduction
- ✅ `test_dashboard_viewdata.py` : 4 cas du cycle_id traversent `build_sales_view()` sans crash
- ✅ `test_dashboard_app.py` : 4 cas du cycle_id rendus distinctement dans le HTML (lien/texte/« hors cycle »/« inconnu »)
- ✅ `pytest` : 497 passed
- ✅ `ruff check` : aucune erreur nouvelle (2 erreurs E702 pré-existantes laissées)
- ⚠️ Redémarrage manuel du bot + `/status` : à faire par l'utilisateur avant merge

## Références

- Ticket : #470 — Enregistrer le cycle_id au moment de la vente
- Amont (ventes sur signal) : #472 (hors scope, mention dans phase3_scoring.txt)
- Précédent (TP watcher) : #321 — Ajouter thread watcher take profit temps réel
- Précédent (maker exit) : #390 — Watcher de sorties maker LIMIT post-only
