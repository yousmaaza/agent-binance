# PR #242 — Tickets [REC] via REC-AUTO + binance-dev sur branche PR existante

> **Mergée le** : 2026-06-22
> **Branche** : `feat/fix-rec-auto-workflow`
> **Issues** : N/A (feat CI/CD)

## Contexte

Le workflow CI/CD d'auto-implémentation des recommandations tech lead était incomplet :
- Le job `claude-post-review` créait des issues mais n'associait pas la branche source de la PR
- Le workflow `binance-dev-auto` pouvait uniquement créer une nouvelle branche depuis `main`, pas travailler sur une PR existante
- Les recommandations [REC] étaient créées mais orphelines — pas d'association avec la PR qui les a générées

Cette PR établit un flux complet : **tech-lead-review → création issue [REC] → implémentation sur branche existante → fermeture issue**. Trois workflows sont révisés pour coordonner ce flux.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/claude-post-review.yml` | Modification | Job 2 `create-rec-tickets` détecte les 3 types de recommandations et crée des issues avec métadonnées de lien vers la PR |
| `.github/workflows/auto-dispatch-on-auto-label.yml` | Modification | Détecte label `REC-AUTO` en plus de `AUTO`, extrait `target_branch` et `pr_number` du body de l'issue, les passe à `binance-dev-auto` |
| `.github/workflows/binance-dev-auto.yml` | Modification | Accepte inputs optionnels `target_branch` et `pr_number`, implémente en mode REC-AUTO sur branche existante, ferme l'issue après commit |

### Fonctionnalités ajoutées

#### 1. Job `create-rec-tickets` : détection multiformat des recommandations

**`claude-post-review.yml:152–222`**
- Cherche les sections `### ⚠️ Points d'attention`, `### ⚠️ À simplifier / à clarifier`, `### 💡 Pour aller plus loin`
- Crée une issue [REC] pour chaque recommandation avec :
  - Label `REC-AUTO` (déclenche `auto-dispatch-on-auto-label`)
  - Body incluant les balises HTML commentées `<!-- pr_branch: {branch} -->` et `<!-- pr_number: {pr_number} -->`
  - Ajout automatique au project board "Binance Bot Agent" (#4)
- Poste un commentaire récap sur la PR d'origine

#### 2. Extraction des métadonnées REC-AUTO

**`auto-dispatch-on-auto-label.yml:104–126`** (bloc Python nouveau)
- Déclenche sur `REC-AUTO` (en plus de `AUTO`)
- Extrait via regex du body de l'issue :
  - `target_branch` : branche où implémenter (ex. `feat/issue-240-xxx`)
  - `pr_number` : numéro de la PR source (ex. `240`)
- Exporte ces valeurs pour le workflow `binance-dev-auto`

#### 3. Mode REC-AUTO dans binance-dev-auto

**`binance-dev-auto.yml:14–21, 39, 101–107`**
- Inputs optionnels : `target_branch` (chaîne) et `pr_number` (chaîne)
- Checkout sur `target_branch` si fournie (sinon `main` par défaut)
- Prompt distingue deux cas :
  - **REC-AUTO** (`target_branch != ''`) : implémente sur la branche existante, ne crée pas de nouvelle PR, ferme l'issue après commit avec commentaire
  - **AUTO** (`target_branch == ''`) : comportement classique — crée une branche `feat/issue-<N>-<slug>` et une PR
- Vérification d'état : skip si issue déjà fermée (sécurité anti-doublon, ligne 69–71)

## Décisions techniques notables

- **Métadonnées HTML commentées** (plutôt que labels/projects) : les labels et projects API sont limités en volume ; les commentaires HTML dans le body sont évolutifs et ne polluent pas la lisibilité du texte pour les humains.
- **Extraction regex stricte** : `<!-- pr_branch: (.+?) -->` ne capture que le contenu jusqu'au premier `-->`, prévenant les faux positifs.
- **Distinction REC-AUTO vs AUTO par présence de `target_branch`** : plutôt qu'un label supplémentaire, on utilise la présence/absence de l'input pour switcher le comportement — plus simple et moins de variable d'état.
- **Fermeture issue en REC-AUTO** : après implémentation, l'issue [REC] est fermée automatiquement par l'agent avec un commentaire de trace. L'issue ne reste jamais orpheline — elle crée un trail du travail effectué.

## Impact sur l'architecture

**Impact CI/CD majeur** :
- **Avant** : recommandations créaient des issues flottantes (label REC, mais sans lien vers la PR source ni branche cible)
- **Après** : recommandations sont intégrées au workflow PR existant — implémentées sur la même branche, associées au numéro de PR, fermées automatiquement après communi

Le workflow de tech lead est renforcé :
```
PR ouverte
  ↓
Tech lead review (claude-post-review job 1 : fix bloquants)
  ↓
Recommandations détectées (claude-post-review job 2 : create-rec-tickets)
  ↓ crée issues [REC] avec pr_branch + pr_number
Dispatch auto-dispatch-on-auto-label sur REC-AUTO
  ↓ extrait target_branch du body
Implémente via binance-dev-auto en mode REC-AUTO
  ↓ commits sur branche existante
Ferme issue [REC]
```

Pas d'impact sur le flux d'exécution de trading (`webhook_server.py`, TRADE_PROMPT, phases 0–8) — changement purement CI/CD.

## Références CLAUDE.md respectées

- **Règle 3 (modifications via agent binance-dev)** : cette PR refactor les workflows CI/CD qui déclenchent `binance-dev` et `binance-dev-auto`, respectant le contrat que seul cet agent implémente les tickets.
- **Minimalisme** : chaque changement est chirurgical — ajout de 39 lignes en `auto-dispatch`, 40 lignes en `binance-dev-auto`, 57 lignes en `claude-post-review` (total 136 +, 91 -). Aucune refonte gratuite.
- **Gestion d'erreur** : les échecs de GraphQL ou d'extraction regex sont loggés ; si une métadonnée est manquante, le workflow dégénère gracieusement (fallback à branche `main`).

## Notes de debug

### Quand une recommandation n'est pas détectée

1. Vérifier le heading exact : `### ⚠️ Points d'attention` (pas `### Points d'attention` ou `##Points`).
2. Vérifier qu'il y a du contenu après le heading (pas une section vide).
3. Lire le commentaire du revieweur pour confirmer la casse du heading.

### Quand REC-AUTO extrait mal les métadonnées

1. Vérifier les balises HTML : `<!-- pr_branch: feat/... -->` et `<!-- pr_number: 240 -->` (pas d'espaces gênants autour des `-->`).
2. Tester la regex manuellement :
   ```bash
   echo "<!-- pr_branch: feat/test -->" | grep -oP '(?<=pr_branch: )[^ ]+'
   ```

### Quand une issue REC-AUTO n'est pas implémentée

1. Vérifier que le label `REC-AUTO` est bien assigné (sinon `auto-dispatch-on-auto-label` ne déclenche pas).
2. Vérifier que `target_branch` n'est pas vide — si vide, le workflow checkout sur `main` et crée une nouvelle branche.
3. Vérifier les logs du workflow : `gh run view <run-id> --log` → section "Run binance-dev agent".
