# PR #371 — [M1-bis] Nettoyer phase4_sizing.txt (pseudo-code dupliqué avec le script)

> **Mergée le** : 2026-07-24
> **Branche** : `feat/issue-370-nettoyer-phase4-sizing`
> **Issues** : #370

## Contexte

Le prompt Phase 4 (`prompts/phases/phase4_sizing.txt`) contenait un pseudo-code détaillé (56 lignes) retraçant toute la logique de sizing, de calcul d'ATR, de TP intelligent, et d'arrondi Kraken. Cette logique était déjà complètement implémentée dans le script Python déterministe `binance-bot/core/phases/phase4_sizing.py`.

Ticket #370 demandait le nettoyage du prompt pour éliminer la duplication et le ramener à un simple **orchestration** (construire l'input JSON → appeler le script → lire l'output), conforme au pattern appliqué en PR #369 sur la Phase 5.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/phases/phase4_sizing.txt` | Refactorisation | Supprime 56 lignes de pseudo-code ; conserve uniquement l'orchestration (input JSON + appel script + lecture output) |

### Contenu du prompt avant/après

**Avant (détail algorithme)** :
```
- Calcul du risque : portfolio_total × risk_per_trade_pct
- Estimation ATR via range 4h (approximation 2% si indisponible)
- Calcul prix entry/stop/TP mécanique/intelligent (vs résistances)
- Extraction lot_decimals/ordermin/costmin via kraken pairs
- Arrondi quantité via step_size
- Vérifications budget/montant minimum
```

**Après (orchestration)** :
```
Construis /tmp/cycle___CYCLE_ID___phase4_input.json avec buy_candidates
Appelle __PROJECT_DIR__/.venv/bin/python3 __PROJECT_DIR__/binance-bot/core/phases/phase4_sizing.py __CYCLE_ID__
Lis /tmp/cycle___CYCLE_ID___phase4_output.json pour extraire :
  - ordres_prepares (liste des ordres dimensionnés)
  - skipped (coins ignorés)
```

### Fonctions affectées

| Fonction | Fichier | Action | Impact |
|---|---|---|---|
| `phase4_sizing()` | `binance-bot/core/phases/phase4_sizing.py` | Aucune modification | Script inchangé ; exécuté exactement comme avant |
| `run_trade_workflow()` | `binance-bot/orchestration/runner.py` | Aucune modification | Appel du prompt inchangé ; passe `__CYCLE_ID__` comme avant |

Aucune modification Python. C'est un changement de documentation du prompt uniquement.

## Décisions techniques notables

- **Éliminer la duplication documentation/code** : le pseudo-code du prompt s'était progressivement écouté du script réel. Ramener le prompt au rôle qui lui convient (orchestration) et laisser la logique détaillée au script.
- **Pattern cohérent avec Phase 5 (PR #369)** : appliquer le même style de prompt "épuré" à toutes les phases pour uniformité. Phase 4 et Phase 5 suivent désormais le même modèle.
- **Heartbeat summary enrichi** : ajouter le nombre de coins skippés au summary (`{len(skipped)} skippés`) pour traçabilité dans les logs de phase.

## Impact sur l'architecture

Changement isolé — **aucun impact comportemental**. Le prompt s'exécute exactement comme avant (le script `phase4_sizing.py` est inchangé). C'est une **clarification de documentation** : le prompt reflète désormais ce qu'il fait réellement (appeler le script) plutôt que de dupliquer la logique que le script implémente.

**Observable dans les logs** : aucun changement. Les rapports Phase 4 et les heartbeats sont identiques.

## Références CLAUDE.md respectées

- **Minimalisme** : suppression de 56 lignes de pseudo-code redondant. Aucune nouvelle logique, aucun code spéculatif.
- **Modifications chirurgicales** : `phase4_sizing.txt` uniquement modifié ; aucun autre fichier touché.
- **Documentation = source de vérité du code** : le prompt documente maintenant ce que le code fait réellement.

## Notes

Ticket #364 (PR #369) avait appliqué un pattern similaire sur Phase 5. Cette PR étend le pattern à Phase 4, pour une documentation de prompts cohérente et fiable dans l'ensemble des 9 phases.

