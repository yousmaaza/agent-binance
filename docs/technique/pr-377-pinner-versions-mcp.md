# PR #377 — Pinner versions mcp/tradingview-mcp-server dans .mcp.json

> **Mergée le** : 2026-07-29
> **Branche** : `feat/issue-376-pinner-versions-mcp-tradingview`
> **Issues** : #376

## Contexte

L'outil MCP TradingView ne parvenait pas à démarrer en production (VPS) avec l'erreur :
```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'
```

Cause : `uv` (gestionnaire de paquets utilisé en CI) résolvait `mcp` vers la dernière version **2.0.0**, qui a supprimé et restructuré le module `mcp.server.fastmcp` (breaking change majeur entre 1.x et 2.x). Le serveur MCP `tradingview-mcp-server` 0.7.1 n'a pas encore été mis à jour pour être compatible avec `mcp>=2.0.0`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.mcp.json` | Modification | Pin explicite des versions dans le bloc `mcpServers.tradingview` |

### Détail des changements

Le fichier `.mcp.json` a été modifié pour ajouter des pins de version dans la commande `uvx` :

**Avant** :
```json
"tradingview": {
  "command": "uvx",
  "args": ["--from", "tradingview-mcp-server", "tradingview-mcp"]
}
```

**Après** :
```json
"tradingview": {
  "command": "uvx",
  "args": ["--from", "tradingview-mcp-server==0.7.1", "--with", "mcp==1.29.0", "tradingview-mcp"]
}
```

Explications :
- `tradingview-mcp-server==0.7.1` : version PyPI la plus récente (0.7.1 est le dernier release publié)
- `mcp==1.29.0` : dernière version 1.x disponible sur PyPI (dernière compatible avec le module `mcp.server.fastmcp` qui a été supprimé en 2.x)
- `--with` : directive `uv` pour épingler une dépendance transitive

## Décisions techniques notables

- **Pourquoi épingler et non attendre un fix en amont** : `tradingview-mcp-server` 0.7.1 ne reçoit plus de maintenance (pas de fix natif pour `mcp 2.x` publié). Épingler `mcp==1.29.0` garantit la déterminisme et élimine le risque que `uv` invalide son cache et re-résout vers une version incompatible.
- **Pourquoi 1.29.0 et non une autre 1.x** : `1.29.0` est le dernier release du channel 1.x sur PyPI (avant le breaking change 2.0.0).
- **Pas de modification du code métier** : ce changement est purement dans la configuration `.mcp.json` — aucune modification de scripts ou de la logique du bot.

## Impact sur l'architecture

Changement **isolé en configuration**. Aucun impact sur l'architecture globale ni sur le flux d'exécution du bot. Le serveur TradingView MCP démarre maintenant sans erreur, rendant les outils MCP (`mcp__tradingview__*`) disponibles lors d'un cycle de trading.

## Références CLAUDE.md respectées

- **Règle 3 (secrets et configuration)** : `.mcp.json` est un fichier de configuration, pas un secret — les pins de version y sont appropriées.
- **Aucune dépendance lourde ajoutée** : le changement n'ajoute aucune dépendance Python runtime — juste un pin `uv` pour déterminisme.
