# PR #361 — [BUG] phase8_cycle_log.py ne commit jamais state/trade_history.json

> **Mergée le** : 2026-07-20
> **Branche** : `feat/issue-360-phase8-cycle-log-py-ne-commit-jamais`
> **Issues** : #360

## Contexte

Le script de commit/push automatique généré par `phase8_cycle_log.py` (Phase 8 du cycle de trading) ne stageait que `state/cycle_log.jsonl`, laissant `state/trade_history.json` en dehors du versionning Git dès qu'aucun autre mécanisme n'était responsable de son staging. Cela a causé un drift silencieux entre la source de vérité locale (`state/trade_history.json`) et le repository depuis le 8 juillet, détecté et corrigé manuellement le 20 juillet via le commit `c29f625`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase8_cycle_log.py` | Création + correction | Nouveau module Phase 8 qui génère le script bash d'auto-commit/push en end-of-cycle, avec ajout explicite de `state/trade_history.json` |

### Fonctions ajoutées / modifiées

| Fonction/Bloc | Action | Description |
|---|---|---|
| `phase8_cycle_log.py` (module entier) | Création | Module autonome qui : (1) lit les variables Phase 8 depuis `/tmp/cycle_{CYCLE_ID}_phase8_input.json` ; (2) écrit une ligne JSON dans `state/cycle_log.jsonl` (max 90 entrées) ; (3) génère un script bash qui stage les deux fichiers d'état critiques (`cycle_log.jsonl` + `trade_history.json`) puis commit/push |
| `cl_script` (variable, ligne 60–69) | Ajout | Bloc qui construit le script bash. **Clé** : ligne 66 ajoute `"git add state/trade_history.json\n"` en plus de la ligne 65 qui ajoute `cycle_log.jsonl` |

## Décisions techniques notables

- **Séparation en module** : Le code de fin de cycle (Phase 8) a été extrait en module autonome `phase8_cycle_log.py`, isolant la logique de persistance Git des autres phases. Cela favorise la testabilité et la clarté.
- **Staging explicite des deux fichiers** : Au lieu de compter sur un state de staging antérieur (fragile), le script bash stage les deux fichiers explicitement en une seule étape. Élimine les dépendances cachées.
- **Écriture atomique du script** : Le script bash est généré en `/tmp/` et rendu exécutable avant invocation, évitant les races sur la cohérence du contenu.
- **Gestion d'erreur basique** : Try/except sur la lecture JSON et l'invocation du script ; notifications Telegram en cas de problème, sans bloquer le cycle.

## Impact sur l'architecture

Le changement est chirurgical, limité à la Phase 8. Aucun impact sur les phases 0–7 ou sur les handlers de commandes Telegram. L'ajout de `state/trade_history.json` dans l'auto-commit garantit simplement que le fichier ne diverge jamais du repository, renforçant la fiabilité du système de persistance d'état.

Ce module représe aussi la **naissance de l'architecture modulaire par phase** — avant, tout vivait dans `webhook_server.py` ou dans le texte du prompt. Avec `phase8_cycle_log.py`, chaque phase peut potentiellement avoir son propre fichier, facilitant les futures extractions (phases 0–7 à suivre).

## Références CLAUDE.md respectées

- **Règle 5 (stdout/stderr)** : Le stdout du sous-processus Claude est sauvegardé dans `logs/stdout/cycle_{cycle_id}.log` indépendamment du succès/échec du script bash (capture toujours active).
- **Règle 2 (PROJECT_DIR dynamique)** : `PROJECT_DIR` est reconstruit depuis le chemin du fichier, garantissant portabilité Mac → VPS.
- **Règle 3 (Aucun secret hardcodé)** : Le script bash ne contient que des chemins, pas de tokens ou credentials.
- **Règle 7 (Auto-scheduler)** : La boucle `main_loop()` déclenche le cycle, qui inclut Phase 8 ; aucune invocation cron/systemd.
- **Pas de force-push ni de git reset** : Le script utilise `git pull --rebase --autostash` pour réconcilier les changements éventuels du remote, puis `git push`, garantissant la sécurité du workflow multi-machine.

