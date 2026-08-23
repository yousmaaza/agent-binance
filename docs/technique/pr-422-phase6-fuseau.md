# PR #422 — [BUG] phase6_next_cycle.py duplique fmt_local et next_4h_slot

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-421-phase6-fuseau`
> **Issues** : #421, #395 (régression déjà corrigée mais pas appliquée ici)

## Contexte

`phase6_next_cycle.py` (script exécuté en Phase 6) réimplémentait son propre calcul du prochain slot 4h UTC et son propre formatage de l'heure locale via `.astimezone()` sans argument. Cela le maintenait en dehors du correctif #395 qui a externalisé ces deux fonctionnalités vers `core/timing.py` avec support explicite du fuseau configuré (`display_timezone` via `config.json`).

**Manifestation du bug** : sur la VPS Hostinger (fuseau machine = `Etc/UTC`), `.astimezone()` sans argument retourne l'heure UTC inchangée, affichant l'heure en UTC sous le libellé trompeur "heure locale". Exemple constaté le 23/08/2026 07:34 : le slot 08:05 UTC s'affichait `08:05 (heure locale)` au lieu de `10:05 (heure locale)` en décalage horaire d'été Paris (+02:00).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase6_next_cycle.py` | Refactoring minimaliste | Élimination de la duplication ; le script est passé de 26 lignes à 15 lignes |
| `tests/test_phase6_next_cycle.py` | Mise à jour des tests | Adaptation pour patcher `core.timing.datetime` ; ajout d'une classe de base `_DisplayTimezoneTestCase` ; test de régression |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| (contenu de `phase6_next_cycle.py`) | Refactorisé | Remplace le calcul manuel du slot par un appel centralisé `next_4h_slot()` (depuis `core.timing`) ; remplace `.astimezone().strftime()` par `fmt_local()` |

## Décisions techniques notables

- **Centralisation vs duplication** : même si `phase6_next_cycle.py` est un script isolé exécuté par le sous-processus Claude, il est chargé dans `sys.path` et peut importer depuis `binance-bot/core/` sans problème. Le gain de maintenabilité (une seule source de vérité pour le slot et le formatage) outrepasse la complexité minimale d'un calcul local dupliqué.

- **Patchage des tests** : le test gelait précédemment l'heure en patchant le module stdlib `datetime` global. Après la fix, l'heure doit être gelée au niveau du module `core.timing` (où `next_4h_slot()` et `fmt_local()` résident). Patcher `datetime.datetime` global ne suffit plus — il faut patcher `core.timing.datetime` pour affecter les appels internes au module.

- **Fixation du fuseau configuré** : une classe de base `_DisplayTimezoneTestCase` fixe `APP_CONFIG["display_timezone"] = "Europe/Paris"` au démarrage et la restaure à la fin, garantissant que les tests restent indépendants du fuseau de la machine (VPS en UTC, Mac en America/Los_Angeles, etc.).

- **Test de régression ajouté** : `TestNextSlotUsesConfiguredTimezoneNotMachineTimezone::test_output_is_paris_offset_not_raw_utc` valide explicitement que le slot 08:05 UTC s'affiche `10:05 (heure locale)` en été Paris (UTC+2), et non `08:05` (raw UTC).

## Impact sur l'architecture

Changement isolé, sans impact sur l'architecture globale. La sortie contractuelle de Phase 6 (stdout + fichier JSON) reste identique. Les autres phases ne communiquent jamais directement avec `phase6_next_cycle.py` — elles consomment sa sortie via `phase6_8.txt` (script orchestrateur qui parse le JSON).

## Références CLAUDE.md respectées

- **Minimalisme** (§Réfléchir avant de coder) : refactoring chirurgical, une seule responsabilité éliminée (duplication), zéro fonctionnalité ajoutée.

- **Modifications chirurgicales** (§Modifications chirurgicales) : seul le fichier touché par le bug est modifié ; les tests sont ajustés de manière minimale pour s'adapter au changement.

- **Convention horaire interne/affichage** (§Convention horaire) : précise que `next_4h_slot()` travaille en UTC interne, seul l'affichage via `fmt_local()` utilise le fuseau configuré — ce correctif le réaffirme en centralisant la logique.

- **Pas de secret hardcodé** (§Aucun secret hardcodé) : aucun nouveau secret introduit.

- **Python 3.11 + venv** (§Python via venv) : tous les appels Python utilisent le venv local 3.11.

## Validation

- **5 tests unitaires** dans `tests/test_phase6_next_cycle.py` : 4 existants adaptés + 1 nouveau test de régression. Tous passent avec la VPS simulée en UTC.
- **Syntaxe Python** : vérifiée via `python -c "import ast; ast.parse(open(...).read())"`.
- **Suite complète** : 166 tests, tous verts (`python -m unittest discover -s tests -p "test_*.py"`).
- **Redémarrage VPS** : à faire par l'utilisateur ; la commande `/status` doit répondre en < 5s et afficher l'heure locale correcte (10:05 et non 08:05 si fuseau Paris).
