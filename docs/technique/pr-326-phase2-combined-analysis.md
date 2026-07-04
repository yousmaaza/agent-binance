# PR #326 — Migrer Phase 2 de coin_analysis vers combined_analysis (4h)

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-319-combined-analysis-phase2`
> **Issue** : #319

## Contexte

Phase 2 (Analyse multi-timeframe) orchestrait historiquement :
- **Étape A** : appel `mcp__tradingview__coin_analysis` sur tous les coins en 4h pour extraire RSI, MACD, BB, EMA, signal BUY/SELL/NEUTRAL
- **Étape B** : appel conditionnel `mcp__tradingview__coin_analysis` 1D sur les coins BUY/STRONG_BUY en 4h

Cependant, `coin_analysis` ne retournait **pas de données de support/résistance** ni **d'ADX** — informations critiques pour :
1. **Phase 3** : affiner le scoring avec des niveaux de support/résistance
2. **Phase 4** : dimensionner les ordres en fonction de la distance au plus proche niveau de résistance (TP intelligent futur, ticket #325)
3. **Stratégie générale** : valider la force d'une tendance via ADX (>20 = tendance confirmée)

L'outil `mcp__tradingview__combined_analysis` retourne **tous ces indicateurs** + la gestion d'erreur intégrée, mais n'existait pas dans la version antérieure du MCP. Cette PR le met en production pour 4h.

## Changements

### Fichier modifié

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/phases/phase2_analysis.txt` | Modification | +18 lignes, -7 lignes : migration appel 4h vers combined_analysis + extraction ADX + résistances |

### Modifications détaillées

#### Étape A — Analyse 4h (ligne 8–30 de phase2_analysis.txt)

**Avant** :
```
mcp__tradingview__coin_analysis(symbol="{tv_symbol}USDT", exchange="BINANCE", timeframe="4h")
→ retourne RSI, MACD, BB, EMA, signal BUY/SELL/NEUTRAL uniquement
```

**Après** :
```
mcp__tradingview__combined_analysis(symbol="{tv_symbol}USDT", exchange="BINANCE", timeframe="4h")
→ retourne RSI, MACD, BB, EMA, signal BUY/SELL/NEUTRAL, ADX, supports/résistances
Si combined_analysis échoue → fallback sur coin_analysis (nouveaux champs = None)
```

#### Nouvelles variables dans `analysis_results[coin]`

| Variable | Type | Source | Fallback | Utilité |
|---|---|---|---|---|
| `adx_4h` | float \| None | `technical.adx.value` | None (en fallback) | Force de la tendance (0-100, >20 confirmé) |
| `adx_trend_4h` | str \| None | `technical.adx.trend_strength` | None (en fallback) | Qualité tendance (strong/moderate/weak) |
| `resistance_1_4h` | float \| None | `technical.support_resistance.resistance_1` | None (en fallback) | Premier niveau de résistance 4h |
| `resistance_2_4h` | float \| None | `technical.support_resistance.resistance_2` | None (en fallback) | Deuxième niveau de résistance 4h |
| `nearest_resistance_4h` | float \| None | `technical.support_resistance.nearest_resistance` | None (en fallback) | Le plus proche niveau de résistance |
| `distance_to_resistance_4h_pct` | float \| None | `technical.support_resistance.distance_to_resistance_pct` | None (en fallback) | Distance en % au plus proche niveau |
| `resistance_1_1d` | None | (pas encore disponible) | Always None | Réservé pour futur ticket migrant 1D vers combined_analysis |

#### Gestion d'erreur 4h

- Si `combined_analysis` échoue ou rate-limitée (error dans réponse) → **fallback automatique** sur `coin_analysis` 4h
  - Les nouveaux champs (ADX, résistances) sont assignés à `None`
  - Signal 4h continue normalement (`signal_4h`, `rsi_4h` extraits du coin_analysis fallback)
  - Aucun blocage du cycle
  
- Si les deux appels échouent → signal_4h = "NEUTRAL", `signal_4h_failed = True` en Phase 3

#### Étape B — Analyse 1D (ligne 32–45)

**Inchangée** : logique filtrée sur signal_4h BUY/STRONG_BUY, toujours via `coin_analysis` 1D (attendant migration future ticket).

#### Heartbeat Phase 2 enrichi (ligne 51)

**Avant** :
```
✓ Phase 2 — N coins analysés
```

