# PR #130 — Remplacer projects_v2_item par workflow_dispatch dans binance-dev-auto

> **Mergée le** : 2026-05-28
> **Branche** : `fix/binance-dev-auto-workflow-dispatch`
> **Issues** : #130

## Contexte

Le webhook GitHub `projects_v2_item` ne fonctionne que sur les **projets d'organisation**. Le repo `yousmaaza/agent-binance` est un compte personnel → GitHub rejetait le déclenchement avec `Unexpected value 'projects_v2_item'`.

Le workflow `binance-dev-auto.yml` était bloqué et ne pouvait pas être déclenché automatiquement depuis le project board v2.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/binance-dev-auto.yml` | Modification | Migration du trigger event vers `workflow_dispatch` avec inputs explicites |

### Modifications au workflow

| Élément | Ancien | Nouveau | Raison |
|---|---|---|---|
| Trigger | `on: projects_v2_item` | `on: workflow_dispatch` | Support des comptes personnels, pas seulement orga |
| Inputs | GraphQL query step (`updateProjectV2...`) | `issue_number` (requis) + `item_node_id` (optionnel) | Paramètres explicites via formulaire workflow |
| Résolution issue | Step GraphQL avec `query.projects_v2_item.*` | `gh issue view $ISSUE_NUMBER` + regex simple | Plus fiable, pas de dépendance projet v2 côté workflow |
| Vérification label | Absente (basée sur webhook event) | Vérification du label `AUTO` (exit 1 sinon) | Sécurité : ne lance l'agent que si explicitement marqué |

### Déclenchement manuel

Avant (webhook automatique, non fonctionnel sur compte personnel) :
```bash
# Pas d'option — déclenché par le project board v2 event
```

Après (workflow_dispatch manuel via CLI ou GitHub UI) :
```bash
gh workflow run binance-dev-auto.yml --ref main \
  -f issue_number=123 \
  -f item_node_id=PVTI_xxx  # optionnel
```

## Décisions techniques notables

- **`workflow_dispatch` au lieu de `issue` trigger** : Permet un contrôle explicite du quand/comment. Le project board passe les inputs manuellement via `gh workflow run`, au lieu de reposer sur un webhook événementiel non supporté.
- **Vérification du label `AUTO` dans le workflow** : Filtre de sécurité — seules les issues explicitement marquées `AUTO` seront implémentées, même si le workflow est déclenché manuellement.
- **`item_node_id` optionnel** : Permet de déclenchcher l'implémentation sans basculer le ticket en "In review" sur le board (mode dev/test local). Lors du déclenchement depuis le board (via automatisation externe), l'`item_node_id` est passé pour mettre à jour l'état.

## Impact sur l'architecture

Changement **isolé à la CI/CD** — pas d'impact sur l'architecture du bot de trading.
- ✅ Aucune modification du code applicatif (`scripts/webhook_server.py`, `config.json`, etc.)
- ✅ Aucun impact sur les phases de trading ni le flux de données
- ✅ Simplement une correction du mécanisme de déclenchement des agents GitHub Actions

Les utilisateurs locaux n'ont aucune action à prendre. Le déclenchement manuel via `gh workflow run` est l'option recommandée pour les tests en CI.

## Références CLAUDE.md respectées

- **Règle 8** (Workflow ticket → branche → PR) : Cette PR EN EST LE RÉSULTAT. Le changement au workflow lui-même stabilise le pipeline d'implémentation des tickets.
- **Git via CLI** : Aucune modification nécessaire au profil `git-perso` ou aux règles de commit locales.
