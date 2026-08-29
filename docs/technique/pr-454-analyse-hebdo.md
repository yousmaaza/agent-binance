# PR #454 — [M1] Analyse hebdomadaire rédigée par Claude dans le dashboard

> **Mergée le** : 2026-08-29
> **Branche** : `feat/issue-453-analyse-hebdo`
> **Issues** : #453

## Contexte

L'analyse hebdomadaire du dashboard (section « Note de la semaine ») affichait un résumé statique fourni par la fonction `analysis.weekly_note()`. Cette PR substitue un texte généré par Claude avec un garde-fou numérique strict : chaque chiffre du texte doit être retrouvé dans la charge utile transmise (tel quel ou dérivé par une opération simple — somme, pourcentage, différence). Si le contrôle échoue ou l'appel Claude tombe en erreur, le dashboard retombe automatiquement sur le texte déterministe sans révéler la défaillance à l'utilisateur.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/weekly_analysis.py` | Ajouté (416 lignes) | Nouvelle logique de génération hebdomadaire |
| `binance-bot/core/timing.py` | Modification | Ajout `next_weekly_slot()` et `iso_week_key()` pour la programmation |
| `binance-bot/config/llm.py` | Modification | Ajout flags CLI Claude et timeout pour l'analyse |
| `binance-bot/storage/mongo.py` | Modification | Ajout méthodes `find_cycles_since()`, `find_weekly_analysis()`, `save_weekly_analysis()` |
| `binance-bot/webhook_server.py` | Modification | Intégration du scheduler hebdomadaire dans `main_loop()` |
| `dashboard/mongo_client.py` | Modification | Ajout `get_latest_weekly_analysis()` avec cache |
| `dashboard/viewdata.py` | Modification | Ajout `build_weekly_analysis_view()` pour formater l'affichage |
| `dashboard/app.py` | Modification | Passage de l'analyse au contexte template |
| `dashboard/templates/dashboard.html` | Modification | Affichage de l'analyse rédigée + indicateur fallback |
| `tests/test_weekly_analysis.py` | Ajouté (351 lignes) | Suite de tests pour le contrôle numérique et l'idempotence |
| `tests/test_timing.py` | Modification | Ajout tests `next_weekly_slot()` et `iso_week_key()` |
| `tests/test_dashboard_*.py` | Modification | Tests des vues dashboard avec l'analyse |

### Fonctions ajoutées / modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `run_weekly_analysis()` | `core/weekly_analysis.py` | Ajoutée | Point d'entrée appelé par `main_loop()`, ne lève jamais (isolée de l'orchestration) |
| `next_weekly_slot()` | `core/timing.py` | Ajoutée | Calcule le prochain lundi 00:10 UTC (5 min après le cycle 00:05) |
| `iso_week_key()` | `core/timing.py` | Ajoutée | Génère la clé d'idempotence (ex: `2026-W35`) |
| `_verify_numbers()` | `core/weekly_analysis.py` | Ajoutée | Garde-fou central : valide que tous les nombres du texte sont retrouvés dans les données |
| `_call_claude()` | `core/weekly_analysis.py` | Ajoutée | Appel Claude CLI avec `--output-format json`, gestion timeout + erreurs |
| `_select_window()` | `core/weekly_analysis.py` | Ajoutée | Sélectionne 7 jours si ≥10 trades, sinon 30 jours avec flag `window_widened` |
| `_aggregate()` | `core/weekly_analysis.py` | Ajoutée | Agrégats PnL brut/net/frais et compteurs |
| `_significance()` | `core/weekly_analysis.py` | Ajoutée | Verdict statistique (IC95% sur la moyenne par trade) |
| `_cycles_summary()` | `core/weekly_analysis.py` | Ajoutée | Résumé des cycles : total, avec ordre, erreurs |
| `find_weekly_analysis()` | `storage/mongo.py` | Ajoutée | Récupère le document d'une semaine ISO |
| `save_weekly_analysis()` | `storage/mongo.py` | Ajoutée | Sauvegarde idempotente via upsert sur `_id = week_key` |
| `find_cycles_since()` | `storage/mongo.py` | Ajoutée | Retourne cycles dont le timestamp est ≥ depuis |
| `get_latest_weekly_analysis()` | `dashboard/mongo_client.py` | Ajoutée | Récupère l'analyse la plus récente avec cache |
| `build_weekly_analysis_view()` | `dashboard/viewdata.py` | Ajoutée | Formate l'analyse pour le template (fallback explicit) |

## Décisions techniques notables

