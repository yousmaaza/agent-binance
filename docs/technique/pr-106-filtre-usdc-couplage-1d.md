# PR #106 — Phase 1 filtre USDC non tradables + Phase 2 appels 1D couplés par coin

> **Mergée le** : 2026-05-25
> **Branche** : `feat/issue-105-filtre-usdc-1d-sequentiel`
> **Issues** : #105

## Contexte

L'optimisation Phase 2 précédente (#104) filtrait les appels TradingView 1D sur les seuls candidats BUY 4h, réduisant le nombre total d'appels. Cependant, deux problèmes subsistaient :

1. **Coins non tradables sur Binance** : Certains coins (STEEM, PEOPLE) passaient les screeners TradingView mais n'avaient pas de paire USDC valide sur Binance spot, provoquant des appels inutiles à TradingView et des erreurs de parsing 1D (`Expecting value: line 1 column 1`).

2. **Paralléllisation inefficace Phase 2** : Les 14 appels 4h se faisaient en parallèle global, puis les 9 appels 1D en batch séparé. Cela n'exploitait pas l'opportunité d'étendre l'appel 1D immédiatement après un résultat 4h BUY (sans attendre tous les 4h).

Cette PR corrige ces deux inefficacités via :
- **Phase 1** : filtre tradabilité explicite (vérification paire USDC via `binance-cli spot ticker-price`)
- **Phase 2** : regroupement 4-5 coins et appels 1D couplés coin par coin (après chaque résultat 4h BUY)

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Modification | Prompts Phase 1 et Phase 2 refactorisés |

### Phase 1 — Tradability check

**Ajout (lignes 298–303)** : nouvelle section "Vérification de tradabilité USDC"

Après avoir construit l'univers initial de candidats (union des screeners + portfolio_coins), pour **chaque coin candidat** :

```bash
binance-cli spot ticker-price --symbol {COIN}USDC --profile agent-profile
```

- ✓ Si le prix est retourné ET volume 24h ≥ 5M USDC → coin tradable
- ✗ Si la commande échoue ou le symbole est introuvable → coin non tradable

**Filtre définitif** : éliminer immédiatement tous les coins marqués ✗. Seuls les coins ✓ passent à la Phase 2. Cela évite les appels TradingView inutiles et les erreurs de parsing 1D.

### Phase 2 — Regroupement et couplage 1D

**Refactorisation majeure (lignes 308–337)** : remplacement de la stratégie "batch global 4h + batch séparé 1d" par une stratégie "groupes de 4 coins couplés".

#### Avant (PR #104) :
```
14 appels coin_analysis 4h en parallèle global
 ↓
Filtrer sur les résultats BUY 4h
 ↓
9 appels coin_analysis 1d en batch séparé (après)
```

#### Après (PR #106) :
```
Univers découpé en groupes de 4 coins maximum

Groupe 1 (4 coins) :
  ├─ 4 appels 4h en parallèle intra-groupe
  └─ Immédiatement après résultats 4h :
     └─ appels 1d en parallèle pour les BUY/STRONG_BUY du groupe

Groupe 2 (4 coins) : [même pattern]
...
Groupe N (≤4 coins) : [même pattern]
```

**Règles du nouveau pattern** :

1. Max 4–5 appels `coin_analysis` **simultanés** (toutes timeframes confondues) pour respecter le rate limit TradingView.
2. Pour chaque groupe :
   - **Étape A** : 4h en parallèle
   - **Étape B** : dès qu'un résultat 4h revient, si signal = BUY/STRONG_BUY, lancer l'appel 1d immédiatement (en parallèle avec les autres appels 1d du groupe)
3. Coins avec signal_4h = NEUTRAL/SELL/STRONG_SELL : signal_1d = "NEUTRAL" (pas d'appel 1d).
4. Si un appel 1D échoue : signal_1d = "NEUTRAL", coin **non éliminé** (continuer le scoring).

**Résultat** : réduction du nombre total d'appels TradingView + suppression des appels inutiles sur coins non tradables.

## Décisions techniques notables

- **Tradability check via `binance-cli`** : réutilise le mécanisme existant (déjà appelé en Phase 0 pour le portfolio). Pas de dépendance supplémentaire.
- **Rate limit respecté** : 4–5 appels max (vs. 14 parallèles auparavant) pour éviter les 429 de TradingView.
- **Graceful degradation 1D** : si un appel 1D échoue, l'agent ne supprime pas le coin mais assigne signal_1d = "NEUTRAL". Le scoring Phase 3 prendra en charge cette situation (coin peut toujours être candidat BUY si score ≥ 6).
- **Pas de changement aux phases suivantes** : Phase 3 (scoring), Phase 4 (sizing), Phase 5 (exécution), Phase 6–7 restent inchangées. La structure de données inter-phases (signal_4h, signal_1d, rsi) est stable.

## Impact sur l'architecture

L'implémentation de Phase 1 et Phase 2 n'affecte pas la communication entre les phases :
- Phase 1 alimente Phase 2 avec un univers réduit aux coins tradables sur Binance.
- Phase 2 retourne les mêmes champs (signal_4h, signal_1d, rsi, score) à Phase 3.
- Les phases suivantes (3–7) restent inchangées.

**Avantages** :
- Diminution du nombre d'appels TradingView (14 × 2 timeframes → ~8–12 au total selon les résultats 4h BUY).
- Élimination des erreurs de parsing 1D liées aux coins non tradables.
- Meilleure observabilité : le nombre réel d'appels 1D (coins_1d_count) est explicité dans la notification Phase 2.

## Références CLAUDE.md respectées

- **Règle 1 (Telegram via curl)** : Non applicable à cette PR (aucune modification réseau).
- **Règle 2 (Secrets via .env)** : Non applicable (aucun nouveau secret).
- **Règle 3 (PROJECT_DIR dynamique)** : Non applicable (pas de changement chemins).
- **Règle 4 (Logs stdout/stderr)** : Respecté — aucune suppression de capture.
- **Règle 5 (UTC interne)** : Non applicable à cette PR.
- **Règle 6 (Auto-scheduler dans main_loop)** : Non applicable (aucune modification scheduler).
- **Règle 7 (venv .venv)** : Non applicable (aucun changement dépendances).
- **Règle 8 (Workflow ticket → branche → PR)** : ✅ Respecté — issue #105, branche dédiée, PR avec target main.

**Tokens de substitution** : `__PROJECT_DIR__`, `__CHAT_ID__`, `__BOT_TOKEN__`, `__CYCLE_ID__`, `__PROMPT_VERSION__` intacts.
