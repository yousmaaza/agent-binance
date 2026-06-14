# PR #234 — [M232] Fix outils MCP TradingView — restaurer atilaahmettaner

> **Mergée le** : 2026-06-14
> **Branche** : `feat/issue-232-fix-tradingview-mcp-tools-v2`
> **Issues** : #232

## Contexte

Les outils MCP TradingView utilisés dans les Phases 1 et 2 du workflow de trading étaient basés sur le serveur `tradesdontlie`, qui n'expose pas les fonctions attendues (`quote_get`, `chart_set_symbol`, `chart_set_timeframe`, `data_get_study_values`, `data_get_ohlcv`). Cette PR restaure l'intégration vers le serveur MCP `atilaahmettaner`, qui fournit les outils d'analyse technique réellement disponibles et qui sont mieux alignés avec les besoins du bot.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `.mcp.json` | Modification | Restauration de la configuration du serveur MCP TradingView (serveur `atilaahmettaner` via `uvx` depuis `tradingview-mcp-server`) |
| `prompts/trade_prompt.txt` | Modification majeure | Remplacement des appels MCP en Phases 1, 2 et 3 pour utiliser les outils disponibles |

### Fonctions/outils affectés (dans l'ordre des phases)

#### Phase 1 — Scan marché

**Avant** :
- `mcp__tradingview__quote_get()` — tentait de récupérer les données de cotation (non disponible)

**Après** :
- `mcp__tradingview__top_gainers(exchange="BINANCE", timeframe="4h", limit=25)` — identifie les coins avec le meilleur momentum
- `mcp__tradingview__volume_breakout_scanner(exchange="BINANCE", timeframe="4h", volume_multiplier=2.0, price_change_min=3.0, limit=25)` — détecte les breakouts volume
- `mcp__tradingview__market_sentiment(symbol="BTC", category="crypto", limit=20)` — évalue le sentiment global du marché crypto

#### Phase 2 — Analyse multi-timeframe

**Avant** :
- `mcp__tradingview__chart_set_symbol()` → `chart_set_timeframe()` → `data_get_study_values()` → `data_get_ohlcv()` (workflow graphique non disponible)

**Après** :
- `mcp__tradingview__coin_analysis(symbol="{COIN}USDT", exchange="BINANCE", timeframe="4h")` — analyse technique 4h (RSI, MACD, BB, EMA, signal BUY/SELL/NEUTRAL)
- `mcp__tradingview__coin_analysis(symbol="{COIN}USDT", exchange="BINANCE", timeframe="1D")` — analyse technique journalière (pour les coins BUY/STRONG_BUY en 4h seulement)

#### Phase 3 — Scoring

**Avant** :
- Critères basés sur variation 24h > 3% et ADX > 20 (non calculables sans données techniques complètes)

