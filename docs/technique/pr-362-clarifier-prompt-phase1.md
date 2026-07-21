# PR #362 — Clarifier le prompt Phase 1 — TypeError unhashable slice

> **Mergée le** : 2026-07-21
> **Branche** : `feat/issue-359-clarifier-prompt-phase1-typeerror-slice`
> **Issues** : #359

## Contexte

Le prompt Phase 1 décrivait le fichier de sortie `/tmp/cycle_{CYCLE_ID}_phase1_output.json` sans clarifier que sa structure est un **dict racine** (objet JSON) avec deux clés (`tradable` et `non_tradable`), pas une liste. Claude générait parfois du code qui tentait de slicer le dict directement (ex: `tradable[:30]`), causant une exception `TypeError: unhashable type: 'slice'` en Phase 1. Bien que le bot disposait d'un fallback, cela polluait les logs `logs/stderr/` de chaque cycle affecté.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/phases/phase1_scan.txt` | Clarification textuelle | Prévention de `TypeError: unhashable type: 'slice'` en Phase 1 |

### Contenus ajoutés/modifiés

**Ligne 15–21 du prompt Phase 1** :
- **Avant** : "Lis le fichier `/tmp/cycle___CYCLE_ID___phase1_output.json`" (sans détail sur la structure)
- **Après** : 
  - Précise que le fichier contient un **objet JSON racine** (dict) avec deux clés : `{"tradable": [...], "non_tradable": [...]}`
  - Ajoute un **exemple de lecture correcte** :
    ```python
    data = json.load(f)
    tradable = data["tradable"]
    ```
  - Affirme explicitement : "accède-y par sa clé, ne slice jamais le dict racine"

## Décisions techniques notables

- **Approche texte uniquement** : pas de modification de code Python ou de la structure JSON elle-même. Le fix repose sur la clarification du prompt pour guide Claude vers le code correct.
- **Exemple de code dans le prompt** : met en avant la bonne pratique (accès par clé) directement dans le prompt, plutôt que laisser Claude la déduire.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. Phase 1 continue de générer le même JSON, mais le prompt évite désormais la génération de code erroné qui tentait de le traiter comme une liste.

## Références CLAUDE.md respectées

- **Principe "Réfléchir avant de coder"** : clarification explicite du format attendu pour prévenir les malinterprétations
- **Minimalisme** : ajout minimal au prompt (7 lignes) pour résoudre un problème précis sans spéculation

## Test plan

Après merge, le bot ne génère plus d'erreur `TypeError: unhashable type: 'slice'` en Phase 1 sur cycles successifs.
