# PR #142 — Clarifier le format date en Phase 8 du trade_prompt

> **Mergée le** : 2026-05-28
> **Branche** : `feat/issue-124-clarify-date-format`
> **Issues** : #124

## Contexte

La Phase 7 du TRADE_PROMPT écrit des heartbeat logs au format JSONL (`logs/cycle_<id>_phases.jsonl`), chacun avec un timestamp `ts` en ISO 8601 UTC. Ces logs sont essentiels pour tracer l'exécution chronologique des 7 phases d'un même cycle et permettre le débogage précis.

Le ticket #124 relevait une ambiguïté dans la documentation : clarifier pourquoi le format utilise les secondes (`%Y-%m-%dT%H:%M:%SZ`) plutôt que seulement les minutes. Cette PR documente et justifie ce choix existant dans le code.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `CLAUDE.md` | Modification | Clarification de la section 5 « Convention horaire » : ajout d'une ligne explicitant la raison des secondes dans les timestamps JSONL |
| `prompts/trade_prompt.txt` | Modification | Ajout d'un commentaire inline dans la fonction `hb()` (Phase 7) documentant la raison du format avec secondes |

### Détails des modifications

**1. CLAUDE.md (section 5, ligne 46)**

Ajout d'une clarification explicite :
```
- **Format date pour l'unicité par cycle** : les heartbeat logs (JSONL) utilisent le format `%Y-%m-%dT%H:%M:%SZ` **avec secondes** pour garantir que chaque phase d'un même cycle ait un timestamp distinct (7 phases peuvent s'exécuter en moins de 60s). L'agrégation horaire seule (`%H:%M`) serait insuffisante.
```

Cette ligne explique que sans les secondes, deux phases rapides (ex : Phase 6 et Phase 7 s'exécutant dans la même minute) auraient le même timestamp dans le JSONL, ce qui perdrait l'ordre chronologique. Les secondes sont indispensables pour l'unicité et le tri des événements.

**2. prompts/trade_prompt.txt (fonction `hb()`, lignes 24–28)**

Ajout d'un commentaire multi-lignes dans la fonction `hb()` de Phase 7 :
```python
def hb(phase, status="ok", summary=""):
    # Format date incluant les secondes (%H:%M:%S) pour l'unicité par cycle :
    # chaque phase d'un même cycle a des secondes distinctes, ce qui permet
    # d'identifier précisément l'ordre chronologique des événements dans le JSONL
    # (agrégation horaire seule serait insuffisante pour différencier 7 phases en <60s)
```

Le commentaire capture la logique métier directement au point où le format est appliqué, facilitant la compréhension sans obligatoirement relire CLAUDE.md.

## Décisions techniques notables

- **Documentation vs modification de code** : aucun changement logique dans le code lui-même. La PR est une **clarification documentaire** du comportement existant, conforme au ticket #124.

- **Double documentation** : ajouter la clarification dans CLAUDE.md (règles non négociables) **et** dans un commentaire du prompt (où le code la justifie) assure que la justification est accessible du point de vue du maintainer et du développeur.

- **Pas de code applicatif touché** : seule documentation modifiée ; aucun impact sur les tests, les builds ou le runtime du bot.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. La convention de timestamp UTC avec secondes était déjà en vigueur depuis la PR #23 (2026-05-21). Cette PR en clarifie la raison, augmentant la maintenabilité et réduisant la confusion future.

## Références CLAUDE.md respectées

- **Règle 8** (modifications via agent `binance-dev`) : cette PR modifie `CLAUDE.md` et `prompts/trade_prompt.txt`. Les deux fichiers sont autorisés en exception directe sur `main` (CLAUDE.md est meta-règles, trade_prompt est config). Aucune modification de code applicatif (`scripts/webhook_server.py`).

- **Section 5, Convention horaire** : la clarification renforce et documente une règle existante déjà enoncée dans cette section, sans la modifier.

- **Jamais de modifications directes sur `main`** : bien que la PR soit simple, elle a suivi le workflow normal ticket → branche → PR → review → merge, conforme aux directives.
