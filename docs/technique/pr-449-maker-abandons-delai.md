# PR #449 — /maker — afficher les abandons et corriger la précision du délai

> **Mergée le** : 2026-08-29
> **Branche** : `feat/issue-430-maker-abandons`
> **Issues** : #430

## Contexte

La commande `/maker` affichait un manque de visibilité sur les ordres abandonnés (ordres maker qui ont expiré sans remplissage ni fallback) et présentait une imprécision dans l'affichage du délai médian de remplissage (arrondi à la minute alors que la stratégie a besoin de précision à la seconde pour régler les paramètres `maker_max_concession_pct` et `maker_timeout_seconds`).

Cette PR ajoute :
1. Compteur `total_abandoned` dans le bloc de santé du watcher
2. Nouveau funnel watcher avec répartition fills/fallbacks/abandoned
3. Précision à la seconde pour le délai médian (ex : "110s" au lieu de "1min")
4. Tendance 7j du taux de remplissage avec garde-fou sur l'effectif minimal

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/commands/maker.py` | Modification | Ajout de deux nouvelles fonctions, refactoring de trois handlers d'affichage, affichage du funnel watcher et abandon counter |
| `tests/test_maker_command.py` | Modification | Ajout de 10 nouveaux tests couvrant les critères d'acceptation (#430) et les scénarios de dégradation |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_fmt_seconds_precise()` | Ajoutée | Formate un flottant de secondes en chaîne "Ns", jamais tronqué à la minute. Dédié aux métriques de délai (différent de `_fmt_duration()` utilisé pour l'âge des ordres). |
| `_format_health_section()` | Modifiée | Signature : accepte désormais `state: dict \| None` en paramètre (chargement mutualisé en amont dans `run_maker()`). Affiche `total_abandoned` dans le cumul. |
| `_format_watcher_funnel()` | Ajoutée | Calcule et formate les 3 issues du funnel watcher (remplis/replis marché/abandonnés) à partir de `state`. Population distincte de `trade_history` : ces compteurs se réinitialisent si le fichier d'état est perdu/corrompu, contrairement à l'historique des trades. Label explicite pour éviter la confusion. |
| `_format_efficiency_section()` | Modifiée | Signature : accepte `state: dict \| None` en paramètre. Utilise `_fmt_seconds_precise()` pour le délai médian. Ajoute une tendance 7j avec message de garde-fou si effectif < 5 trades classés. Appelle `_format_watcher_funnel()` en fin de bloc. |
| `run_maker()` | Modifiée | Charge l'état une fois (`_load_json(_WATCHER_STATE_PATH, None)`) et le passe à `_format_health_section()` et `_format_efficiency_section()` pour éviter les chargements redondants. |

## Décisions techniques notables

- **Deux métriques de délai distinctes** : `_fmt_duration()` reste inchangé (affichage du temps écoulé des ordres en attente, arrondi à la minute), `_fmt_seconds_precise()` nouveau (délai médian de remplissage, précision à la seconde). Justification : la stratégie a besoin de précision pour régler les paramètres de timeout, mais l'affichage du temps écoulé peut rester grossier.

- **Funnel watcher isolé de trade_history** : les trois compteurs (fills/fallbacks/abandoned) partagent un même dénominateur (`total_attempts`) et ne doivent jamais être mélangés avec le taux de remplissage issu de l'historique. Ces compteurs se réinitialisent si le fichier d'état est perdu/corrompu (cf. `core/maker_watcher.py::_write_watcher_state`), contrairement à `trade_history` qui est immuable. Le label "remis à zéro si l'état est perdu" le rappelle explicitement.

- **Garde-fou sur la tendance 7j** : la tendance n'est calculée que si l'échantillon 7j atteint au moins 5 trades classés (`_MIN_TREND_SAMPLE = 5`). En dessous, un message honnête ("échantillon insuffisant") est affiché plutôt qu'un pourcentage trompeur. Seuil justifié par le volume actuel du bot (5 fills au total sur la période de test du ticket).

- **Chargement mutualisé de l'état** : `run_maker()` charge une fois `_WATCHER_STATE_PATH` et le passe aux fonctions au lieu que chacune le recharge. Évite les I/O redondants et simplifie le testage des états dégradés.

## Impact sur l'architecture

Changement isolé à la commande `/maker` — aucun impact sur l'architecture globale.
- La commande reste une lecture seule de l'état persistant.
- Aucune nouvelle dépendance ajoutée.
- `maker_watcher_state.json` n'est jamais modifié par cette commande (cf. commentaire en tête du fichier `commands/maker.py`).

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : la fonction `_load_config()` utilise le chemin dynamique depuis `core.env`.
- **Minimalisme** : zéro code spéculatif, chaque ligne répond à un critère d'acceptation du ticket #430.
- **Conventions de nom et format** : tous les textes affichés en français, noms de fonctions en snake_case, fonction-helpers regroupées par bloc.