- **Garde-fou numérique strict** : Le contrôle `_verify_numbers()` extrait tous les nombres du texte Claude et valide chacun contre la charge utile. Un nombre « inventé » ou dérivé par une opération non autorisée fait échouer la génération. Cela prévient l'hallucination de chiffres (ex. une performance fictive) sans bloquer les résumés honnêtes (somme de trades, pourcentage de gains, etc.).

- **Fenêtre adaptative** : Sous 10 trades en 7 jours, la fenêtre s'élargit à 30 jours avec un flag `window_widened` clairement indiqué. Cela évite les analyses sur un échantillon trop petit tout en gardant la transparence (le lecteur sait qu'une fenêtre large a été utilisée).

- **Idempotence par semaine ISO** : Une seule génération par semaine ISO (ex: `2026-W35`), via la clé `_id` du document Mongo et un test d'existence au démarrage. Cela prévient les multiples appels Claude le même lundi.

- **Isolation du cycle de trading** : La fonction `run_weekly_analysis()` n'est jamais appelée avec `await` ni directement dans le workflow de trading. Elle boucle indépendamment dans `main_loop()`, et tout échec (quota, timeout, contrôle numérique) est capturé localement. Une défaillance de l'analyse ne remonte jamais au cycle de trading.

- **Contexte de la semaine précédente** : Pour éviter que le texte répète les mêmes constats plusieurs semaines de suite (fenêtre large), on transmet l'agrégat de la semaine précédente. Claude peut alors écrire « il n'y a rien de nouveau » plutôt que de fabriquer un récit sur des données inchangées.

- **Modèle Sonnet 4.6 + JSON output** : L'analyse utilise Sonnet (pas Opus) et `--output-format json` au lieu de `stream-json`. Pas d'appels tool use (les données sont déjà dans le prompt), donc moins de latence et coût stable capturé en un seul objet JSON.

## Impact sur l'architecture

- **Ajout d'une boucle scheduler hebdomadaire** : `main_loop()` enchâsse maintenant deux schedulers (4h pour les trades, 1 semaine pour l'analyse) qui tournent en parallèle sans se gêner.

- **Nouvelle collection MongoDB** : `db.weekly_analysis` avec documents indexés par semaine ISO (`_id = "2026-W35"`).

- **Dashboard enrichi** : La section « Note de la semaine » affiche désormais l'analyse rédigée (si disponible) ou un fallback explicitement marqué, avec la fenêtre utilisée (7 ou 30 jours) et la date de génération.

- **État persistant** : La clé d'idempotence (semaine ISO) est générée depuis `iso_week_key()` et stockée dans Mongo. Zéro état volatil.

Changement isolé au periphérique dashboard, pas d'impact sur l'orchestration des phases de trading ou la logique de cycles.

## Références CLAUDE.md respectées

- **Règle 1 (venv + profil)** : Tout appel Python du bot utilise le venv `.venv/` et Python 3.11 (récupéré via les flags CLI et le subprocess enviroment).
- **Règle 2 (PROJECT_DIR dynamique)** : `PROJECT_DIR` est calculé via `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` dans le module, pas hardcodé.
- **Règle 3 (branche + PR)** : La PR a suivi le workflow : issue #453 → branche `feat/issue-453-analyse-hebdo` → création PR mergée.
- **Règle 5 (isolation des erreurs Claude)** : La fonction `run_weekly_analysis()` attrape toute exception et la logue localement — aucune remontée au webhook_server.
- **Règle 6 (UTC interne)** : Tous les timestamps et calculs de fenêtres utilisent UTC. Le formatage pour l'affichage est géré par le dashboard via `to_local()`.
- **Règle 7 (scheduler dans main_loop)** : L'auto-scheduler hebdomadaire vit dans la même boucle de polling que le scheduler 4h, pas dans cron ou systemd.

## Coût et performance

- Appel Claude une fois par semaine (vs toutes les 4h pour le trading).
- Timeout strict de 120s pour l'analyse (pas de retry, repli déterministe).
- Coût enregistré dans Mongo pour tracking (`cost_usd` du document).

## Tests

Suite complète en `tests/test_weekly_analysis.py` (351 lignes) :
- ✅ Contrôle numérique : nombre inventé rejeté, nombre dérivé (somme/pourcentage) accepté
- ✅ Idempotence : deuxième appel dans la même semaine ISO n'appelle pas Claude
- ✅ Élargissement de fenêtre : 7j → 30j si < 10 trades, flag porté jusqu'au document
- ✅ Repli sur erreur : aucun document écrit si Claude échoue ou contrôle échoue
- ✅ Pas de génération sans trade ni cycle sur la fenêtre

Tous les tests passent, ainsi que les vérifications statiques (`ruff`, `mypy`).
