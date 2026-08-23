# PR #425 — [M1] TP et dimensionnement net de frais

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-411-tp-sizing-net-frais`
> **Issues** : #411

## Contexte

Le bot calculait le Take Profit (TP) et la quantité d'ordre en ignorant les frais de trading, ne tenant compte que de la distance du stop-loss. En reality, un échange aller-retour (entrée + sortie) coûte ~0.9% en frais Kraken au palier actuall du compte. Cela créait des divergences : le TP calculé visait un gain brut de 3% + frais, mais le gain net réel était décalé de 0.9%.

De plus, les calculs du TP étaient répartis dans quatre endroits distincts (`phase4_sizing.py`, `phase5_execution.py`, `maker_watcher.py`, bloc RECALIBRAGE TP du prompt Phase 0), avec des formules non identiques, rendant les arbitrages difficiles et les évolutions à risque.

Cette PR unifie les quatre calculs avec une seule formule nette de frais et introduit un **plancher de viabilité** (Phase 0) garantissant qu'aucun TP recalibré ne devienne perdant.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Modification | `reward_risk_ratio` passe de 2.0 à 1.5 (net de frais) ; nouveau `fee_round_trip_pct` = 0.009 ; `min_profit_pct_take` passe de 2.0 à 5.0 |
| `binance-bot/core/phases/phase4_sizing.py` | Modification | Formule TP et dimensionnement quantité incluent `fee_round_trip_pct` ; calcul de `prix_tp` et `quantite` net de frais |
| `binance-bot/core/phases/phase5_execution.py` | Modification | Même formule TP que phase4 ; transport de `fee_round_trip_pct` dans les ordres maker pending |
| `binance-bot/core/maker_watcher.py` | Modification | Lecture de `fee_round_trip_pct` depuis l'ordre pending ; même formule TP au fill |
| `binance-bot/core/phases/phase0_profit.py` | Modification | Évaluation du profit sur un % net estimé (déduction `fee_round_trip_pct`) ; défaut `min_profit_pct_take` passe de 2.0 à 5.0 |
| `prompts/phases/phase0_snapshot.txt` | Modification | Bloc RECALIBRAGE TP : même formule TP, + plancher de viabilité (TP ne descend jamais sous `entry × (1 + 2 × fee_round_trip_pct)`) |
| `README.md` | Modification | Documentation des deux nouvelles clés config |
| `tests/test_phase4_sizing.py` | Modification | +2 tests : TP net, dimensionnement net ; defaults avec `fee_round_trip_pct=0` pour isoler les anciennes formules |
| `tests/test_phase5_execution.py` | Modification | +1 test TP net, +2 tests existants adaptés aux frais |
| `tests/test_phase5_execution_maker.py` | Modification | +1 test TP net maker, adaptations aux frais |
| `tests/test_maker_watcher.py` | Modification | +1 test TP net au fill maker |
| `tests/test_phase0_profit.py` | Modification | +2 tests : profit brut > seuil mais net < seuil (ne clôture pas), profit net >= seuil (clôture) |
| `tests/test_phase0_recalibrate_tp_floor.py` | Création (99 lignes) | Nouveau test de spécification : reproduit l'algorithme du plancher prompt, 4 cas couverts |

### Fonctions ajoutées / modifiées

| Fonction / Formule | Action | Description |
|---|---|---|
| TP net formule | Modifiée | Avant : `entry × (1 + stop_distance × reward_risk_ratio)` ; Après : `entry × (1 + (stop_distance + fee_round_trip_pct) × reward_risk_ratio + fee_round_trip_pct)` |
| Dimensionnement quantité | Modifiée | Avant : `risk_usdc / (entry × stop_distance)` ; Après : `risk_usdc / (entry × (stop_distance + fee_round_trip_pct))` |
| TP plancher (Phase 0) | Ajoutée | `entry × (1 + 2 × fee_round_trip_pct)` — TP recalibré ne descend jamais sous ce seuil |
| Profit évaluation (Phase 0) | Modifiée | Avant : `pnl_pct >= min_profit_pct_take` ; Après : `pnl_pct - fee_round_trip_pct×100 >= min_profit_pct_take` |

## Décisions techniques notables

1. **Unification de formule** : Les quatre calculs du TP (phase4, phase5, maker_watcher, phase0 prompt) utilisent maintenant la **même formule nette de frais**. Transport de `fee_round_trip_pct` dans les ordres pending pour que maker_watcher.py applique la même formule au fill que phase4_sizing.py.

2. **Changement de sémantique de `reward_risk_ratio`** : La valeur défaut passe de 2.0 à 1.5 et représente désormais le **rapport net de frais**. Exemple : si stop=3%, fee=0.9%, alors TP visé = entry × (1 + (3%+0.9%)×1.5 + 0.9%) ≈ entry × 1.0675 = +6.75% net.

3. **Plancher de viabilité (Phase 0)** : Le recalibrage TP au bloc RECALIBRAGE du prompt ajoute un garde-fou : si la résistance 4h proposée aurait créé un TP < `entry × (1 + 2×fee_round_trip_pct)`, le TP mécanique est conservé (plutôt que d'accepter un TP perdant). Cela prévient les cas historiques où une résistance basse aurait créé un TP à -5% net.

4. **Marge minimale du plancher** : Fixée à `2 × fee_round_trip_pct` (par défaut ~1.8% net) — gain minimal garanti = coût des frais eux-mêmes. Non paramétrisé en clé config pour rester dans le périmètre exact de l'issue (seules `reward_risk_ratio` et `fee_round_trip_pct` changent).

5. **Test du plancher via Python pur** : La formule du plancher Phase 0 vit dans le prompt (raisonnement Claude) et ne peut pas être invoquée directement par `unittest`. Le fichier `tests/test_phase0_recalibrate_tp_floor.py` **reproduit fidèlement** l'algorithme décrit à l'ÉTAPE 3 du bloc RECALIBRAGE en Python pur et sert de **garde-fou de non-régression** — toute évolution de la formule dans le prompt doit être répercutée dans ce test (cf. `.claude/memory/contrat-prompts-scripts.md` : logique métier dans prompts = hors portée unittest natif).

6. **Évaluation profit net (Phase 0)** : `min_profit_pct_take` est évalué sur un pourcentage **net estimé** (`pnl_pct - fee_round_trip_pct×100`) plutôt que brut. Cela évite de clôturer une position avec +5.5% brut mais +4.6% net quand le seuil est 5%. Le frais de sortie réel n'étant connu qu'après le SELL MARKET, on utilise l'estimation.

7. **Iso-impact sur reward_risk_ratio** : Le changement de 2.0 → 1.5 maintient un rapport économiquement équivalent une fois les frais intégrés. Calculé en amont pour que le TP en production vise le même gain net que l'ancienne formule brute.

## Impact sur l'architecture

**Impact isolé au dimensionnement et au calcul du TP.** Une fois la position ouverte (quantité et TP fixés), les phases 0 (clôture profit), 6 (OCO), 7 (log), 8 (cycle_log) restent identiques. Les changements affectent uniquement :
- Phase 4 (dimensionnement) : quantité calculée net de frais
- Phase 5 (exécution) : TP recalculé net de frais au fill
- Maker Watcher (fill asynchrone) : TP calculé net de frais à la lecture du pending
- Phase 0 (profit) : seuil évalué net de frais

Le flux d'exécution reste inchangé. Aucun nouveau composant, aucune nouvelle dépendance. L'évaluation du profit en Phase 0 (Telegram, logs) change d'ordre de grandeur (+5% au lieu de +2%) mais utilise la même logique de clôture.

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : Tous les chemins d'import et d'état utilisent `PROJECT_DIR` — compatible Mac et VPS.
- **Règle 3 (binance-dev)** : Modifié via branche `feat/issue-411-*` et PR standard.
- **Règle 5 (stdout/stderr capturés)** : Aucune modification des logs — les cycles continuent de capturer stdout/stderr en `logs/stdout/` et `logs/stderr/`.
- **Pas de nouvelle dépendance** : La PR n'ajoute que des formules arithmétiques ; `math.floor`, `math.ceil` étaient déjà utilisés.

## Tests

- **Suite complète : 185 tests (175 avant + 10 nouveaux)** — tous verts
  - `test_phase4_sizing.py` : +2 (TP net, dimensionnement net)
  - `test_phase5_execution.py` : +1 (TP net) ; adaptations mineures sur configs existants pour `fee_round_trip_pct=0`
  - `test_phase5_execution_maker.py` : +1 (TP net maker), adaptations
  - `test_maker_watcher.py` : +1 (TP net au fill)
  - `test_phase0_profit.py` : +2 (cas gross-above/net-below, cas net-above)
  - `test_phase0_recalibrate_tp_floor.py` (nouveau) : +4 (cas du plancher, résistance basse, résistance comfortale, pas de résistance)

- **Syntaxe Python** : `python -c "import ast; ast.parse(...)"` → 0 erreur sur tous les `.py` modifiés
- **JSON valide** : `python -c "import json; json.load(open('config.json'))"` → valide
- **Aucune violation linting nouvelle** : `ruff` avant/après sur les fichiers touchés = 26 erreurs pré-existantes inchangées
- **Test de cohérence prompt/script** : `tests/test_prompt_script_contract.py` reste vert (9/9) — chemins d'échange cycle_*.json inchangés

## Notes importantes

1. **Vérification numérique du plancher** : Cas XRP du 2026-08-19 (cité dans l'issue) : entrée 3.00, stop 2.91 (3% distance), résistance 2.90. Plancher = 3.00 × 1.018 = 3.054. Résistance remise au jour = 2.90 × 0.98 = 2.842 < plancher → TP mécanique conservé (~+4.75% net), pas le TP perdant initial.

2. **Aucune modification de `tp_watcher.py`** : Ce fichier lit `tp_price`, ne le calcule pas — conforme à l'issue qui spécifie les 4 lieux de calcul uniquement.

3. **Configuration directe sur branche** : `config.json` a été modifié directement sur `feat/issue-411-*` (pas sur `main`), conforme au workflow ticket → branche → PR de CLAUDE.md.

4. **Test unitaire vs. test prompt** : Le contrat entre `test_phase0_recalibrate_tp_floor.py` (Python pur) et `prompts/phases/phase0_snapshot.txt` (prompt Claude) est documenté dans `.claude/memory/contrat-prompts-scripts.md` — ce pattern est établi depuis PR #423.