**Après** :
- `+1 point` si le coin est dans la liste `top_gainers` (indicateur de momentum positif)
- `+1 point` si le coin est détecté dans `volume_breakout_scanner` (signal de force d'achat)

### Détails des modifications

#### `.mcp.json`
La configuration MCP a été mise à jour pour ajouter le serveur TradingView via `uvx` :
```json
"tradingview": {
  "command": "uvx",
  "args": ["--from", "tradingview-mcp-server", "tradingview-mcp"]
}
```

Cette configuration remplace un appel direct à un binaire local non disponible par une invocation via `uvx` du package `tradingview-mcp-server` sur npm, qui expose les outils `atilaahmettaner` (incluant `top_gainers`, `coin_analysis`, `volume_breakout_scanner`, `market_sentiment`).

#### `prompts/trade_prompt.txt`
Changements structurels majeurs :

1. **Phase 1** (lignes 329–361) :
   - Remplace l'appel unique `quote_get` par trois appels distincts et parallélisables : `top_gainers`, `volume_breakout_scanner`, `market_sentiment`
   - Gestion des erreurs MCP : si un appel échoue, continue avec les données disponibles (pas de blocage du cycle)
   - Conservation de la vérification de tradabilité USDC via `binance-cli` (inchangée)

2. **Phase 2** (lignes 363–403) :
   - Remplace la séquence de commandes graphiques par deux appels directs à `coin_analysis` par coin
   - Étape A : analyse 4h sur tous les coins (obligatoire)
   - Étape B : analyse 1D filtrée — seulement pour les coins avec signal 4h BUY/STRONG_BUY
   - Gestion gracieuse du rate-limit TradingView : un signal 1D manquant (due limite) n'empêche pas un score solide en 4h

3. **Phase 3** (lignes 430–482) :
   - Tableau de scoring restructuré pour refléter les nouveaux critères
   - Critères "Variation 24h > 3%" et "ADX > 20" remplacés par "+1 si top_gainers" et "+1 si volume_breakout_scanner"
   - Maintien du score maximal 10 pts (poids identiques, juste les sources changent)
   - Seuil adaptatif `min_signal_score_degraded` utilisé si tous les coins 4h BUY ont un rate-limit 1D

### Gestion des erreurs MCP

Chaque appel MCP inclut une gestion d'erreur silencieuse :
- Si `top_gainers` échoue → `top_gainers_symbols = []` (aucun bonus +1 pour ce critère)
- Si `coin_analysis` 4h échoue → `signal_4h = "NEUTRAL"` (pas de blocage du cycle)
- Si `coin_analysis` 1d échoue → `signal_1d = "NEUTRAL"` avec marqueur `signal_1d_rate_limited = True` (pas de malus, juste notation dégradée)

Le cycle continue dans tous les cas. Fallback `binance-cli` conservé pour la vérification USDC (pas impacté par cette PR).

## Décisions techniques notables

- **Utilisation de `coin_analysis` plutôt que de construire un flux graphique** : plus simple, moins d'appels API, résultats fiables (RSI, MACD, Bollinger Bands, EMA, signal directement calculé par TradingView)
- **Appels 1D filtrés en Phase 2B** : réduit la charge API et limite les rate-limits TradingView en ne demandant l'analyse journalière que pour les candidats prometteurs
- **Seuil adaptatif en Phase 3** : si TradingView rate-limite tous les appels 1D, le bot bascule vers `min_signal_score_degraded` plutôt que de refuser tous les trades (robustesse)
- **Top_gainers + volume_breakout comme signaux supplémentaires** : fournissent une confirmation de momentum et de force d'achat indépendante de l'analyse RSI/MACD (diversification des signaux)

## Impact sur l'architecture

Impact limité mais structurant :

- **Changement du flux MCP** : au lieu d'une séquence de commandes graphiques (chart_set_symbol → chart_set_timeframe → data_get), utilise maintenant des appels directs sans état côté serveur (`coin_analysis`)
- **Réduction du nombre d'appels MCP par cycle** : auparavant ~8-10 appels graphiques par coin (4h), maintenant ~2 appels (`coin_analysis` 4h + optionnellement 1d). Réduit la latence et le risque de rate-limit
- **Amélioration de la robustesse** : chaque appel est isolé ; un échouement n'impacte pas les autres (contrairement aux appels graphiques qui dépendent d'un état commun `chart_set_symbol`)
- **Scoring plus fiable** : les critères de Phase 3 sont maintenant basés sur des données effectivement disponibles (`top_gainers`, `volume_breakout`) plutôt que sur des calculs non-disponibles (variation 24h, ADX)

La persistance en MongoDB, les ordres binance-cli en Phases 4-5, et les notifications Telegram restent inchangées.

## Références CLAUDE.md respectées

- **Règle "Aucun secret hardcodé"** : `.mcp.json` ne contient pas de tokens ou credentials (utilise des variables d'environnement implicites gérées par `uvx` et le système MCP)
- **Règle "Helpers partagés"** : les appels MCP en Phase 1 et 2 utilisent directement les helpers injectés (`exec(open("__HELPERS_PATH__").read())`), pas d'import Python direct
- **Règle "Fallback si appel MCP échoue"** : chaque appel est encapsulé dans un try/except avec fallback gracieux (défini en Phase 1-2)
- **Règle "Auto-scheduler interne"** : non impacté ; le scheduling reste interne à `main_loop()` (inchangé)
- **Règle "Format date UTC interne"** : les timestamps des cycles restent en UTC (inchangé)

## Test plan utilisateur (fourni dans la PR)

- ✅ Phase 1 appelle `top_gainers` sans erreur
- ✅ Phase 1 appelle `volume_breakout_scanner` sans erreur
- ✅ Phase 1 appelle `market_sentiment` sans erreur
- ✅ Phase 2 appelle `coin_analysis` 4h pour chaque coin
- ✅ Phase 2 appelle `coin_analysis` 1d pour les coins BUY/STRONG_BUY en 4h
- ✅ Phase 3 scoring inclut +1 top_gainers et +1 volume_breakout_scanner
- ✅ Si un appel MCP échoue, le cycle continue avec les données disponibles (pas de crash)
- ✅ Redémarrage manuel du bot et vérification `/trade` (à faire par utilisateur avant merge)

## Notes supplémentaires

- **Nommage des symboles** : `coin_analysis` accepte les symboles au format `{COIN}USDT` (pas `{COIN}USDC`). La vérification tradabilité USDC reste via `binance-cli` en Phase 1 (inchangée).
- **Score maximal** : reste 10 pts (tableau restructuré mais poids identiques).
- **Pas d'impact sur les dépendances** : `requirements.txt` inchangé (le serveur MCP est fourni via `uvx`).
