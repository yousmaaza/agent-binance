# PR #117 — ci: skip workflows tech-lead-review et doc-tech sur doc/medium-report

> **Mergée le** : 2026-05-25
> **Branche** : `ci/skip-doc-medium-report`
> **Issues** : N/A

## Contexte

La branche `doc/medium-report` accumule des commits générés automatiquement par la routine `daily-recap` qui alimente le fichier `docs/medium-journal.md`. Cette branche :
- Ne contient que des modifications de documentation (journal Medium)
- N'a pas de code Python à reviewer
- N'est jamais mergée (reste ouverte indéfiniment pour accumulation de logs)

Or, les workflows CI (`claude-code-review` et `claude-doc-tech`) se déclenchaient inutilement sur chaque commit, consommant du quota agent Claude sans bénéfice.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/claude-code-review.yml` | Modification | Ajoute un filtre pour skip la branche `doc/medium-report` du tech-lead-review |
| `.github/workflows/claude-doc-tech.yml` | Modification | Ajoute un filtre pour skip la branche `doc/medium-report` de la génération doc technique |

### Détail des changements

**`claude-code-review.yml`** (ligne 17) :
```yaml
if: github.event.pull_request.head.ref != 'doc/medium-report'
```
Le job `tech-lead-review` ne s'exécutera plus si la PR provient de la branche `doc/medium-report`.

**`claude-doc-tech.yml`** (lignes 15-17) :
```yaml
if: |
  github.event.pull_request.merged == true &&
  github.event.pull_request.head.ref != 'doc/medium-report'
```
Le job `doc-tech` ne s'exécutera plus si la PR provient de la branche `doc/medium-report`, en complément de la condition existante "PR mergée".

## Décisions techniques notables

- **Filtre au niveau du workflow, pas du job** : le filtre est appliqué au niveau des conditions GitHub Actions (`if:`) pour éviter que le runner ne soit allocué inutilement
- **Branche complète en dur** : utilisation de `github.event.pull_request.head.ref != 'doc/medium-report'` plutôt qu'une regex, pour clarté et performance
- **Pas de skip des autres workflows** : seuls les deux workflows dispendieux (review + doc-tech) sont skippés ; les workflows légers (tests, lint standard) continuent de tourner

## Impact sur l'architecture

Changement isolé au niveau CI/CD. Aucun impact sur l'architecture applicative du bot ou les workflows de trading. Économie de ressources agents uniquement.

## Références CLAUDE.md respectées

- Aucune modification du code applicatif (`scripts/`, `config.json`, `CLAUDE.md`)
- Modification CI/workflow autorisée (pas dans les contraintes non négociables)
