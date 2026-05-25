# PR #118 — feat(medium): dossier medium-articles + agent + CI skip article/*

> **Mergée le** : 2026-05-25
> **Branche** : `docs/articles-brainstorm`
> **Issues** : Configuration documentaire + outillage agent

## Contexte

Cette PR met en place l'infrastructure complète pour la gestion des articles Medium tirés du projet `agent-binance` : création d'un espace de brainstorming structuré, d'un agent dédié pour automatiser le cycle de vie (branche → brouillon → publication → archivage), et de la configuration CI pour éviter les reviews techniques sur du contenu documentaire.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.claude/agents/medium-articles-manager.md` | Ajout | Nouvel agent de 277 lignes gérant le workflow complet des articles (new/publish/update-index) |
| `.claude/commands/medium.md` | Ajout | Slash command `/medium` qui invoque l'agent pour les 3 actions |
| `.github/workflows/claude-code-review.yml` | Modification | Étend le skip CI pour couvrir `article/*` et `docs/medium-*` en plus de `doc/medium-report` |
| `.github/workflows/claude-doc-tech.yml` | Modification | Idem : skip sur les branches Medium |
| `docs/medium-articles/README.md` | Ajout | Guide d'utilisation + conventions de nommage + tableau index articles + backlog d'idées |
| `docs/medium-articles/01-setup-projet-prompt-mcp.md` | Ajout | Brouillon (draft) du 1er article : setup du projet, prompt 8-phase, outils MCP TradingView |

### Nouvelles sections et comportements

#### 1. Agent `medium-articles-manager`

Trois actions :

| Action | Commande | Résultat |
|---|---|---|
| **new** | `/medium new "Titre d'article"` | Crée branche `article/NN-slug` depuis `docs/medium-articles`, initialise le fichier brouillon (frontmatter YAML + template sections vides), ouvre une issue de tracking GitHub |
| **publish** | `/medium publish NN https://medium.com/...` | Met `status: published` dans le frontmatter + URL Medium, met à jour le tableau index du README, ferme l'issue de tracking |
| **update-index** | `/medium update-index` | Lit tous les fichiers `.md` de `docs/medium-articles/`, extrait le frontmatter YAML (number, title, status, published_url), reconstruit le tableau index du README |

#### 2. Slash command `/medium`

Fichier `.claude/commands/medium.md` : invoque l'agent `medium-articles-manager` via le Task tool avec les arguments de l'action demandée.

#### 3. Extension CI

Les workflows `claude-code-review.yml` et `claude-doc-tech.yml` skippent maintenant trois branches/patterns Medium :
- `doc/medium-report` : journal daily-recap auto-alimenté (branche stable)
- `article/*` : brouillons en cours (aucun code Python)
- `docs/medium-*` : branche de base pour les articles publiés archivés

**Impact** : Aucune PR ouverte depuis ces branches ne déclenchera une review tech-lead ou une génération de doc-tech — elles sont purement documentaires.

#### 4. Structure des articles

Chaque article vit sur sa propre branche `article/NN-slug` :

```
Lifecycle:
  article/NN-slug (branche de travail)
    → status: draft (plan + bullets)
    → status: writing (prose complète)
    → status: published (URL Medium + figé)
    → merge dans docs/medium-articles (branche de base)
```

Frontmatter obligatoire :

```yaml
---
status: draft|writing|published
number: NN
slug: NN-slug-court
title: "Titre complet"
target_length: 1500-2200 mots
target_audience: devs senior, pas forcément traders
tags_medium: [Python, Claude, LLM, ...]
created: YYYY-MM-DD
published_url: ""  # rempli par /medium publish
github_issue: #N
---
```

#### 5. Brouillon initial

`docs/medium-articles/01-setup-projet-prompt-mcp.md` : brouillon du 1er article en mode "plan détaillé" (structure complète, snippets identifiés, matériel à préparer listé, questions ouvertes). À enrichir en prose par l'utilisateur.

## Décisions techniques notables

- **Agent ≠ rédaction** : `medium-articles-manager` gère uniquement la plomberie (branches, frontmatter, index). La rédaction du contenu est la responsabilité de l'utilisateur. Cela évite les hallucinations sur du contenu marketing.

- **Branche `docs/medium-articles` dédiée** : contrairement au workflow classique (branches from `main`), les articles se créent depuis `docs/medium-articles` pour isoler le brainstorming. Seuls les articles `status: published` y sont mergés.

- **Skip CI sur Medium** : les branches Medium ne contiennent aucun code Python — le skip CI (tech-lead, doc-tech) réduit le bruit et économise les appels API (reviews innécessaires).

- **Frontmatter YAML** : chaque article porte son état (draft/writing/published) et son URL Medium. L'index README est reconstruit automatiquement par l'agent sur chaque `publish` ou `update-index`.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture du bot de trading (`webhook_server.py`, phases, MongoDB, Telegram). `medium-articles-manager` est un outil d'organisation documentaire, externe au système de trading. Les branches Medium (article/*, docs/medium-*) sont skippées des workflows de review et de documentation technique, donc aucun cycle de rétroaction avec le core.

## Références CLAUDE.md respectées

- **Règle 8** (modifications via agent dédié) : ce changement passe par `medium-articles-manager`, un nouvel agent, qui respecte les règles d'isolation (jamais de commit direct sur main, jamais de modification de code applicatif).
- **Conventions de nommage** : `article/NN-slug` suit le pattern des branches de feature du projet.
- **Pas de code applicatif** : tous les changements touchent uniquement `docs/`, `.claude/agents/`, `.claude/commands/`, et les workflows `.github/` — jamais `scripts/`, `config.json`, `CLAUDE.md`, ou `binance-bot/`.

## Architecture de l'agent

| Composant | Responsabilité |
|---|---|
| `medium-articles-manager.md` (agent) | Logique de 3 actions (new/publish/update-index), gestion des branches, des fichiers, des issues GitHub |
| `medium.md` (slash command) | Point d'entrée utilisateur — parse les arguments et invoque l'agent via Task tool |
| `docs/medium-articles/` (répertoire) | Espace de stockage des brouillons + branche de base pour les articles publiés |
| `.github/workflows/*.yml` (CI) | Skip des branches Medium pour éviter les reviews innécessaires |

L'agent n'écrit jamais de prose — il gère la plomberie (branch, frontmatter, index), laissant la rédaction à l'utilisateur.
