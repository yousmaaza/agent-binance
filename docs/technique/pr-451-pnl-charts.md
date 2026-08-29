# PR #451 — Graphe de PnL par jour/mois et grille d'état des cycles

> **Mergée le** : 2026-08-29
> **Branche** : `feat/issue-450-pnl-chart`
> **Issues** : #450

## Contexte

Le dashboard affichait une bande de cadence SVG censée montrer la répartition des cycles (actifs / inactifs / en échec) mais elle était illisible sur les barres fines et les infobulles natives (`<title>` SVG) inexploitables au toucher ou au clavier. Parallèlement, la vue "Résultats" manquait d'une visualisation claire du PnL par période (jour ou mois) — les données brutes existaient (`equity_curve` en Mongo) mais n'étaient pas exploitées.

Cette PR remplace la bande de cadence par deux graphiques plus lisibles et ajoute une grille de diagnostic basée sur le calendrier théorique des créneaux auto, capable de détecter les cycles qui n'ont jamais démarré (lesquels n'écrivent rien en Mongo et restent invisibles à toute requête).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `dashboard/viewdata.py` | Modification | Ajout de 5 nouvelles fonctions pour calcul PnL et grille des cycles ; refactoring de `build_cadence_band()` (reste utilisé par la tuile "cycles ok" et la note de la semaine) |
| `dashboard/app.py` | Modification | Ajout de `_load_grid_cycles()` pour lecture optimisée Mongo; intégration du calcul PnL jour/mois dans `_build_results_view()` |
| `dashboard/mongo_client.py` | Modification | Ajout de `get_cycles_for_grid()` avec projection légère pour limiter la charge Mongo (180 documents sans décisions/explication) |
| `dashboard/settings.py` | Modification | Nouveau paramètre `CYCLE_GRID_DAYS` (défaut : 30 jours) |
| `dashboard/templates/dashboard.html` | Modification | Suppression de la bande de cadence SVG; ajout des deux graphiques PnL (jour/mois) avec toggle; ajout de la grille de cycles avec légende d'état |
| `dashboard/static/css/style.css` | Modification | Suppression de styles `.cadence` (69 lignes); ajout de 68 lignes pour `.pnl`, `.cgrid`, `.legend` et grille CSS |
| `dashboard/static/js/app.js` | Modification | Suppression du code cadence; ajout de 65 lignes pour contrôle PnL (toggle jour/mois, infobulle) et grille (infobulle au survol/focus) |
| `tests/test_dashboard_viewdata.py` | Modification | Ajout de 35 tests (notamment sur `pnl_by_period()`, `pnl_bars()`, `build_cycle_grid()`, cohérence PnL/net_usdc, matching cycles aux créneaux). Suppression de 4 tests devenus sans objet. |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `pnl_by_period()` | Ajoutée | Dérive le PnL net de chaque jour/mois depuis la courbe cumulée `equity_curve`. La somme des périodes reconstitue exactement `net_usdc`. Accepte granularité "day" ou "month". |
| `pnl_bars()` | Ajoutée | Géométrie SVG des barres divergentes autour de zéro : position, hauteur, largeur pour chaque période. Échelle symétrique autour de zéro (pertes et gains équilibrés visuellement). Inclut statistiques : meilleur, pire, total. |
| `build_cycle_grid()` | Ajoutée | Grille théorique des créneaux auto (6 par jour × N jours), chacun rattaché au cycle correspondant en base ou marqué "jamais démarré". Retourne colonnes (jours), comptes par état, stats taux réussite/erreur. |
| `_mark_date_labels()` | Ajoutée | Marque les dates à afficher (tous les 7 jours + premiers de mois) en évitant les collisions (31/07 et 01/08 trop proches). |
| `_match_cycles_to_slots()` | Ajoutée | Associe chaque cycle au créneau théorique le plus proche (tolérance 1 heure). Cycles manuels près d'un créneau sont rattachés au créneau (travail accompli, peu importe le déclencheur). |
| `_grid_cell()` | Ajoutée | Calcule l'état d'une cellule grille (action/idle/error/missing) + infobulle (score, durée, coût API, ordres). |
| `_slot_label()` | Ajoutée | Formate une heure de créneau en heure locale affichable. |
| `build_cadence_band()` | Modifiée | Reste utilisé par `cadence_summary()` (tuile "cycles ok") et `analysis.weekly_note()`. Le SVG de la bande a été retiré du template, mais les données continuent d'alimenter les autres tuiles. |

## Décisions techniques notables

### 1. Grille basée sur le calendrier théorique, pas sur les documents Mongo

