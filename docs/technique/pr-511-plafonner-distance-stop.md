# PR #511 — [STRAT] Plafonner la distance de stop pour écarter les coins ultra-volatils

> **Mergée le** : 2026-09-28
> **Branche** : `feat/issue-508-cible-realiste`
> **Issues** : #508

## Contexte

La PR #510 (PR #507) avait introduit un garde-fou sur la **cible TP** (`max_realistic_move_pct`), visant à rejeter les ordres dimensionnés sur un stop trop large pour que le marché puisse livrer un TP mécanique réaliste. 

Cependant, l'analyse rétrospective sur 110 trades réels révèle que ce filtre bloquerait **97.3 % des trades** — autrement dit, il arrêterait le bot. La cible dérive mécaniquement du stop via la formule `cible = (stop_distance + fee) × reward_risk_ratio + fee`, donc aucune largeur de stop n'offre un ratio net ≥ 1.0 compatible avec une cible ≤ 3 % quand les frais arrondis font 0.9 %. Ce constat reste valide et n'a pas changé.

**Nouvelle approche (cette PR)** : plutôt que de filtrer sur la **cible**, filtrer directement sur la **distance du stop** qui l'induit. Un stop au-delà d'un seuil signale une volatilité extrême (coins comme TRUMP 22-23/08/2026, ATR 4h > 4.8 %) qui ne mérite pas une position, indépendamment de la cible mécanique.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase4_sizing.py` | Modification | Ajout de la variable `max_stop_distance_pct` et du check détection volatilité extrême avant calcul prix_stop/prix_tp |
| `config.json` | Modification | Nouvelle clé `max_stop_distance_pct: 0.12` (plafond 12 % sur la distance du stop) |
| `tests/test_phase4_sizing.py` | Modification | 3 nouvelles classes de test validant le plafond |
| `docs/strategie.html` | Modification | Section "28 septembre" documentant la démonstration d'impasse, le nouveau plafond, le tableau de choix du seuil ; correction de l'affirmation périmée sur la hausse médiane |
| `docs/strategie.md` | Modification | Régénéré via `scripts/strategie_to_md.py` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `phase4_sizing.py` (bloc principal) | Modifiée | Après calcul de `stop_distance_pct = atr_pct × atr_stop_multiplier`, check si > `max_stop_distance_pct` ; si oui, skip en TYPE_B avec reason détaillée (stop calculé, plafond, ATR 4h) ; continue avant calcul prix_stop/prix_tp |

## Décisions techniques notables

- **Placement du check** : immédiatement après le calcul de `stop_distance_pct` et **avant** les calculs prix_stop/prix_tp. Cela écarte le coin sans gaspiller de calculs si c'est un cas extrême.
- **skip_type = TYPE_B** : le coin n'a pas passé le filtre de dimensionnement valide (montant, coûts, limites marché) — classification cohérente avec les autres cas TYPE_B (montant < seuil, prix_stop négatif).
- **reason chiffrée** : la raison inclut le stop calculé, le plafond et l'ATR 4h qui les explique. Exemple : `"Stop 15.0% > plafond 12.0% (volatilité extrême, ATR 4h 5.0%)"`. Cela permet au debug et au dashboard d'analyser précisément pourquoi un coin a été rejeté.
- **Défaut 0.12 (12 %)** : mesuré sur la courbe coût/bénéfice de 110 trades réels : le blocage chute de 30.9 % à 10.9 % entre 10 % et 12 %, puis stagne. Cible ainsi la vraie queue volatile sans perte d'opportunité normale.
- **Retraits** : la clé `max_realistic_move_pct`, le garde-fou sur la cible et ses 4 tests dédiés ont été supprimés (aucune mention restante à chercher).
- **Mesure MFE** : correction de la documentation technique (SPEC.md) : la hausse médiane offerte par le marché pendant la détention (MFE, Maximum Favorable Excursion) mesurée sur 19 trades (bougies Kraken 30 jours, cycles de #508) s'élève à **+1.52 %** (pas 4.9 %), confirmant que les cibles mécaniques et larges sont inatteignables.

## Impact sur l'architecture

Changement isolé au sein de la Phase 4 (sizing). Aucun impact sur :
- Les phases 0, 1, 2, 3 (analyse, scoring)
- Les phases 5, 6, 7, 8 (exécution, reporting)
- La boucle principale ou le scheduler
- Les handlers de commande

**Impact attendu sur les cycles** : réduction des trades bloqués en TYPE_B au seuil mesuré (~10.9 % des trades historiques), soit ~11 trades / 110 passés sous ce filtre. Avant ce plafond : aucun filtre explicite sur la distance du stop, donc tous les trades la traversaient (aucun reject basé sur cette métrique).

## Références CLAUDE.md respectées

- **Règle 2** (`PROJECT_DIR` dynamique) : les chemins utilisés dans phase4_sizing.py via `PROJECT_DIR` et `sys.path.insert(0)` sont inchangés.
- **Règle 8** (modification stratégie → mise à jour docs/strategie.html) : la section "28 septembre" a été réécrite pour documenter la nouvelle approche et mesures ; `docs/strategie.md` régénéré via `scripts/strategie_to_md.py --check` (valide).
- **Règle 3** (modifications via agent binance-dev + branche) : cette PR a suivi le workflow ticket → branche → PR → merge.
- **Règle 5** (stdout/stderr sauvegardés) : aucune modification de la capture de logs ; cycle_log.jsonl continue à enregistrer skip_type et skip_detail.
