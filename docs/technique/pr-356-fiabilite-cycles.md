# PR #356 — Fiabilité cycles — autostash push + détection quota stdout

> **Mergée le** : 2026-07-05
> **Branche** : `feat/issue-354-355-cycle-reliability`
> **Issues** : #354, #355

## Contexte

Deux bugs mineurs de fiabilité dans la phase 8 (cycle log) et le post-processing des cycles :
1. **#354** : `git pull --rebase` échouait silencieusement parce que `state/trade_history.json` est constamment modifié par le bot en live. Le commit cycle log était créé localement mais jamais poussé vers GitHub.
2. **#355** : Détection de quota incomplet. Le message "You've hit your session limit" apparaît dans **stdout** du sous-processus Claude, pas dans stderr. La détection n'utilisait que stderr, d'où les cycles quota mal classifiés en MongoDB.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase8_cycle_log.py` | Modification mineure | Ajout `--autostash` à `git pull --rebase` pour résoudre les conflits locaux automatiquement |
| `binance-bot/orchestration/runner.py` | Modification mineure | Augmentation de la détection de quota : vérification de stdout en plus de stderr |

### Fonctions ajoutées / modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| _(script bash)_ | phase8_cycle_log.py | Modifiée | Ligne 67 : ajout du flag `--autostash` à la commande `git pull --rebase` |
| `_handle_trade_post_run()` | runner.py | Modifiée | Ligne 195 : ajout de `is_resource_error(stdout_path)` dans la condition de détection de quota |

## Décisions techniques notables

- **`--autostash` dans git rebase** : Ce flag esthère automatiquement les changements locaux non committés avant le rebase, puis les réapplique après. Évite les conflits silencieux quand `state/trade_history.json` diverge entre le remote et le local. La notification Telegram `⚠️ cycle_log push échoué` sera maintenant évitée dans la majorité des cycles.

- **Réutilisation de `is_resource_error()`** : La fonction `is_resource_error(stdout_path)` était déjà importée de `orchestration.stream_parser` (ligne 17) et utilisée pour les notifications au début du post-run (ligne 181). L'extension à la ligne 195 réutilise la même logique plutôt que d'invoquer une autre pile de détection, maintenant la cohérence du code.

- **Orden des vérifications** : La nouvelle condition `is_resource_error(stdout_path) or any(k in stderr_content for k in quota_keywords)` cherche d'abord stdout (détection spécialisée) avant stderr (mots-clés génériques). Cet ordre garanti une détection robuste des deux cas.

## Impact sur l'architecture

Changements isolés, pas d'impact architectural. La PR corrige deux bugs localisés sans modifier le flux de cycle ou introduire de nouveaux composants. Les deux modifications ont zéro dépendances croisées.

## Références CLAUDE.md respectées

- **Modifications chirurgicales** : Deux fichiers touchés, une seule ligne modifiée par fichier. Aucun refactoring ni "améliorations" collatérales.

- **Minimalisme** : Chaque fix est minimal (1 flag ajouté, 1 fonction réutilisée). Pas de code spéculatif.

- **Stdout/stderr obligatoires** : Les logs cycle sont sauvegardés intégralement (stdout et stderr de chaque cycle). Phase 8 les pousse via git push — cela permet le debugging post-mortem.

- **Pas de dépendances lourdes** : Aucune nouvelle dépendance ; les modifications utilisent les outils existants (git, stream_parser.is_resource_error).

## Notes de test

- **Cas #354** : Le prochain cycle auto doit montrer `cycle_log.jsonl` pushé sans notification `⚠️ cycle_log push échoué`. Vérifiable dans le fichier `state/daemon.log` et sur GitHub (commits `chore: cycle log YYYYMMDD_HHMMSS` visibles régulièrement).

- **Cas #355** : Si un cycle se déclenche avec quota épuisé et message "You've hit your session limit" dans stdout, MongoDB doit enregistrer `error_type: "quota"` au lieu de `"crash"`. Vérifiable via MongoDB Atlas : `db.cycles.findOne({error_type: "quota"})` doit retrouver les cycles quota récents.

- **Pas de régression** : La modification du post-run est purement additive (ajout d'une condition supplémentaire). Les cycles normaux continuent d'être classifiés correctement.
