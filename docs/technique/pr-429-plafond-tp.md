# PR #429 — [M1] Plafonner le TP à ce que le marché délivre réellement

> **Mergée le** : 2026-08-28
> **Branche** : `feat/issue-428-plafond-tp`
> **Issue** : #428

## Contexte

Le bot calculait des cibles de prise de profit (TP) basées sur une formule mécanique (`reward_risk_ratio` × distance du stop-loss). Sur un stop large (haut multiplicateur ATR), cela produisait des cibles jusqu'à 14% de hausse — très au-dessus de ce que le marché livre en pratique.

Analyse historique de 13 trades :
- Hausse médiane pendant la détention : **+4.9%**
- 90e centile : **+9.3%**
- Aucune cible > 8% jamais atteinte (0/4 cas)

Ces cibles inatteignables concentraient les pertes. La PR ajoute un plafond absolu configurable (`max_tp_pct = 0.06`, soit 6%) appliqué de façon identique aux quatre emplacements où le TP est calculé.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Ajout paramètre | Nouveau champ `max_tp_pct: 0.06` |
| `binance-bot/core/phases/phase4_sizing.py` | Modification | Applique le plafond au TP calculé en Phase 4 (dimensionnement) |
| `binance-bot/core/phases/phase5_execution.py` | Modification | Applique le plafond au TP recalculé après le fill de l'ordre MARKET (Phase 5) |
| `binance-bot/core/maker_watcher.py` | Modification | Applique le plafond au TP dans le watcher d'ordres LIMIT maker, posé sur la structure `pending` |
| `prompts/phases/phase0_snapshot.txt` | Modification | Documente le plafond dans la Phase 0 (recalibrage auto du TP) |
| `README.md` | Modification | Documente le paramètre dans la table de config et la section TP |
| `tests/test_phase4_sizing.py` | Ajout tests | 52 lignes — cas où le plafond s'applique vs ne s'applique pas |
| `tests/test_phase5_execution.py` | Ajout tests | 90 lignes — idem Phase 5 (MARKET + maker fallback) |
| `tests/test_maker_watcher.py` | Ajout tests | 62 lignes — cas du watcher maker |
| `tests/test_phase0_recalibrate_tp_floor.py` | Modification | 113 lignes — 13 nouveaux tests pour le plafond + recalibrage Phase 0 |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `phase4_sizing.py:L69-77` | Modifiée | Calcul TP avec plafond : `prix_tp = min(tp_mécanique, tp_plafond)` ; conflit plancher/plafond géré explicitement |
| `phase5_execution.py:L187-195` | Modifiée | Idem pour le TP recalculé après fill du MARKET |
| `maker_watcher.py:L133-141` | Modifiée | Idem pour le watcher, `max_tp_pct` posé sur la structure `pending` par phase5_execution.py |
| `_register_open_position()` | Modifiée | Lit `max_tp_pct` depuis le `pending` et applique la même logique |

## Décisions techniques notables

- **Plafond configurable simple, pas volatilité dynamique** : l'issue proposait deux approches (plafond fixe vs dérivé de la volatilité observée). Retenu : plafond fixe (`max_tp_pct = 0.06`) chargé depuis `config.json` — suffisant d'après l'analyse, sans nouvelle source de données, cohérent avec le style existant (`reward_risk_ratio`, `fee_round_trip_pct` sont déjà de simples clés configurables). Reste ajustable en production si un marché plus porteur montre des cibles plus hautes atteignables.

- **Quatre emplacements identiques, dont le prompt** : appliqué systématiquement dans les trois fichiers Python (Phase 4, Phase 5, maker_watcher) ET dans le bloc de recalibrage TP de `prompts/phases/phase0_snapshot.txt` (Phase 0, raisonnement Claude pur). Piège documenté dans #411 : omettre le prompt aurait annulé le correctif au cycle suivant (moins de 4h), sans trace.

- **Conflit plancher/plafond (#411) traité explicitement** : si le plafond ramène la cible sous le plancher de viabilité (entrée majorée de 2× les frais aller-retour), le plancher prime — la cible mécanique est conservée plutôt qu'une cible perdante. Testé dans les 4 emplacements.

- **Écart fin entre `min_profit_pct_take` (5%) et `max_tp_pct` (6%)** : collision non neutralisée. Le seuil net de prise de profit anticipée (Phase 0) se déclenche à 5.9% brut, le plafond de TP à 6%. L'écart n'est que de 0.1 point. Conséquence : sur une position qui progresse lentement (plusieurs heures), la prise de profit Phase 0 a 4h pour voir le passage à 5.9% avant que le watcher ne vise 6% — le plafond devient décoratif. Sur progression rapide (minutes), le TP Watcher (poll 2 min) capture le passage à 6% avant Phase 0 (poll 4h). **Non strictement systématique, mais écart trop fin**. Proposition pour clarifier : élargir l'écart (baisser `min_profit_pct_take` à 4.5% ou monter `max_tp_pct` à 6.5-7%) — à trancher dans une PR séparée.

## Impact sur l'architecture

Changement isolé, pas d'impact architectural. La formule TP existante est enrichie d'une borne supérieure indépendante de la résistance 4h. Interaction claire avec le mécanisme de plancher de viabilité (#411) — tous deux traitent la collision explicitement (la contrainte plus restrictive prime).

## Références CLAUDE.md respectées

- ✅ **Minimalisme** : la logique du plafond tient en 4 lignes par emplacement (calcul plafond + test conflit avec plancher)
- ✅ **Modifications chirurgicales** : chaque emplacement touche uniquement le calcul TP concerné, sans refactoring adjacent
- ✅ **Python via venv 3.11** : tests exécutés sur suite complète (226 tests, tous verts), `python -c "import ast; ast.parse(...)"` sur les 3 fichiers Python modifiés
- ✅ **Pas de secret hardcodé** : `max_tp_pct` chargé depuis `config.json` comme tous les autres paramètres
- ✅ **Conventions UTC/local** : la formule TP est purement numérique (prix), pas de conversions horaires
- ✅ **Agentification** : implémentation via l'agent `binance-dev` depuis branche `feat/issue-428-plafond-tp`

## Notes techniques

- `tests/test_phase0_recalibrate_tp_floor.py` isole les 13 nouveaux tests du plafond via `max_tp_pct=1.0` (le plafond est neutralisé pour ces cas existants), respectant le même pattern que `fee_round_trip_pct=0` déjà utilisé dans #411.
- La Phase 0 (recalibrage) est testée indirectement via `test_phase0_recalibrate_tp_floor.py` — le prompt n'a pas de script Python associé (raisonnement Claude pur). La logique du recalibrage est reproduite dans les tests (`tp_mecanique`, `tp_plancher`, `tp_plafond_absolu`) pour validation.
- Suite complète : **226 tests** (213 baseline + 13 nouveaux), tous verts — `python -m unittest discover -s tests -p "test_*.py"`.
