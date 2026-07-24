# PR #369 — [M1] Refactorer Phase 5 (exécution) en script Python déterministe

> **Mergée le** : 2026-07-24
> **Branche** : `feat/issue-364-refactor-phase5-script-deterministe`
> **Issues** : #364

## Contexte

La Phase 5 (exécution des ordres) était jusqu'à présent écrite intégralement en bash exécuté par Claude dans le prompt `prompts/phases/phase5_execution.txt`, rendant impossible le testing déterministe et fragilisant la chaîne d'exécution du bot. Ce refactor déplace toute la logique d'exécution vers `binance-bot/core/phases/phase5_execution.py` (script Python pur), permettant :

- **Testing unitaire** de la Phase 5 indépendamment de Claude
- **Déterminisme** : exécution reproductible
- **Maintenabilité** : code Python lisible et instrumentable
- **Isolation des erreurs** : un coin en erreur n'interrompt pas les autres

La Phase 5 débloque les Tickets 2 et 4 du plan de testing (`docs/superpowers/specs/2026-07-24-tests-integration-design.md`).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase5_execution.py` | Réécriture majeure (+163 lignes, -45) | Implémente la logique complète d'exécution (était partiellement en bash, désormais 100% Python) |
| `prompts/phases/phase5_execution.txt` | Refactorisation (-40 lignes) | Devient un orchestrateur : construit le JSON d'input, appelle le script, consomme l'output |

### Fonctions ajoutées / modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| Entrée du script | `phase5_execution.py:main` | Créée | Lit l'input JSON depuis `/tmp/cycle_{CYCLE_ID}_phase5_input.json` et déclenche la boucle d'exécution |
| Boucle d'ordres | `phase5_execution.py:55–216` | Créée | Traite chaque ordre préparé par la Phase 4 (tri par score décroissant) |
| Re-fetch prix + drift check | `phase5_execution.py:65–72` | Créée | Appelle `binance("ticker", ...)`, vérifie le drift < `price_deviation_max_pct`, skip TYPE_C si dépassement |
| Vérification solde USDC | `phase5_execution.py:74–80` | Créée | Re-fetch le solde, skip TYPE_C si insuffisant |
| BUY MARKET + query du fill | `phase5_execution.py:82–98` | Créée | Lance l'ordre marché, poll 3 tentatives (1s d'intervalle), skip TYPE_C si non rempli |
| Clôture immédiate si TP dépassé | `phase5_execution.py:111–158` | Créée | Détecte si le prix post-fill ≥ TP cible, ferme à marché, écrit trade en `trade_history.json` avec `close_reason="market_above_tp_at_fill"` |
| Pose du stop-loss | `phase5_execution.py:167–215` | Créée | Calcule `actual_qty_sl` arrondi aux `lot_decimals`, pose l'ordre SL, flag `protection_failed` si échec |
| Écriture output JSON | `phase5_execution.py:227–234` | Créée | Génère `/tmp/cycle_{CYCLE_ID}_phase5_output.json` avec `executed`, `skipped`, `orders_executed`, `orders_skipped_detail` |

## Décisions techniques notables

- **Gestion des erreurs granulaire** : un `try/except` par ordre (ligne 217–220) capture toute exception non prévue (ex. timeout réseau) et classe l'ordre en skip TYPE_C — préserve le comportement séquentiel du prompt bash (un coin skip n'arrête pas les autres).

- **Format JSON canonique** : l'input et l'output utilisent le même schéma que Phase 4 output / Phase 6 input, garantissant la composabilité avec les autres phases.

- **Re-fetch systématique prix et solde** : bien que coûteux en latence, reconfirme l'état du marché juste avant l'exécution (déjà en place dans le prompt bash, maintenu ici).

- **Atomic writes** : `_save_trade_history_atomic()` (depuis `trade_helpers.py`) utilisé pour chaque trade, garantissant la cohérence du fichier état même en cas de crash ou concurrence (bien que rare en mono-thread).

- **Aucun changement de seuil ni de formule** : les valeurs `price_deviation_max_pct`, `reward_risk_ratio`, calculs TP/SL restent strictement identiques à avant refactor — c'est une **pure réécriture applicative**, pas un changement de logique métier.

## Impact sur l'architecture

**Architecture globale** :
- La Phase 5 passe d'exécutant bash (via Claude) à orchestrateur (Claude construit l'input JSON et appelle le script) — pattern identique à Phase 3/4 déjà refactorisées.
- Le prompt `phase5_execution.txt` redevient lisible : 40 lignes de doc + orchestration, au lieu de 80 lignes de logique bash implicite.

**Flux d'exécution** :
```
[Phase 4 output] → phase5_execution.txt (orchestration)
                 → python3 phase5_execution.py (exécution)
                 → [Phase 5 output JSON]
                 → Phase 6 input
```

**Testabilité** : la Phase 5 peut désormais être testée indépendamment de Claude via :
- Des fichiers JSON d'input factices
- Un harness de test mock Kraken (`fake_kraken.py`, Ticket 2)
- Des tests d'intégration (Ticket 4)

**Compatibilité** : sortie JSON compatible en aval (Phase 6/7/8) — aucun changement visible pour les consumers du output.

## Références CLAUDE.md respectées

- **Règle 2 : `PROJECT_DIR` dynamique** (ligne 32) : `PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))` — fonctionne sur Mac et VPS Linux sans modification.

- **Règle 3 : Aucun secret hardcodé** — tous les paramètres (seuils, limites) chargés depuis `config.json` via `_load_config()` (ligne 44).

- **Règle 4 : Pas de `urllib` pour Telegram** — notifications déléguées à la fonction `tg()` (fournie par `trade_helpers.py`), qui shell out vers `curl` (ligne 153, 181, 206, 225).

- **Règle 5 : Logs stdout/stderr persistés** — le script écrit en stdout (ligne 236 : `PHASE5_DONE|...`), capture garantie par `run_trade_workflow()` → `logs/stdout/cycle_{id}.log` et `logs/stderr/cycle_{id}.log`.

- **Règle 6 : Convention horaire UTC interne** — tous les timestamps en UTC (ligne 129, 186), formatage local à la présentation Telegram uniquement.

- **Venv Python 3.11** — script exécutable via `.venv/bin/python3` sur dev et prod (CLAUDE.md §1).

## Notes annexes

**Incohérence résiduelle (hors scope)** : Le prompt `prompts/phases/phase4_sizing.txt` contient encore la logique complète en pseudo-code bash alors que `phase4_sizing.py` l'implémente déjà — cette divergence prompt/script pré-existe et concerne la Phase 4, pas la Phase 5. À traiter dans une PR ultérieure.

**Validations recommandées avant merge en prod** :
1. Test local : `/trade` depuis Telegram sur le Mac
2. Test VPS : redémarrage du service, `/status` réactif en < 5s
3. Test de cycle réel : un ou deux ordres BUY réels (ou sur `kraken paper`) pour valider le remplissage du fill et la pose du SL
