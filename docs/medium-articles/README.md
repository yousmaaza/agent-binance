# docs/medium-articles/ — Articles Medium

Espace de brainstorming et de rédaction pour les articles Medium tirés du projet `agent-binance`.

## Sources d'inspiration

- **`docs/medium-recap.md`** : chronologie 19→21 mai 2026 (POC à v2), 9 étapes structurantes avec problème/décision/angle.
- **`docs/medium-journal.md`** : journal quotidien auto-alimenté par l'agent `daily-recap` (cron 23h Paris, branche `doc/medium-report`). Matière brute pour suivre l'évolution post-v2.
- **`docs/technique/SPEC.md`** : spec technique à jour. Source de vérité pour les détails d'implémentation.
- **`docs/fonctionnel/*.md`** : doc utilisateur des commandes Telegram (`/trade`, `/status`, `/perf`, etc.).
- **`docs/visuals/*.svg`** : diagrammes D2 prêts à embarquer dans les articles.

## Convention de nommage

**Fichiers** : `NN-slug-court.md` où `NN` est l'ordre de publication souhaité.

Exemples : `01-setup-projet-prompt-mcp.md`, `02-otoco-binance-spot.md`, `03-agents-claude-code.md`.

**Branches Git** : `article/NN-slug-court` — une branche par article pour isoler le brainstorming et la rédaction.

Exemple : `article/01-setup-projet-prompt-mcp`.

Pas de date dans le nom de fichier — l'ordre de publication peut bouger pendant la rédaction.

## Workflow par article

```
article/NN-slug  →  (brainstorm → rédaction → relecture)  →  merge dans docs/medium-articles
                                                                ↑
                                                     uniquement quand status = published
```

### Cycle de vie d'un article

Chaque article passe par 3 états dans le frontmatter YAML :

1. **`status: draft`** — Plan détaillé + bullets, pas de prose finale. L'agent `medium-articles-manager` initialise cet état.
2. **`status: writing`** — Prose en cours, paragraphes complets, structure figée. Tu mets à jour le statut manuellement.
3. **`status: published`** — URL Medium renseignée, article figé. L'agent `medium-articles-manager` peut passer à cet état sur commande.

### Branches et merges

- Chaque article vit sur sa propre branche `article/NN-slug`.
- La branche `docs/medium-articles` est la branche de référence : elle accumule les articles **publiés**.
- Les branches `article/*` se créent depuis `docs/medium-articles` (pas `main`).
- On merge dans `docs/medium-articles` uniquement quand `status: published`.
- La CI (tech-lead-review, doc-tech) est skippée sur `article/*` et `docs/medium-*`.

### Commandes de l'agent `medium-articles-manager`

| Action | Ce que tu dis | Ce que fait l'agent |
|---|---|---|
| Nouvel article | `/medium new "Titre de l'article"` | Crée branche `article/NN-slug`, initialise le fichier brouillon, ouvre une issue de tracking |
| Publier | `/medium publish NN https://medium.com/...` | Met `status: published` + URL, met à jour l'index README, ferme l'issue |

## Index

| # | Titre | Statut | URL Medium |
|---|---|---|---|
| 01 | Setup d'un bot de trading piloté par Claude + MCP TradingView | ✅ published | [Lire](https://medium.com/@yousrimaazaoui_98610/claude-code-mcp-tradingview-binance-cli-lalliance-ultime-pour-vos-agents-autonomes-1953597730d5) |

## Conventions de rédaction

- **Français** (même langue que les notifications Telegram et le `CLAUDE.md`).
- **Pas de jargon crypto** non explicité — vise un public dev senior pas forcément trader.
- **Snippets de code** : 5 à 15 lignes max, toujours avec un chemin `file.py:line` en commentaire.
- **Captures d'écran** : place les fichiers dans `docs/medium-articles/assets/<article-slug>/` (créer le dossier si besoin).
- **Liens** : interne au repo OK pour ton brouillon, mais avant publication Medium, remplacer par des liens GitHub absolus.

## Idées d'articles futurs (backlog)

- **Pivot OTOCO → BUY MARKET + OCO immédiat** : récit du bug Binance, choix d'archi.
- **Industrialisation : 3 agents Claude + GitHub Actions** : `ticket-manager`, `binance-dev`, `tech-lead-reviewer`.
- **CLAUDE.md, ou comment apprivoiser une IA en 100 lignes** : focus sur le fichier de conventions.
- **Stream-json : voir Claude penser en direct** : streaming logs, parser inline.
- **Cost-engineering LLM : Sonnet pour le bot, Haiku pour les agents** : différenciation explicite entre tâches à enjeu et tâches outillage.
- **Trailing stop : la première amélioration de stratégie venue d'un humain (pas du LLM)** : ce que l'IA n'a pas vu.
- **Routines remote Claude Code : un agent qui ne dort jamais** : daily-recap, schedule, branche dédiée.
