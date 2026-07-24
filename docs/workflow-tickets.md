# Workflow de traitement des tickets

Ce document explique comment un ticket GitHub devient du code mergé sur `main` dans ce projet — à la main, ou entièrement automatisé via GitHub Actions.

## Vue d'ensemble

```
Ticket créé (manuel ou ticket-manager)
        │
        ├─ Sans label AUTO ────────► invoquer binance-dev manuellement (Claude Code local)
        │
        └─ Label "AUTO" ───────────► auto-dispatch-on-auto-label.yml
                                            │
                                            ▼
                                     binance-dev-auto.yml (CI, mode AUTO)
                                            │  crée branche feat/issue-N-slug, implémente, ouvre la PR
                                            ▼
                              claude-code-review.yml (auto sur "PR opened")
                                            │  poste un commentaire de review (tech-lead-reviewer)
                                            ▼
                              claude-post-review.yml (auto après la review)
                                     ├─ Job 1 : corrige les 🛑 bloquants directement sur la branche PR
                                     └─ Job 2 : crée un ticket [REC] (label REC-AUTO) par recommandation ⚠️/💡
                                            │
                                            ▼
                              auto-dispatch-on-auto-label.yml (label REC-AUTO)
                                            │
                                            ▼
                                     binance-dev-auto.yml (CI, mode REC-AUTO)
                                            │  implémente SUR LA BRANCHE PR EXISTANTE, ferme le ticket [REC]
                                            ▼
                              rec-complete-review.yml (sur fermeture d'un ticket REC-AUTO)
                                            │  si tous les [REC] de la PR sont fermés → relance la review
                                            └─ sinon attend les autres [REC]
                                            ▼
                                     (boucle jusqu'à review propre)
                                            │
                                            ▼
                              L'UTILISATEUR MERGE LA PR (jamais automatique)
                                            │
                                            ▼
                              claude-doc-tech.yml (auto sur "PR merged")
                                     génère docs/technique/pr-N-slug.md, met à jour SPEC.md + README.md,
                                     miroir GitHub Wiki (best-effort)
                                            │
                                            ▼
                              Déployer sur la VPS : gh workflow run deploy-vps.yml (manuel, voir deploy/README.md)
```

En parallèle, deux routines cloud planifiées (pas des GitHub Actions — voir `/schedule`) tournent chaque jour : une analyse `state/cycle_log.jsonl` pour proposer des tickets `[CONFIG]` si la stratégie mérite un ajustement, une autre alimente `docs/medium-journal.md` (branche `doc/medium-report`) à partir des PR mergées et tickets fermés du jour.

## 1. Création d'un ticket

- **Manuelle** : `gh issue create` ou via l'agent `ticket-manager` (connaît les conventions de titre/labels/priorité/taille du board "Binance Bot Agent", projet #4).
- **Automatique** : après tout `ExitPlanMode` approuvé, `ticket-manager` est invoqué automatiquement pour convertir le plan validé en epic + sous-tickets.
- Le board a 5 statuts : `Backlog` → `Ready` → `In progress` → `In review` → `Done`. Priorité `P0`/`P1`/`P2`, taille `XS`→`XL`.

## 2. Implémentation — deux chemins possibles

### Chemin manuel (le plus courant pour du travail supervisé)

L'utilisateur (ou moi, Claude Code, en session interactive) invoque l'agent `binance-dev` (Task tool). Il :
1. Vérifie que l'arbre de travail est propre (`git status --porcelain`) — **abort si non**, ne touche à rien.
2. Sélectionne le ticket `In progress` le plus prioritaire (P0>P1>P2, puis taille XS→XL) — ou implémente le ticket spécifié.
3. Crée une branche `feat/issue-<N>-<slug>` depuis `main`.
4. Implémente, respecte `CLAUDE.md`, commit, push.
5. Ouvre une PR liée à l'issue, bascule le ticket en `In review`.

### Chemin automatique (label `AUTO`)

Ajouter le label **`AUTO`** sur une issue déclenche `auto-dispatch-on-auto-label.yml` :
1. Ajoute l'issue au board si absente, bascule en `In progress`.
2. Dispatche `binance-dev-auto.yml` (`workflow_dispatch`), qui lance `binance-dev` via `anthropics/claude-code-action` (modèle `claude-haiku-4-5`, 60 tours max) directement en CI — même logique que le chemin manuel, avec quelques adaptations CI (pas de `git-perso`, pas de venv, `GH_PAT` déjà exporté).

## 3. Review automatique (à l'ouverture de la PR)

