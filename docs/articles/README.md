# docs/articles/ — Brouillons pour articles Medium

Espace de brainstorming et de rédaction pour les articles Medium tirés du projet `agent-binance`.

## Sources d'inspiration

- **`docs/medium-recap.md`** : chronologie 19→21 mai 2026 (POC à v2), 9 étapes structurantes avec problème/décision/angle.
- **`docs/medium-journal.md`** : journal quotidien auto-alimenté par l'agent `daily-recap` (cron 23h Paris, branche `doc/medium-report`). Matière brute pour suivre l'évolution post-v2.
- **`docs/technique/SPEC.md`** : spec technique à jour. Source de vérité pour les détails d'implémentation.
- **`docs/fonctionnel/*.md`** : doc utilisateur des commandes Telegram (`/trade`, `/status`, `/perf`, etc.).
- **`docs/visuals/*.svg`** : diagrammes D2 prêts à embarquer dans les articles.

## Convention de nommage

`NN-slug-court.md` où `NN` est l'ordre de publication souhaité.

Exemples : `01-setup-projet-prompt-mcp.md`, `02-otoco-binance-spot.md`, `03-agents-claude-code.md`.

Pas de date dans le nom de fichier — l'ordre de publication peut bouger pendant la rédaction.

## Workflow par article

Chaque article passe par 3 états :

1. **Brouillon (`status: draft`)** : plan détaillé + bullets, pas de prose finale. Tu rédiges dessus librement.
2. **En rédaction (`status: writing`)** : prose en cours, paragraphes complets, structure figée.
3. **Publié (`status: published`)** : URL Medium ajoutée en tête, fichier en lecture seule.

Le statut est dans le frontmatter YAML en haut de chaque fichier d'article. Pas de hook automatique pour le moment.

## Index

| # | Titre | Statut | URL Medium |
|---|---|---|---|
| 01 | Setup d'un bot de trading piloté par Claude + MCP TradingView | draft | — |

## Conventions de rédaction

- **Français** (même langue que les notifications Telegram et le `CLAUDE.md`).
- **Pas de jargon crypto** non explicité — vise un public dev senior pas forcément trader.
- **Snippets de code** : 5 à 15 lignes max, toujours avec un chemin `file.py:line` en commentaire.
- **Captures d'écran** : place les fichiers dans `docs/articles/assets/<article-slug>/` (créer le dossier si besoin).
- **Liens** : interne au repo OK pour ton brouillon, mais avant publication Medium, remplacer par des liens GitHub absolus.

## Idées d'articles futurs (backlog)

- **Pivot OTOCO → BUY MARKET + OCO immédiat** : récit du bug Binance, choix d'archi.
- **Industrialisation : 3 agents Claude + GitHub Actions** : `ticket-manager`, `binance-dev`, `tech-lead-reviewer`.
- **CLAUDE.md, ou comment apprivoiser une IA en 100 lignes** : focus sur le fichier de conventions.
- **Stream-json : voir Claude penser en direct** : streaming logs, parser inline.
- **Cost-engineering LLM : Sonnet pour le bot, Haiku pour les agents** : différenciation explicite entre tâches à enjeu et tâches outillage.
- **Trailing stop : la première amélioration de stratégie venue d'un humain (pas du LLM)** : ce que l'IA n'a pas vu.
- **Routines remote Claude Code : un agent qui ne dort jamais** : daily-recap, schedule, branche dédiée.
