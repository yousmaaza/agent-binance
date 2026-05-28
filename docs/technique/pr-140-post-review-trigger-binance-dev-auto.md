# PR #140 — Post-review déclenche binance-dev-auto sur tickets [REC]

> **Mergée le** : 2026-05-28
> **Branche** : `feat/post-review-trigger-binance-dev-auto`
> **Issues** : #140

## Contexte

Avant cette PR, les recommandations de review (sections `⚠️ À simplifier` et `💡 Pour aller plus loin` du commentaire tech lead) étaient converties en tickets GitHub par l'agent `ticket-manager`, mais la création du ticket s'arrêtait là. L'implémentation devait être déclenchée manuellement soit par l'utilisateur invoquant `binance-dev` directement, soit via le script `dispatch_rec_tickets.sh` (qui avait été créé comme workaround).

Le but de cette PR : **automatiser complètement la chaîne review → tickets → implémentation** sans aucune intervention manuelle. Dès qu'un ticket `[REC]` est créé avec les labels `tech-lead-review` et `AUTO`, le workflow `binance-dev-auto` se déclenche et lance l'implémentation.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.github/workflows/claude-post-review.yml` | Modification | Ajout du label `AUTO` et dispatch du workflow `binance-dev-auto` pour chaque ticket créé |
| `dispatch_rec_tickets.sh` | Ajout (nouveau) | Script utilitaire bash pour dispatcher manuellement les workflows pour tickets existants (migration) |
| `label_rec_auto.sh` | Ajout (nouveau) | Script utilitaire bash pour ajouter rétroactivement le label `AUTO` aux tickets `[REC]` historiques |

### Détails des modifications

**1. `.github/workflows/claude-post-review.yml`**

- **Step "Ensure tech-lead-review + AUTO labels exist"** (lignes 154-169) :
  - Création du label `AUTO` avec couleur `0075ca` et description "Ticket éligible au workflow binance-dev-auto"
  - Garantit que le label existe avant d'être appliqué aux tickets

- **Job "create-recommendation-tickets" — prompt ticket-manager** (lignes 171-237) :
  - Modification critique : après création de chaque ticket, le prompt ajoute l'exécution de `gh workflow run binance-dev-auto.yml` (lignes 218-226)
  - Paramètres transmis : `issue_number` et `item_node_id` (le node ID GraphQL du ticket dans le projet)
  - `sleep 10` entre chaque dispatch pour éviter les race conditions GitHub Actions
  - Commentaire récap sur la PR mentionne le déclenchement des workflows (ligne 232)

**2. `dispatch_rec_tickets.sh` (nouveau)**

Script bash autonome pour dispatcher manuellement les workflows. Usage :
- `./dispatch_rec_tickets.sh` : dispatch immédiat pour tous les tickets `[REC] + In progress + AUTO`
- `./dispatch_rec_tickets.sh --dry-run` : affiche ce qui serait dispatché sans exécuter

Interroge le board via GraphQL pour trouver les tickets éligibles (plutôt que de relire une liste statique).

**3. `label_rec_auto.sh` (nouveau)**

Script bash pour migrer les tickets historiques. Usage :
- `./label_rec_auto.sh` : ajoute le label `AUTO` sur tous les tickets `[REC]` sans ce label
- `./label_rec_auto.sh --dry-run` : affiche ce qui serait modifié

Utile pour traiter les tickets `[REC]` créés avant cette feature et qui n'auraient donc pas reçu le label automatiquement.

## Décisions techniques notables

- **Dispatch dans le prompt ticket-manager, pas en step séparé** : garder la logique de dispatch au même endroit que la création de tickets facilite le débogage et rend le flux plus clair. Un step post-creation aurait complexifié la communication entre jobs.

- **sleep 10 entre dispatches** : les race conditions GitHub Actions sont rares mais réelles quand on lance plusieurs `gh workflow run` en succession rapide. 10 secondes est un équilibre entre débit et fiabilité sans bloquer indéfiniment.

- **Scripts en bash plutôt qu'en Python** : les deux scripts utilitaires (dispatch + label) ne dépendent pas de la stack Python du projet et doivent pouvoir tourner rapidement en standalone. Bash + `gh api` est plus léger et plus portable.

- **Interrogation GraphQL du board** : plutôt que de passer une liste en paramètre, les scripts queryent le board en temps réel pour éviter le décrochage entre la réalité (tickets supprimés, statut changé) et une liste statique.

## Impact sur l'architecture

**Avant** :
```
Review tech lead
    ↓
Création tickets [REC] manuels ou via ticket-manager
    ↓
Utilisateur invoque binance-dev ou dispatch_rec_tickets.sh
    ↓
Workflow binance-dev-auto se déclenche
```

**Après** :
```
Review tech lead
    ↓
Création tickets [REC] via ticket-manager (labels: AUTO, tech-lead-review)
    ↓
ticket-manager → gh workflow run binance-dev-auto automatiquement
    ↓
Workflow binance-dev-auto se déclenche sans action manuelle
```

**Impact architectural** : suppression d'une étape manuelle dans la chaîne CI/CD. Le flux devient entièrement automatisé du commentaire de review jusqu'au démarrage de l'implémentation. Aucun changement aux scripts applicatifs ou à la logique métier.

## Références CLAUDE.md respectées

- **Règle 8** (modifications de code via agent `binance-dev`) : cette PR modifie la CI/CD et les workflows GitHub, pas le code applicatif (`scripts/webhook_server.py`). Workflow GitHub = infrastructure, exception autorisée par CLAUDE.md.

- **Jamais de modifications directes sur `main`** : la PR a suivi le workflow normal ticket → branche → PR → review → merge, conforme aux directives.
