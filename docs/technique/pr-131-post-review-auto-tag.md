# PR #131 — Post-review auto-tag tech-lead-review + In progress

> **Mergée le** : 2026-05-28
> **Branche** : `feat/post-review-auto-tag`
> **Issues** : Aucune issue parent — amélioration du CI/workflow

## Contexte

Amélioration du workflow de review technique (`claude-post-review.yml`). Après que le tech-lead-reviewer termine une review, le workflow créait automatiquement des tickets GitHub pour les recommandations, mais :
- Le label `tech-lead-review` était appliqué sans vérifier son existence au préalable
- Les tickets recommandations étaient créés avec un status "Backlog" au lieu de "In progress"

Cette PR ajoute un step d'idempotence pour créer le label s'il n'existe pas et autorise le ticket-manager à configurer le status initial comme "In progress".

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/claude-post-review.yml` | Création | Nouveau workflow complet d'automatisation post-review |

### Composants ajoutés / modifiés

#### Workflow `claude-post-review.yml`

Le workflow était inexistant auparavant — il a été créé de zéro avec deux jobs parallèles.

**Job 1 — fix-bloquants** :
- Déclenché après succès du workflow `Claude Tech Lead Review`
- Checkout de la branche PR
- Fetch du commentaire review contenant la section `### 🛑 Bloquants`
- Si bloquants détectés : invoque Claude CLI pour corriger chaque bloquant identifié sur la branche PR
- Commit et push des corrections sur la branche
- Poste un commentaire récap sur la PR

**Job 2 — create-recommendation-tickets** (nouveau comportement) :
- **Nouveau step** : `Ensure tech-lead-review label exists` (lignes 154–164)
  - Crée le label `tech-lead-review` avec couleur `0075ca` et description explicite
  - Idempotent : `... 2>/dev/null || true` (ne bloque pas s'il existe déjà)
  - Préalable indispensable avant d'assigner des tickets
- Fetch du commentaire review (identique au job 1)
- Invoque l'agent `ticket-manager` pour convertir les recommandations en issues
- Les tickets reçoivent les labels `enhancement` + `tech-lead-review` (ligne 202)
- Les tickets sont ajoutés au board #4 avec **status "In progress"** (ligne 200), non "Backlog"
- Poste un commentaire récap

## Décisions techniques notables

1. **Label séparé avant usage** : le step "Ensure tech-lead-review label exists" s'exécute avant l'agent ticket-manager, garantissant que le label existe. GitHub retourne `success` même si le label préexiste (grâce au `|| true`).

2. **Status board "In progress" au lieu de "Backlog"** : les recommandations qui ont passé la barre d'une review tech lead sont dignes d'être traitées immédiatement, pas remisées au backlog. Cela signale priorité et provenance claire (review, pas backlog organique).

3. **Workflow lancé après review** : le workflow `claude-post-review.yml` s'active automatiquement après que `Claude Tech Lead Review` complète (`workflow_run.types: [completed]`), sans intervention utilisateur. Les deux jobs s'exécutent en parallèle (pas de dépendance déclarée).

4. **Secrets et PAT** :
   - Job 1 : `secrets.GITHUB_TOKEN` standard (déjà disponible)
   - Job 2 : `secrets.GH_PAT` avec scope `project` pour la création de tickets et l'ajout au board — le PAT est préféré à `GITHUB_TOKEN` car `GITHUB_TOKEN` n'a pas accès aux projects GitHub

## Impact sur l'architecture

Aucun impact architectural sur le code applicatif (`scripts/webhook_server.py`, état persistant). C'est un changement **pur CI/CD** :

- **Avant** : review tech lead → notifications → action manuelle utilisateur pour créer les tickets (ou oubli)
- **Après** : review tech lead → workflow automatique → bloquants corrigés et recommandations tickétisées → board mis à jour

L'intégration CLI (agents `binance-dev`, `ticket-manager`) reste identique ; seul le déclenchement est externalisé.

## Références CLAUDE.md respectées

N/A — ce fichier est CI/CD (workflows), pas code applicatif. Les contraintes CLAUDE.md s'appliquent uniquement à `scripts/webhook_server.py`, `config.json`, et le shell scripting du daemon.
