# PR #201 — Enrichir CLAUDE.md avec principes généraux de développement

> **Mergée le** : 2026-06-03
> **Branche** : `feat/issue-199-enrichir-claude-md`
> **Issues** : #199

## Contexte

Structurer et documenter les trois principes fondamentaux de développement du projet, qui étaient implicites dans le code mais n'étaient pas formalisés. Ces principes guident les décisions de conception et de refactorisation : réfléchir avant de coder, minimalisme du code, et modifications chirurgicales.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `CLAUDE.md` | Ajout section | Insertion de 73 lignes documentant les trois principes de développement, entre `## Stack` et `## Règles de modification non négociables` |

### Contenu ajouté

**Section `## Principes généraux de développement`** (nouvelles lignes 11–28) :

| Principe | Contenu |
|---|---|
| **Réfléchir avant de coder** | Énoncer les hypothèses explicitement, présenter les alternatives, ne pas implémenter dans le vague, signaler la solution la plus simple |
| **Minimalisme** | Code minimum qui résout le problème, pas de fonctionnalités spéculatives, pas d'abstraction pour un usage unique, pas de gestion d'erreur pour scénarios impossibles |
| **Modifications chirurgicales** | Toucher uniquement ce qui est nécessaire, préserver le style existant, mentionner (ne pas supprimer) le dead code non lié, traçabilité directe vers la demande utilisateur |

## Décisions techniques notables

- **Placement dans CLAUDE.md** : la section est placée immédiatement après `## Stack`, avant les `## Règles de modification non négociables`, pour établir les fondations culturelles avant les règles opérationnelles.

- **Format texte** : utilisation de listes à puces hiérarchisées pour une lisibilité optimale et une intégration facile avec le reste du document.

- **Aucun hardcodage d'exemples** : les principes sont énoncés en termes généraux, applicables à tous les contextes du projet, sans exemple de code spécifique qui pourrait devenir obsolète.

## Impact sur l'architecture

Changement isolé, **pas d'impact sur l'architecture globale**. Cette PR documente uniquement les intentions et les bonnes pratiques ; elle ne modifie aucun code applicatif, configuration, ou comportement du bot.

**Impact de gouvernance** :
- Clarifie les attentes pour les contributeurs (futurs agents ou humains).
- Fournit une base de discussion lors des reviews de code.
- Aligne les décisions de refactorisation sur une philosophie cohérente (minimalisme, traçabilité).

## Références CLAUDE.md respectées

- **Modification de CLAUDE.md lui-même** : conforme à la règle 3 (exception autorisée pour les méta-règles, pas de code applicatif).
- **Aucun secret, path hardcodé, ou dépendance externe** : la section est documentaire pure.
- **Français** : le contenu suit les conventions du projet (français vulgarisé, cible équipe francophone).
