# PR #46 — [REC] Ajouter prompt_version dans le fallback Mongo erreur

> **Mergée le** : 2026-05-22
> **Branche** : `feat/issue-26-prompt-version-fallback-mongo-erreur`
> **Issues** : #26

## Contexte

La PR #22 avait introduit `PROMPT_VERSION` (hash SHA-1 8 chars du template) et l'injectait dans chaque document Mongo via la Phase 7 — écrite par le sous-processus Claude en fin de cycle nominal. En revanche, le bloc fallback de `run_trade_workflow()` qui s'exécute côté `webhook_server.py` lorsque le sous-processus Claude échoue (exit code ≠ 0) n'incluait pas ce champ. Résultat : les cycles terminés en erreur ne permettaient pas de filtrer par version de prompt, rendant impossible l'isolation des régressions introduites par un changement de template.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification (+1 ligne) | Le document Mongo d'un cycle en erreur contient désormais `prompt_version`, rendant les erreurs filtrables par version de template |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `run_trade_workflow()` | Modifiée | Ajout de `"prompt_version": PROMPT_VERSION` dans le `$set` du bloc fallback Mongo (ligne :1007) qui s'exécute uniquement lorsque `exit_code != 0` |

## Décisions techniques notables

- **Réutilisation directe de la constante module `PROMPT_VERSION`** : la variable est calculée une fois au boot (SHA-1 du template brut, 8 chars hex) et est accessible globalement dans `run_trade_workflow()` sans paramètre supplémentaire — changement minimal d'une seule ligne.
- **Pas de modification du bloc succès** : le bloc Phase 7 (écrit par le sous-processus Claude) n'est pas touché. Seul le chemin d'erreur, géré par `webhook_server.py` lui-même, est impacté.
- **`upsert=True` conservé** : si le cycle a échoué avant d'écrire quoi que ce soit en Mongo (Phase 7 jamais atteinte), l'`upsert` crée le document ; si Phase 7 a partiellement écrit avant l'erreur, le `$set` complète sans écraser.

## Impact sur l'architecture

Changement isolé dans le chemin d'erreur de `run_trade_workflow()`. L'uniformité du schéma Mongo est améliorée : tous les documents `cycles`, qu'ils soient en `status: "success"` ou `status: "error"`, contiennent désormais le champ `prompt_version`. Cela permet des requêtes de diagnostic cohérentes du type `db.cycles.find({"prompt_version": "abc12345"})` sans avoir à traiter les deux cas séparément.

## Références CLAUDE.md respectées

- **Règle 2 (pas de secret hardcodé)** : `PROMPT_VERSION` est calculé depuis le contenu du template, pas depuis une clé externe — conforme.
- **Règle 4 (stdout/stderr toujours capturés)** : le fallback Mongo est déclenché après la capture des logs, pas à la place.
