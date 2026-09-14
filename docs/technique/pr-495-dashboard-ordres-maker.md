# PR #495 — Dashboard : montrer où les ordres maker d'achat sont posés

> **Mergée le** : 2026-09-14
> **Branche** : `feat/issue-493-ordres-maker-dashboard`
> **Issues** : #493

## Contexte

Le dashboard affichait des stats synthétiques du watcher maker (total de remplissages, taux de succès) mais restait silencieux sur les ordres en attente : où est-ce qu'une limite d'achat est posée en ce moment ? De combien a-t-elle déjà chassé le marché ? À quel point de son plafond d'annulation est-elle ?

Cette PR ajoute une section visuelle (cartes SVG par ordre, avec jauges de budget) pour rendre cette information compréhensible au premier coup d'œil — surtout le cas critique où un ordre approche de son annulation programmée.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `dashboard/viewdata.py` | Ajout de 3 fonctions + constantes | Nouvelle couche présentation pour les ordres maker |
| `dashboard/app.py` | Modification route `/` | Intègre les ordres maker dans le contexte de rendu |
| `dashboard/templates/dashboard.html` | Ajout bloc HTML (51 lignes) | Rendu des cartes ordres + état vide expliqué |
| `dashboard/static/css/style.css` | Ajout styles CSS (25 lignes) | Échelle SVG, jauges, pastilles de statut, typographie maker |
| `binance-bot/core/phases/phase7_mongo.py` | Modification liste config (2 lignes) | Expose `maker_max_concession_pct` et `maker_timeout_seconds` au dashboard |
| `tests/test_dashboard_app.py` | Ajout classe TestMakerOrdersCards (116 lignes) | Vérifie le rendu HTML réel des cartes |
| `tests/test_dashboard_viewdata.py` | Ajout tests build_maker_* (127 lignes) | Couvre les trois nouvelles fonctions en pur cas |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `build_maker_orders(pending_orders, config, tz_name, now=None)` | Ajoutée | Calcule pour chaque ordre : prix courant, cap annulation, budgets consommés (concession %, temps %),  barres CSS, state "en_chasse" / "bientôt_annulé", géométrie SVG échelle |
| `build_maker_last_fill(open_positions, closed_trades, now=None)` | Ajoutée | Retrouve la dernière position ou trade entré en maker, pour expliquer l'état vide : "aucun ordre" c'est normal si on a rempli il y a 2h |
| `_maker_bar_tone(pct)` | Ajoutée | Retourne la classe CSS de la jauge selon le % consommé (< 80 % = neutral, ≥ 80 % = warn, ≥ 100 % = crit) |
| `_maker_scale_geometry(initial_price, current_price, cap_price)` | Ajoutée | Calcule les positions x SVG pour l'échelle posé → annulation, avec recalage du libellé pour rester lisible |
| `_build_results_view()` | Modifiée | Appelle les deux nouvelles fonctions viewdata, enrichit `maker` dict avec `orders` et `last_fill` |

## Décisions techniques notables

- **Plafond d'annulation non stocké** : `initial_limit_price × (1 + maker_max_concession_pct)`. Calculé côté vue parce qu'il ne change jamais (connaître le prix d'origine suffit). Tire la valeur de `config.json` qui arrive via `dashboard_state`, avec repli sur les constantes par défaut si les clés manquent (cas ancien `dashboard_state` publié avant cette PR).

- **Jauges CSS plutôt que SVG** : une `<div>` contenant une barre de progression, plus facile à lire au survol et plus accessible que des graphiques SVG complexes. Les deux jauges (concession et temps) utilisent les mêmes seuils (80 %) pour que la pastille de statut soit cohérente avec les jauges.

- **Échelle SVG avec recalage du label** : l'ordre peut être posé à 1 USDC avec un plafond à 1000 USDC ; le libellé du prix courant ne doit pas chevaucher les graduations fixes ("posé à" et "annulation"). Solution : le curseur reste à sa vraie position, seul le texte du prix bouge si nécessaire (`label_x` recalculé). C'est justement le cas le plus important à lire (ordre proche d'un bord) qui bénéficie le plus du recalage.

- **État vide informatif** : au lieu de dire "aucun ordre" (anormal), on dit "aucun ordre d'achat en vol" + le dernier remplissage connu. Cela rappelle que c'est l'état normal la plupart du temps, pas une panne.

- **SVG en `currentColor`** : utilise le token CSS `--ink` au lieu de couleur en dur, compatible thème clair/sombre. Les jauges utilisent les tokens `--gain` (marge restante), `--wait` (seuil d'alerte), `--loss` (seuil critique).

## Impact sur l'architecture

Changement isolé au dashboard, aucun impact sur les phases de trading ou la persistance MongoDB. Le watcher maker continue à fonctionner pareil. La couche présentation reçoit simplement une nouvelle section pour visualiser ce qui était déjà capturé (liste `pending_orders` du watcher).

Phase 7 expose maintenant deux clés config jusqu'ici absentes de la liste publiée, malgré leur usage dans le watcher (`.maker_max_concession_pct`, `.maker_timeout_seconds`). Le repli sur defaults en CSS garantit qu'un ancien `dashboard_state` sans ces clés affiche quand même quelque chose de sensé.

## Références CLAUDE.md respectées

- **Pas de dépendances externes** : les calculs restent en maths pures (Python + CSS + SVG), aucun appel externe nouveau.
- **Architecture polling-only inchangée** : toutes les données proviennent du `dashboard_state` (snapshot Mongo), le dashboard reste en lecture seule.
- **Heure locale en affichage** : `placed_at` convertie via `to_local()`, tous les horodatages utilisant le même helper que le reste du dashboard.
- **Typage implicite** : les fonctions acceptent `list` et `dict`, cohérent avec le reste de viewdata.py ; les tests vérifient le comportement plutôt que les signatures.