`claude-code-review.yml` se déclenche sur `pull_request: [opened, reopened]` — lance l'agent `tech-lead-reviewer` (ruff/radon/bandit/mypy + lecture complète des fichiers modifiés), poste un commentaire structuré sur la PR (note de maintenabilité, 🛑 Bloquants, ⚠️ Points d'attention, 💡 Pour aller plus loin).

## 4. Boucle post-review automatique

`claude-post-review.yml` se déclenche quand la review précédente se termine. Deux jobs :

- **`fix-bloquants`** : lit la review, corrige *directement* chaque item de la section 🛑 Bloquants sur la branche de la PR, commit, push. Aucun ticket créé pour les bloquants — ils sont corrigés immédiatement.
- **`create-rec-tickets`** : pour chaque item numéroté des sections ⚠️/💡 (recommandations non bloquantes), crée une issue `[REC] <titre>` labellisée `REC-AUTO`, avec des marqueurs `<!-- pr_branch: ... -->` / `<!-- pr_number: ... -->` dans le body pour savoir où l'implémenter. Max 5 tickets par PR.

Chaque ticket `[REC]` créé porte le label `REC-AUTO`, ce qui redéclenche `auto-dispatch-on-auto-label.yml` → `binance-dev-auto.yml`, mais en **mode REC-AUTO** cette fois : implémente directement sur la branche PR existante (pas de nouvelle branche, pas de nouvelle PR), puis ferme le ticket `[REC]` avec un commentaire de référence.

Quand un ticket `REC-AUTO` se ferme, `rec-complete-review.yml` vérifie si **tous** les `[REC]` de cette PR sont fermés :
- Si oui → redéclenche `claude-code-review.yml` (nouvelle review propre).
- Si non → attend les autres tickets `[REC]` encore ouverts.

Cette boucle continue jusqu'à obtenir une review sans bloquant ni nouvelle recommandation.

## 5. Merge — toujours manuel

**Aucun mécanisme de ce pipeline ne merge une PR automatiquement.** C'est une action volontaire de l'utilisateur, quel que soit le chemin (manuel ou `AUTO`).

## 6. Après le merge

`claude-doc-tech.yml` se déclenche sur `pull_request: closed` (si `merged == true`) : lance l'agent `binance-doc-tech`, qui génère `docs/technique/pr-<N>-<slug>.md`, met à jour `docs/technique/SPEC.md` et `docs/technique/README.md`, et mirrore best-effort sur le GitHub Wiki. Commit directement sur `main` (doc, pas de code applicatif).

Pour mettre en prod sur la VPS après un merge : déploiement **manuel** via `gh workflow run deploy-vps.yml` (voir `deploy/README.md` et la section "Déploiement" de `CLAUDE.md`) — volontairement séparé du merge, pas de mise en prod automatique sur un bot qui manipule de l'argent réel.

## 7. Routines cloud indépendantes (pas des GitHub Actions)

Deux routines planifiées via le mécanisme `/schedule` (cloud, pas dans `.github/workflows/`) :

- **Analyse config quotidienne** (`0 20 * * *` UTC) : lit `config.json` et `state/cycle_log.jsonl` (7 derniers jours), propose un ticket `[CONFIG]` si des critères de dérive sont atteints (ex: trop de `TYPE_A`/`TYPE_B`, scores élevés sans exécution, drawdown structurel).
- **Daily recap** (`0 21 * * *` UTC) : compose l'entrée du jour dans `docs/medium-journal.md` à partir des PR mergées/issues fermées/créées, commit sur la branche dédiée `doc/medium-report` (jamais sur `main`).

Les deux lisent uniquement des fichiers commités en git (pas `reports/*.md`, gitignored) — indépendantes de la machine qui héberge le bot (Mac ou VPS).

## Points de vigilance

- Les tickets `[REC]` doivent conserver leurs marqueurs `<!-- pr_branch -->`/`<!-- pr_number -->` dans le body — sans eux, `binance-dev-auto` ne sait pas où implémenter le fix et `rec-complete-review` ne peut pas retrouver la PR à re-review.
- Garde-fous constants sur tous les jobs automatisés : jamais `git add -A`/`git add .`, jamais `--force`, jamais de merge automatique, jamais de modification de `.env`/`state/trade_history.json`/`CLAUDE.md`.
- Le modèle utilisé en CI est `claude-haiku-4-5-20251001` pour tous les agents automatisés (coût/vitesse) — différent du modèle par défaut d'une session Claude Code interactive.
