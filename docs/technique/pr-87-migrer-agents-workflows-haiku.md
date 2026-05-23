# PR #87 — [M86] Migrer agents et workflows CI/CD vers claude-haiku

> **Mergée le** : 2026-05-23
> **Branche** : `feat/issue-86-haiku-agents-workflows`
> **Issues** : #86

## Contexte

Réduction des coûts et amélioration de la vélocité des workflows CI/CD automatisés. L'agent `binance-dev` et les agents de documentation exécutant des tâches structurées et répétitives peuvent fonctionner avec `claude-haiku-4-5-20251001` sans perte de qualité, réduisant ainsi les coûts d'exécution.

**Decision** : Conserver `claude-sonnet-4-6` pour le **bot de trading** (Phase 0-7 du cycle d'exécution, stratégie complexe) et migrer uniquement les **agents CI/CD et documentaires** vers haiku.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/binance-dev-auto.yml` | Modification | Migration du modèle Claude pour l'implémentation automatique des tickets |
| `.github/workflows/claude-doc-tech.yml` | Modification | Migration du modèle Claude pour la génération de documentation technique |
| `.github/workflows/claude-post-review.yml` | Modification | Migration du modèle Claude pour les corrections post-review (2 jobs) |
| `.claude/agents/binance-dev.md` | Modification | Changement `model: sonnet` → `model: haiku` dans le frontmatter |
| `.claude/agents/binance-doc-fonc.md` | Modification | Changement `model: sonnet` → `model: haiku` dans le frontmatter |
| `.claude/agents/binance-doc-tech.md` | Modification | Changement `model: sonnet` → `model: haiku` dans le frontmatter |
| `.claude/agents/tech-lead-reviewer.md` | Modification | Changement `model: sonnet` → `model: haiku` dans le frontmatter |
| `.claude/agents/ticket-manager.md` | Modification | Changement `model: sonnet` → `model: haiku` dans le frontmatter |

### Modèles Claude par contexte

| Contexte | Modèle | Raison |
|---|---|---|
| Bot de trading (Phase 0-7) | `claude-sonnet-4-6` | Stratégie d'ordre complexe, analyse marché multi-timeframe, gestion du risque — nécessite le meilleur modèle |
| Agent `binance-dev` (implémentation tickets) | `claude-haiku-4-5-20251001` | Implémentation structurée, directivités claires via `CLAUDE.md` → haiku suffisant |
| Agent `binance-doc-fonc` (docs utilisateur) | `claude-haiku-4-5-20251001` | Rédaction templée, pas de logique complexe → haiku suffisant |
| Agent `binance-doc-tech` (docs architecture) | `claude-haiku-4-5-20251001` | Analyse + extraction structurée de code → haiku suffisant |
| Agent `tech-lead-reviewer` (code review) | `claude-haiku-4-5-20251001` | Analyse de static tools + pattern matching → haiku suffisant |
| Agent `ticket-manager` (gestion tickets) | `claude-haiku-4-5-20251001` | CRUD GitHub via CLI, pas de logique métier → haiku suffisant |
| Workflow `claude-code-review.yml` | `claude-haiku-4-5-20251001` | Inchangé — déjà en haiku depuis le départ |

## Décisions techniques notables

1. **Séparation claire modèle critique vs. optimisable**  
   Le bot de trading (orchestrateur principal) reste en Sonnet car il dirige la stratégie d'exécution d'ordres. Les agents helpers (CI/CD, doc) qui supportent le développement peuvent être en Haiku sans risque.

2. **Pas de modification de `binance-bot/config/llm.py`**  
   La configuration du modèle pour les exécutions de trading reste inchangée. Seuls les workflows CI/CD et les définitions d'agents helpers sont migrés.

3. **Synchronisation agents + workflows**  
   Chaque agent a un `model:` field en frontmatter. Les workflows GitHub Actions qui lancent ces agents via `anthropics/claude-code-action` utilisent le même modèle en `claude_args`. Les deux doivent rester synchronisés.

## Impact sur l'architecture

Changement **non architectural**. Les interfaces, les flux de données, et les responsabilités des agents restent identiques. Seule l'exécution CI/CD devient moins coûteuse. Pas d'impact sur le cycle de trading lui-même.

## Références CLAUDE.md respectées

- **Règle 7** (Python via venv 3.11) : Les workflows continuent à initialiser Python 3.11.
- **Règle 8** (modification via agent `binance-dev`) : Cette PR elle-même a été implémentée via l'agent `binance-dev`.
- Pas de modification de `scripts/`, `state/`, ou `CLAUDE.md`.

## Test plan

- ✅ `.claude/agents/*.md` — tous les 5 agents ont `model: haiku` (frontmatter)
- ✅ `.github/workflows/binance-dev-auto.yml` — `--model claude-haiku-4-5-20251001`
- ✅ `.github/workflows/claude-doc-tech.yml` — `--model claude-haiku-4-5-20251001`
- ✅ `.github/workflows/claude-post-review.yml` — `--model claude-haiku-4-5-20251001` (2 jobs)
- ✅ `binance-bot/config/llm.py` — toujours `claude-sonnet-4-6`
- ✅ `.github/workflows/claude-code-review.yml` — inchangé
- ✅ YAML valide sur tous les workflows modifiés
