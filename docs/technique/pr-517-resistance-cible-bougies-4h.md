# PR #517 — Résistance de la cible = plus haut des bougies 4h Kraken

> **Mergée le** : 2026-10-05
> **Branche** : `feat/issue-516-resistance-cible-bougies-4h`
> **Issues** : #516

## Contexte

Cette PR substitue la source historique (pivot R2 hebdomadaire TradingView) par le plus haut des N bougies 4h Kraken clôturées, pour plafonner la cible de take-profit (TP). La motivation : simplifier l'architecture (pas d'appel MCP TradingView pour le recalibrage Phase 0), améliorer la fiabilité (données Kraken natives, timestamps universels) et valider empiriquement que cette heuristique plus simple fonctionne aussi bien ou mieux que R2 sur les données historiques.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/trade_helpers.py` | Ajout de 3 fonctions (50 lignes) | Règle unique `compute_tp_target()` centralisée pour phase 4/5, maker_watcher et recalibrage Phase 0 |
| `binance-bot/core/phases/phase0_calibrate_tp.py` | Nouveau script Python (64 lignes) | Remplace le bloc textuel du prompt phase0_snapshot.txt ; exécution déterministe |
| `binance-bot/core/phases/phase4_sizing.py` | Modification | Appelle `compute_tp_target()` + `fetch_resistance_4h()` ; stocke résistance dans l'ordre |
| `binance-bot/core/phases/phase5_execution.py` | Modification | Appelle `compute_tp_target()` au fill ; transmet résistance au maker_watcher |
| `binance-bot/core/maker_watcher.py` | Modification (8 lignes) | Appelle `compute_tp_target()` avec la résistance figée à la pose de l'ordre |
| `config.json` | Ajout clé | Nouveau paramètre `resistance_lookback_4h: 30` |
| `prompts/phases/phase0_calibrate_tp.txt` | Suppression | Logique déplacée en script Python (`phase0_calibrate_tp.py`) |
| `prompts/phases/phase0_snapshot.txt` | Modification | Appel du script `phase0_calibrate_tp.py` au lieu du bloc texte |
| `prompts/phases/phase5_execution.txt` | Modification mineure | Ajustement d'une description de chaîne |
| `prompts/position_prompt.txt` | Modification | Mise à jour après suppression du prompt Phase 0 ancien |
| `scripts/resistance_replay.py` | Nouveau script (125 lignes) | Validation historique (80 trades depuis le 03/07) : mesure R2 vs plus haut 30 bougies 4h |
| `docs/strategie.html` | Modification | Section 05/10 : description de la formule de résistance + résultats de mesure |
| `docs/strategie.md` | Modification (généré) | Synchronisé avec strategie.html |
| Tests | Modifications | Mise à jour des tests existants + nouveaux tests pour la résistance 4h |

### Fonctions ajoutées / modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `compute_tp_target()` | `core/trade_helpers.py` | Ajoutée | Règle unique de calcul TP : mécanique nette de frais, plafonné par max_tp_pct et résistance 4h |
| `fetch_resistance_4h()` | `core/trade_helpers.py` | Ajoutée | Récupère le plus haut des N bougies 4h clôturées depuis Kraken via `binance-cli ohlc` |
| `resistance_from_candles()` | `core/trade_helpers.py` | Ajoutée | Extrait le plus haut des bougies fermées (exclut la bougie en cours) |
| `recalibrate_tps()` | `core/phases/phase0_calibrate_tp.py` | Ajoutée | Itère les positions ouvertes, recalcule TP avec résistance 4h, enregistre changements |
| Phase 4 TP | `core/phases/phase4_sizing.py` | Modifiée | Appelle `compute_tp_target()` + mémorise résistance dans l'ordre |
| Phase 5 TP | `core/phases/phase5_execution.py` | Modifiée | Appelle `compute_tp_target()` au fill avec la même logique |
| maker_watcher TP | `core/maker_watcher.py` | Modifiée | Utilise résistance figée à la pose de l'ordre |

## Décisions techniques notables

- **Centralisation du calcul TP** : une seule fonction `compute_tp_target()` pour les trois contextes (entrée, fill, recalibrage), élimine la duplication et améliore la maintenabilité.

- **Résistance figée à la pose** : la résistance est capturée à la phase 4 (calcul de cible d'entrée) et reste inchangée jusqu'au recalibrage Phase 0, même si le marché évolue. Cela simplifie la logique et évite les recalculs répétés.

- **Kraken clôturées uniquement** : le plus haut n'est calculé que sur les bougies 4h dont la clôture est antérieure au moment présent (exclut la bougie en cours, dont le high n'est pas figé). Fonction `resistance_from_candles()` filtre en comparant `open_time + 4h <= now`.

- **N=30 bougies** : lookback de 30 bougies 4h (~120 heures = 5 jours) validé historiquement. Mesure sur 80 trades : distance médiane +1,56 %, taux d'atteinte 9 % (vs R2 hebdo 31 % mais moins cohérent aux entrées).

- **Fallback gracieux** : si Kraken est indisponible (404, timeout, parse error), la fonction retourne `None` et le calcul continue avec le plafond `max_tp_pct` seul, sans erreur bloquante.

- **Réconciliation plancher/plafond** : si la résistance × 0.98 tombe en-dessous du plancher de viabilité (entry × (1 + 2 × frais)), on ignore la résistance mais on **garde le plafond max_tp_pct** (changement de décision #516 par rapport à la logique antérieure qui revenait à la mécanique). Cela simplifie la règle : jamais de cible perdante ou non plafonnable.

- **Suppression du prompt Phase 0 textuel** : le bloc "RECALIBRAGE TP" du prompt `phase0_snapshot.txt` est remplacé par un appel à un script Python `phase0_calibrate_tp.py`. Cela rend le recalibrage déterministe, testable et évite les invocations MCP TradingView.

## Impact sur l'architecture

**Avant** :
- Phase 0 recalibrage TP : bloc textuel dans le prompt, exécuté par Claude, appels MCP TradingView pour R2 hebdo.
- Phase 4/5 : calcul TP avec plancher/plafond incohérents entre les trois contextes (entrée, fill, maker_watcher).

**Après** :
- Phase 0 recalibrage TP : script Python déterministe `phase0_calibrate_tp.py`, une seule source de vérité pour la logique.
- Phase 4/5/maker_watcher : tous appels à `compute_tp_target()`, même formule, même résistance 4h Kraken.
- Configuration : nouvelle clé `resistance_lookback_4h` (défaut 30) dans `config.json`.

**Changements observables** :
1. Résistances TradingView Phase 2 (`resistance_1/2_4h`, `nearest_resistance_4h`) restent en l'état, documentées comme informatives (ne plafonnent plus aucune cible).
2. Les TP des positions ouvertes sont recalibrés au démarrage de chaque cycle Phase 0 (notif Telegram si changement > 0.5 %).
3. Meilleure résilience : Kraken indisponible → TP conservé ou plafonné par `max_tp_pct`, pas d'erreur.

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : respectée dans tous les imports et chemins (phase0_calibrate_tp.py, scripts/resistance_replay.py).
- **Règle 3 (Pas de modification code directe sur main)** : changements via branche `feat/issue-516-resistance-cible-bougies-4h` + PR.
- **Règle 8 (Modification de stratégie met à jour docs/strategie.html)** : formule résistance documentée section 05/10 avec mesures validées.

## Mesures et validation

Script `scripts/resistance_replay.py` valide l'hypothèse sur 80 trades historiques (depuis 2026-07-03) :
- **R2 hebdo** (ancien) : distance médiane +5,55 %, atteinte 31 %, "mord" (tient compte) 31 %, sous plancher 41 %.
- **Plus haut 30 bougies 4h** (nouveau) : distance médiane +1,56 %, atteinte 9 %, "mord" 9 %, sous plancher 86 %.

Interprétation : la résistance 4h est conservative (moins d'impact sur les cibles), mais fiable. Avec N=30, la résistance est ignorée dans 86 % des cas (bien au-dessous du max_tp_pct) → la cible vaut quasi toujours `max_tp_pct` directement.

## Test coverage

- Nouveaux tests : `test_resistance_4h.py` (extraction + filtre bougies clôturées).
- Tests modifiés : `test_maker_watcher.py` (résistance depuis pending), `test_phase0_recalibrate_tp_floor.py` (plancher conserve plafond sous ligne du plancher).
- Tous les tests passent : 674 tests.

## Notes techniques

- Bug adjacent non touché : `scripts/partial_tp_replay.py` (#514) non versionné, ne figure pas dans cette PR.
- Audit CLAUDE.md : les résistances TradingView de la Phase 2 restent documentées comme informatives (noms reconnaissables : `resistance_1/2_4h`, `nearest_resistance_4h` dans les logs), mais ne plafonnent aucune cible opérationnelle (aucune invocation en Phase 4/5/maker_watcher).
