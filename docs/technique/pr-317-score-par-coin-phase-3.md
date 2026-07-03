# PR #317 — Afficher le score par coin dans le rapport Phase 3

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-314-phase3-scores-par-coin`
> **Issues** : #314

## Contexte

Améliorer la visibilité du processus de scoring Phase 3 en enrichissant la notification Telegram avec le détail par coin (score /10, décision BUY/HOLD/SKIP/SELL, et raisons de la décision). Cela aide l'utilisateur à comprendre pourquoi un coin a été sélectionné ou rejeté à chaque cycle.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase3_scoring.py` | Modification | Enrichissement du rapport et ajout du champ `scores_detail` en output JSON |
| `prompts/phases/phase3_scoring.txt` | Modification | Mise à jour de la documentation du flux avec le nouveau champ et le heartbeat résumé |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `phase3_scoring.py` (script) | Modifiée | Génère maintenant un message Telegram détaillé par coin avec score, décision, et raisons. Ajoute le champ `scores_detail` à l'output JSON. |

## Décisions techniques notables

- **Champ `scores_detail`** : nouvelle clé de l'output JSON Phase 3, coexistant avec `skip_coins_detail`. Chaque entrée contient `{score, decision, skip_type, reasons}`.
- **Structure parallèle de décision** : le champ `decision` dans `scores_detail` capture la classification pour chaque coin (BUY/HOLD/SKIP/SELL), indépendant de `skip_type` qui reste un détail technique du filtrage.
- **Message Telegram détaillé** : chaque coin du rapport Phase 3 affiche sa ligne individuellement (score, décision, raisons), tronquée à 4000 chars pour respecter la limite API.
- **Raisons enrichies** : même pour les coins rejetés, les raisons incluent les signaux négatifs (e.g., "RSI 75 hors zone", "1D SELL") pour aider au diagnostic.
- **Heartbeat résumé** : le prompt Phase 3 demande un résumé des scores (max 300 chars) pour le heartbeat `hb(3)`, permettant une synthèse rapide lors de la relecture des logs.

## Impact sur l'architecture

Changement **isolé sur Phase 3**. Le champ `scores_detail` enrichit l'output JSON sans affecter les phases suivantes (Phase 4, 5, 7) qui lisent seulement `buy_candidates` et `skip_coins_detail`. La notification Telegram est améliorée côté affichage, mais le workflow d'exécution reste inchangé.

## Références CLAUDE.md respectées

- **Règle 1 — Minimalisme** : modification chirurgicale limitée à Phase 3, aucune refactorisation du code adjacent.
- **Règle 2 — Modifications chirurgicales** : seul le scoring et le formatage du rapport sont affectés.
- **Règle 6 — Convention horaire** : les logs et heartbeats conservent UTC interne, l'affichage Telegram reste en heure locale.
- **Règle 4 — Appels Telegram via curl** : la fonction `tg()` utilisée pour les notifications reste en place, inchangée.
