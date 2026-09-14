# PR #497 — [BUG] Dashboard — chevauchement du libellé de curseur en bord d'échelle

> **Mergée le** : 2026-09-14
> **Branche** : `fix/issue-496-chevauchement-echelle-maker`
> **Issues** : #496

## Contexte

Sur le dashboard du bot, dans les cartes d'ordres maker en attente (#493, #495), le libellé mobile « limite actuelle » affichait le prix courant du curseur de l'ordre sur l'échelle « posé à → annulation ». Quand le curseur se rapprochait d'une extrémité de l'échelle (0 % de concession au départ, ou ~97 % avant annulation), le libellé était recalé en pixels (via `label_x = min(max(...))`) pour ne pas chevaucher les graduations fixes « posé à » et « annulation ». 

Problème : 
1. Ce recalage produisait un libellé qui **affichait une valeur identique à celle déjà visible** sur une des deux graduations.
2. L'ordre qui vient d'être posé (0 % concession = aucun mouvement du bid) affichait deux fois le même prix.
3. Le recalage en pixels n'était pas robuste : la marge en pixels dépendait de la police, de la taille des nombres à l'écran, ce qui rendait le garde-fou fragile.

La PR #496 a décidé de **taire le libellé plutôt que de le recaler** quand le curseur est trop proche d'une extrémité, car le prix affiché serait de toute façon quasi identique à celui de l'extrémité.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `dashboard/viewdata.py` | Modification majeure | Logique de positionnement du libellé — passage de recalage px à décision booléenne |
| `dashboard/templates/dashboard.html` | Modification mineure | Template : affichage conditionnel du libellé |
| `tests/test_dashboard_app.py` | Modification majeure | 3 tests reécrits pour vérifier l'absence/présence du libellé en HTML réel |
| `tests/test_dashboard_viewdata.py` | Modification majeure | 3 tests reécrits pour vérifier la logique de visibilité du libellé |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_maker_scale_geometry()` | Modifiée | Remplace le calcul de `label_x` (recalage) par une décision booléenne `show_current_label` (visibilité) |

### Constantes remplacées

| Ancienne | Nouvelle | Raison |
|---|---|---|
| `MAKER_LABEL_MARGIN = 46` (pixels) | `MAKER_LABEL_HIDE_THRESHOLD = 0.15` (proportion) | Une proportion de l'échelle utile ne dépend ni de la police ni du nombre de chiffres, donc plus robuste |

## Décisions techniques notables

- **Décision booléenne plutôt que recalage** : au lieu de déplacer le libellé en pixels (`min(max(x_current, ...))`), on décide simplement s'il faut l'afficher ou non. Le curseur (`x_current`) reste **toujours** à sa position réelle — seul le libellé disparaît en zone de proximité.

- **Seuil proportionnel (15 %) plutôt qu'en pixels** : 
  - Ancien : `MAKER_LABEL_MARGIN = 46 px` — dépend de la police, des chiffres affichés.
  - Nouveau : `MAKER_LABEL_HIDE_THRESHOLD = 0.15` — proportion de l'échelle utile (692 unités entre `x_initial` et `x_cap`) depuis chaque bord.
  - Justification : les graduations fixes (« posé à », « annulation ») occupent ~50 unités de texte chacune, plus le débord du libellé centré (~45 unités de chaque côté), soit ~95 unités (~14 %). Arrondi à 15 % par marge de sécurité.

- **Zone de visibilité** : `show_current_label = MAKER_LABEL_HIDE_THRESHOLD < ratio < 1 - MAKER_LABEL_HIDE_THRESHOLD`
  - Si `ratio ≤ 15 %` (curseur au départ) → libellé **absent** (prix = prix de pose, déjà visible en fixe)
  - Si `15 % < ratio < 85 %` (zone centrale) → libellé **affiché** et centré sur le curseur
  - Si `ratio ≥ 85 %` (curseur près de l'annulation) → libellé **absent** (prix ≈ prix d'annulation, déjà visible en fixe)

- **Template** : utilise `{% if o.scale.show_current_label %}` pour l'affichage conditionnel (était auparavant une simple substitution de `{{ o.scale.label_x }}`).

## Impact sur l'architecture

Changement isolé au dashboard, pas d'impact sur le reste du bot :
- La fonction `_maker_scale_geometry()` reste intégrée dans `viewdata.py` et ne change pas d'interface publique (elle retourne toujours un dict `scale`)
- Le template est légèrement plus lisible avec la condition explicite
- Les tests sont reécrits pour vérifier directement l'HTML produit, pas une valeur numérique intermédiaire

## Références CLAUDE.md respectées

- Aucune modification de code applicatif du bot (trade_prompt, phases, kraken-cli, etc.)
- Changement isolé au dashboard, conformément au principe de minimalisme (« code minimum qui résout le problème »)
- Tests portent sur le HTML réel produit (`Flask test client`), pas sur des valeurs intermédiaires