Un cycle qui ne démarre pas n'écrit rien en base. Tout compteur parcourant la collection est aveugle à ces lacunes. `build_cycle_grid()` part du calendrier attendu (6 créneaux × N jours en UTC) et cherche le cycle correspondant ; s'il manque, il marque la cellule "missing" — c'est la seule façon de le voir.

**Impact** : sur 30 jours réels de données, 139 créneaux sur 601 n'ont jamais démarré — une statistic qu'aucune agrégation Mongo ne pouvait exprimer.

### 2. Projection Mongo optimisée pour la grille

`_GRID_PROJECTION` en `mongo_client.py` ne relit que 10 champs (`cycle_id`, `timestamp`, `status`, `error_type`, `trigger`, `top_score`, `execution.*`, `duration_s`, `api_cost_usd`). Éviton-nous les `decisions` et `explanation_fr` (qui représentent l'essentiel de la taille du document) — les 180 documents × 30 jours se chargent en < 100 ms au lieu de 2-3 s.

### 3. Barres divergentes avec échelle symétrique

L'ancien graphique `equity_curve_geometry()` était une courbe continue en aire. Pour le PnL par période, des barres divergentes (positives vers le haut, négatives vers le bas) sont plus claires. Crucialmente, l'échelle est symétrique : `max(|min|, |max|)` définit l'extent autour de zéro. Sans cela, une perte de −24 USDC et un gain de +18 auraient les mêmes barres en longueur (visuelle trompeur).

### 4. Infobulles en JavaScript, pas en SVG `<title>`

Les `<title>` SVG natifs sont illisibles sur petits écrans (barres fines) et inaccessibles au clavier (pas de focus). Le JavaScript positionne une infobulle au survol ET au focus clavier, avec `transform: translate(-50%, -100%)` pour centrer au-dessus de la barre. Identique pour la grille (infobulle sur chaque créneau).

### 5. Slots UTC vs affichage en timezone locale

Les créneaux théoriques sont définis en UTC (CLAUDE.md règle 6) : 0h, 4h, 8h, 12h, 16h, 20h UTC. Mais la grille affiche l'heure locale (`display_timezone`). La fonction `_slot_label()` formate l'UTC en local via `to_local(..., fmt="%H:%M")`. Les cellules data portent `slot_local` (affichage) et `cycle_id` (donnée).

### 6. Tolérance de matching 1 heure

Un cycle lancé manuellement 30min après son créneau théorique devrait compter pour ce créneau (le travail a été fait). `_match_cycles_to_slots()` accepte ±1h de dérive (`SLOT_TOLERANCE_S = 3600`). Au-delà, le cycle est laissé orphelin (ne compte pour aucun créneau) et le créneau reste "missing".

### 7. Espacement intelligente des libellés de date

La grille couvre 30 jours = 30 colonnes. Afficher tous les jours crée du bruit. `_mark_date_labels()` affiche un repère tous les 7 jours ET à chaque début de mois, mais jamais deux collés (31/07 et 01/08 sont à 2 colonnes ; leurs libellés se chevauchent → condition `i - last >= 3` (3 colonnes min) empêche l'affichage du premier (#450)).

### 8. Test de cohérence PnL = net_usdc

Un test clé : `test_pnl_by_period_sums_to_net_usdc()` vérifie que la somme des PnL jour === `financials.global.net_usdc` pour chaque granularité (jour ET mois). Testé sur les données réelles : tous les trois côtés (brut, frais, net) se reconstitunt exactement. **C'est l'insurance que le graphe raconte la bonne histoire.**

## Impact sur l'architecture

Changement isolé au dashboard web (`dashboard/`) — aucun impact sur le bot principal (`binance-bot/`), les phases de cycle, ou la structure Mongo. Les données existent déjà (`equity_curve`, les cycles avec `duration_s` et `api_cost_usd`) ; cette PR les expose mieux.

- Aucune nouvelle API ou endpoint côté bot.
- Aucune modification de schéma Mongo (champs seulement lus, pas créés).
- Performance : requête Mongo allégée pour la grille (100 vs 2000 ms par rafraîchissement).

## Références CLAUDE.md respectées

- **Règle 6 (UTC interne / local à l'affichage)** : slots théoriques en UTC, affichage en `display_timezone` de l'utilisateur. Format `%Y-%m-%d %H:%M` (secondes inutiles pour la granularité 4h).
- **Minimalisme** : projection Mongo optimisée pour ne lire que l'essentiel ; suppression de code mort (bande cadence) ; chaque ligne répond au ticket #450.
- **Pas de secret** : tout paramétrable via `CYCLE_GRID_DAYS` en settings.
