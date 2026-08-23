# PR #414 — Filtrer la liquidité sur le spread et sa persistance, pas un instantané

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-407-filtre-liquidite`
> **Issues** : #407

## Contexte

L'incident TRUMP du 22-23/08/2026 a révélé un risque systémique dans le filtre de liquidité de la Phase 1 : un pic isolé de volume (+27x en une nuit) pouvait faire entrer un coin dans l'univers tradable, même si ce volume s'accompagnait d'un spread extrêmement dégradé (0,126% — 12x plus large que XBT/SOL à 0,006-0,011%). À l'exécution des ordres, le stop-loss a glissé de 2,3 points au-dessus du prix d'entrée prévu (Phase 5), transformant un risque théorique de 1% en risque réel de 3,3%.

Symptôme identifié : le filtre volume seul (`volume_24h >= MIN_VOLUME_USDC`) capture les pics instantanés, pas le volume soutenu. Correction : ajouter deux couches à la Phase 1 :
1. **Filtre spread** : exclure les paires avec un écartement ask/bid trop large (indicateur précoce de liquidité dégradée, coûteux à l'exécution)
2. **Filtre de persistance du volume** : vérifier que le volume tient sur plusieurs périodes consécutives (4h), écartant les pics isolés

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase1_scan.py` | Modification | Ajout du filtre spread (extraction ask/bid, calcul %), ajout du filtre persistance (appel `ohlc` sur candidats filtrés) |
| `config.json` | Ajout | Deux nouveaux paramètres : `max_spread_pct` (0.0008 = 0,08%) et `volume_persistence_periods` (6) |
| `prompts/phases/phase1_scan.txt` | Modification | Mise à jour de la description du prompt Phase 1 pour documenter les nouveaux filtres |
| `tests/fixtures/fake_kraken.py` | Refactoring | Ajout support commande `ohlc`, refactoring en dispatch dict pour maintenabilité |
| `tests/test_phase1_scan.py` | Modification | 2 nouveaux tests (`TestSpreadFilter`, `TestVolumePersistenceFilter`), 3 tests existants adaptés aux champs ticker `a`/`b` et scénarios `ohlc` |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| `phase1_scan.py:_volume_is_persistent()` | Ajoutée | Nouvelle fonction utilitaire : appelle `kraken ohlc` sur une paire donnée, récupère les 6 dernières périodes 4h, calcule un seuil de volume par période (MIN_VOLUME / PERSISTENCE_PERIODS), compte combien de périodes tiennent ce seuil. Retourne `True` si ≥ 4 périodes sur 6 tiennent le seuil (majorité). Appelée uniquement sur les candidats ayant déjà passé le filtre volume + spread pour économiser les appels réseau. |
| `phase1_scan.py:main loop` | Modifiée | Étape 2 (ticker) : extraction des champs `a` (ask) et `b` (bid) en plus de prix/volume ; calcul `spread_pct = (ask - bid) / ask`. Étape 3 (filtrage) : logique d'inclusion réordonnée — portfolio_coins d'abord, puis volume, spread, puis persistance. Structure : `if coin in portfolio_coins: include` → `elif vol < min: skip` → `elif spread > max: skip` → `elif not persistent: skip` → `else: include` |

## Décisions techniques notables

- **Rejet du spread en tant qu'attribut calculé côté TradingView** : les données TradingView MCP ne fournissent pas le spread ask/bid brut, donc extraction locale depuis `kraken ticker` (déjà disponible). Une seule requête réseau supplémentaire par paire (multiplexée en batch).

- **Appel `ohlc` en deux étapes** : filtrer volume+spread d'abord (4h + batches ticker), puis appeler `ohlc` **uniquement** sur les paires qualifiées pour ne pas doubler le budget réseau. Sur le snapshot test (46 paires totales), cela réduit les appels `ohlc` de 46 à ~6 (candidats passant volume+spread).

- **Seuil `max_spread_pct = 0.0008` (0,08%)** : calibré empiriquement à partir de mesures sur Kraken le 23/08/2026. Ancien seuil 0,05% aurait exclu ADA (+10,57 USDC net, pièce la plus profitable de l'historique) pour un dépassement de 4 millièmes de pour-cent. Nouveau seuil 0,08% retient ADA, tout en excluant BNB, LINK, TRUMP (spread 2-3x plus large que les majors XBT/ETH/SOL/XRP). Réserve : le spread varie dans le temps ; ce seuil est un compromis, non une valeur empiriquement validée contre un scénario de stop-loss baissier.

- **Persistance comme majorité simple** : `PERSISTENCE_REQUIRED = VOLUME_PERSISTENCE_PERIODS // 2 + 1`, soit 4 sur 6. Assez strict pour écarter les pics (TRUMP : 1 seule période tenait le seuil), assez flexible pour tolérer une baisse temporaire ou un week-end (un jour manquant sur 6 reste acceptable).

- **Portfolio coins toujours inclus** : indépendamment du volume, spread ou persistance. Garantit une liquidité de repli pour les positions déjà ouvertes (XBT, XRP, SOL).

## Impact sur l'architecture

Changement isolé à la Phase 1 (entrée de l'univers tradable). Pas d'impact sur les phases 2-8 : les données enrichies (`spread_pct`) ne remontent pas hors de la Phase 1 ; les coins acceptés/rejetés convergent dans les mêmes structures tradable/non_tradable que précédemment. L'ordre de filtrage (volume → spread → persistance) est déterministe et documenté en Phase 1.

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : utilisation de `os.path.dirname()` pour calculer le chemin, valide sur Mac et VPS Linux. Aucun chemin hardcodé.

- **Règle 3 (Aucun secret hardcodé)** : les deux nouveaux paramètres (`max_spread_pct`, `volume_persistence_periods`) vivent dans `config.json`, pas en dur dans le code.

- **Règle 4 (Appels Kraken via subprocess)** : les appels `binance("ticker", ...)` et `binance("ohlc", ...)` restent des subprocess `kraken-cli`, wrapper déjà en place. Pas de changement aux appels réseau.

- **Minimalisme (CLAUDE.md préambule)** : seule modification du code existant nécessaire pour fixer le bug (filtre spread + persistance). Pas d'abstraction supplémentaire, pas de gestion d'erreur pour des scénarios impossibles (ex. absence complète de réponse ticker — loggée, pas retraitée).

## Tests

Couverture dans `tests/test_phase1_scan.py` (5 tests au total, 154 tests globaux OK) :

- `TestSpreadFilter` : vérifie qu'une paire avec spread > max_spread_pct est exclue (scénario TRUMP, LINK)
- `TestVolumePersistenceFilter` : vérifie qu'une paire avec pic isolé échoue la persistance (1 période sur 6 vs 4 requises)
- `TestPortfolioCoinsAlwaysIncluded` : vérifie que XBT, XRP, SOL sont inclus même avec volume très bas ou spread très large
- Tests existants (mapping TV, filtres volume, commandes) : mis à jour pour les champs ticker `a`/`b` et scénarios `ohlc`

Validation syntaxe Python : `python -c "import ast; ast.parse(open('binance-bot/core/phases/phase1_scan.py').read())"` → OK.
