# PR #485 — Supprimer la boucle [REC] automatique

> **Mergée le** : 2026-09-07
> **Branche** : `feat/issue-484-supprimer-boucle-rec-auto`
> **Issues** : #484

## Contexte

La boucle [REC] automatique, introduite en PR #242 et consolidée en PR #231, créait automatiquement des tickets "recommandation" suite à une review tech lead. Cette boucle avait trois inconvénients : (1) elle générais un flot important de tickets secondaires, peu actionnables ; (2) elle fragmentait les décisions développement en petits tickets sans priorité claire ; (3) elle consommait des ressources de CI/CD pour dispatcher et implémenter des recommandations qui demandaient finalement de la supervision humaine de toute façon.

Le ticket #484 décide de supprimer entièrement cette boucle : les recommandations d'amélioration restent dans le commentaire de review tech lead, et c'est à l'humain de décider s'il faut ouvrir un ticket. Les bloquants (vrais bugs) continuent d'être corrigés automatiquement en Phase 1 du post-review.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/claude-post-review.yml` | Suppression du Job 2 | Aucun ticket `[REC]` n'est plus créé automatiquement |
| `.github/workflows/auto-dispatch-on-auto-label.yml` | Retrait de `REC-AUTO` | Seul le label `AUTO` déclenche le dispatch |
| `.github/workflows/binance-dev-auto.yml` | Retrait du mode REC-AUTO | Deux inputs (`target_branch`/`pr_number`) supprimés |
| `.github/workflows/rec-complete-review.yml` | Suppression complète | Workflow mort → plus de déclencheur |
| `docs/workflow-tickets.md` | Mise à jour | Reflète le fonctionnement réel après changement |

### Workflows supprimés / déclencheurs retirés

#### `rec-complete-review.yml` — **Workflow complètement supprimé**

Ce workflow se déclenchait sur la **fermeture** d'une issue `REC-AUTO`. Depuis que `REC-AUTO` ne peut plus être créé, ce workflow ne s'exécute jamais. Suppression pure.

#### Job 2 (`create-rec-tickets`) de `claude-post-review.yml` — **Supprimé**

Ce job lisait la section `💡 Pour aller plus loin` du commentaire de review tech lead, créait automatiquement des tickets `[REC]` avec le label `REC-AUTO`, et les ajoutait au board en `Backlog`.

**Désormais** : le Job 1 (`fix-bloquants`) corrige les 🛑 Bloquants, puis le workflow s'arrête. Les recommandations restent visibles dans le commentaire de review — aucune automatisation.

#### Conditions de déclenchement — **Nettoyage**

- **`auto-dispatch-on-auto-label.yml`** : retrait du pseudo-branchement sur `REC-AUTO` (dont la variable `pr_branch`/`pr_number` qui permettait de repérer la PR associée). Seul le label `AUTO` déclenche ce workflow.
- **`binance-dev-auto.yml`** : retrait des inputs `target_branch` et `pr_number` — aucun appelant (autre que `auto-dispatch-on-auto-label.yml`) ne les utilisait.

## Décisions techniques notables

- **Aucune suppression rétroactive de tickets historiques** : les issues `REC-AUTO` créées en PR #242–#482 restent sur le board avec leur label historique (c'est documenté). Le label GitHub `REC-AUTO` n'est pas supprimé du repo — c'est un artifact du passé, non un trigger actif.

- **Recommandations restent lisibles** : le commentaire de review tech lead inclut toujours une section `💡 Pour aller plus loin` pour les opportunités d'amélioration. C'est à l'utilisateur de lire et de décider d'ouvrir un ticket manuel si utile. Cette décision est plus rapide et ciblée qu'une boucle automatique.

- **Simplification du workflow** : moins de jobs, moins d'état à gérer, moins de risque de race conditions entre "création ticket" et "dispatch workflow" — une décision de design pour la robustesse.

## Impact sur l'architecture

**Impact architectural : nul.** Cette PR modifie uniquement l'orchestration CI/CD, pas le code du bot (`webhook_server.py`, phases, helpers, etc.). Le fonctionnement du bot en production est inchangé. Le flux de développement perd une étape automatique (ticket [REC] → implémentation auto → review), mais le cycle principal (ticket → PR → review → merge → déploiement) est inchangé.

## Références CLAUDE.md respectées

- **Pas de modification du code applicatif** : seules les workflows YAML et la documentation ont changé. `webhook_server.py`, `config.json`, et les modules de phases sont intacts.
- **Workflow CI/CD** : le document n'intervient pas, mais respecte le principe de minimalisme (chaque workflow doit avoir une raison d'être).

## Historique des symboles [REC]

Pour la traçabilité, les PRs qui ont introduit ou modifié la boucle [REC] :

| PR | Titre | Fonction |
|---|---|---|
| #242 | feat: tickets [REC] via REC-AUTO + binance-dev sur branche PR existante | Introduction du système |
| #140 | feat(ci): post-review déclenche binance-dev-auto sur tickets [REC] | Implémentation du déclencheur |
| #231 | [CONSOLIDATION MAJEURE] Refactoring v2 — modularisation + extraction TRADE_PROMPT + agents CI/CD | Consolidation et renforcement |
| **#485** | **[TECH] Supprimer la boucle [REC] automatique** | **Suppression et simplification** |