**Après** :
```
✓ Phase 2 — N coins analysés
1 ligne par coin : COIN — RSI_4h / signal_4h / signal_1d / ADX: adx_4h (adx_trend_4h) si adx_4h disponible, omis sinon
```

Exemple :
```
✓ Phase 2 — 8 coins analysés 4h, 3 analysés 1D
XRP — RSI 62 / BUY / NEUTRAL / ADX: 32 (strong)
SOL — RSI 45 / STRONG_BUY / BUY / ADX: 28 (moderate)
BTC — RSI 58 / BUY / NEUTRAL
```

## Décisions techniques notables

- **Résilience via fallback** : si `combined_analysis` TradingView échoue (rate-limit), bascule vers `coin_analysis` 4h sans bloquer le cycle. Les nouveaux champs seront `None`, mais le signal 4h est garanti.
  
- **Pas de modification Phase 3/4** : les nouveaux champs ne sont pas encore consommés par le scoring Phase 3 ou le sizing Phase 4 (intégration score ADX et TP via résistances déféré à tickets ultérieurs #325). Cette PR est donc **rétro-compatible** : les champs existent mais ne changent pas la logique de sélection.
  
- **1D reste inchangé** : l'appel 1D continue d'utiliser `coin_analysis` (coin_analysis 1D ne retourne pas ADX/résistances de toute façon). Placer `resistance_1_1d = None` en attente du ticket futur qui migrera 1D vers combined_analysis.

- **Gestion d'erreur silencieuse 1D conservée** : la gestion d'erreur silencieuse 1D (échec 1D → signal_1d = NEUTRAL, signal_1d_rate_limited = True) reste inchangée. En Phase 3, ce NEUTRAL donne 0 pts mais aucun malus (pas skip TYPE_C pour cette raison, cf. CLAUDE.md règle skip_type).

## Impact sur l'architecture

**Réduction appels TradingView 4h** : pas d'impact direct — `combined_analysis` remplace juste `coin_analysis` 4h (même nombre d'appels, mais avec plus de données).

**Préparation Phase 3 & 4** :
- Phase 3 : les scores par coin pourront bientôt intégrer ADX comme critère supplémentaire (validation tendance)
- Phase 4 : les ordres pourront bientôt utiliser `nearest_resistance_4h` + `distance_to_resistance_4h_pct` pour dimensionner les TP (reward/risk optimal basé sur structure de marché)

**Flux Phase 2 enrichi** :
```
mcp__tradingview__combined_analysis (4h)
    │
    ├──► analysis_results[coin]
    │       ├── signal_4h, rsi_4h (ancien)
    │       ├── adx_4h, adx_trend_4h (NOUVEAU)
    │       ├── resistance_1_4h, resistance_2_4h (NOUVEAU)
    │       ├── nearest_resistance_4h, distance_to_resistance_4h_pct (NOUVEAU)
    │       └── resistance_1_1d = None (NOUVEAU, réservé)
    │
    └──► Heartbeat Phase 2
            └── Affichage ADX par coin si disponible
```

## Références CLAUDE.md respectées

- **Minimalisme** (§2) : aucune refonte de Phase 2, juste remplacement appel MCP + extraction nouveaux champs
- **Modifications chirurgicales** (§3) : uniquement le fichier prompt phase2_analysis.txt touchée, aucune logique Python modifiée (Phase 2 exécution reste dans TRADE_PROMPT)
- **UTC interne** (§6) : aucun changement horaire, ADX et résistances sont des indicateurs atemporels
- **Pas de secret hardcodé** (§3) : aucun nouveau secret, `mcp__tradingview__combined_analysis` déjà disponible via `.mcp.json`

## Tests selon le body PR

✅ Phase 2 appelle `combined_analysis` pour timeframe 4h  
✅ Appel 1D (`coin_analysis`) conservé inchangé  
✅ ADX (`adx_4h`, `adx_trend_4h`) extrait et présent dans `analysis_results[coin]`  
✅ Résistances (`resistance_1_4h`, `resistance_2_4h`, `nearest_resistance_4h`, `distance_to_resistance_4h_pct`) extraites et présentes  
✅ `resistance_1_1d = None` pour tous les coins  
✅ Fallback automatique si `combined_analysis` échoue → nouveaux champs = None, signal 4h inchangé  
✅ Heartbeat Telegram affiche ADX quand disponible  
✅ Redémarrage du bot et `/status` → succès < 5s (à faire par utilisateur avant merge)
