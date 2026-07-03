# PR #312 — [M1] Refactorer Phase 1 — univers depuis Kraken USDC + seuil 1M

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-311-refactorer-phase1-univers-kraken-usdc`
> **Issues** : #311

## Contexte

Phase 1 du workflow de trading (scan de marché) refactorisée pour :
1. Redéfinir l'**univers de candidats** : source depuis les paires USDC réellement disponibles sur **Kraken** (via `kraken pairs`) au lieu de listes TradingView/Binance
2. **Baisser le seuil volume** de 5M à **1M USDC** (configurable) pour augmenter le nombre de candidats tradables
3. Garantir un **fallback sur portfolio_coins** (XBT, XRP, SOL) même si leur volume 24h tombe sous le seuil

Cette refacto aligne la sélection d'univers avec la réalité de la liquidité Kraken et réduit le risque d'ignorer des opportunités en alt-coins de taille moyenne.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase1_scan.py` | Réécriture majeure | Univers désormais depuis Kraken; appels ticker par batch; filtre volume dynamique |
| `config.json` | Ajout clé | Paramètre `min_volume_usdc` (défaut 1M) pour la souplesse |
| `prompts/phases/phase1_scan.txt` | Mise à jour docs | Explique le nouveau flux Phase 1 et le rôle du `tv_symbol` mapping |
| `prompts/phases/phase2_analysis.txt` | Ajustement mineur | Clarifie que screeners TradingView enrichissent mais ne définissent plus l'univers |
| `state/cycle_log.jsonl` | Sync de la démo | Exemple d'un cycle après refacto (4 coins tradables) |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `phase1_scan.py` (module entier) | Réécriture | Récupère univers via `kraken pairs -o json`, calcule volumes 24h par batch de 10 paires, filtre par seuil ou inclut portfolio_coins |

## Décisions techniques notables

- **Source Kraken au lieu de TradingView/Binance** : Kraken est le vrai broker; c'est sa disponibilité et sa liquidité qui font la réalité tradable. Les screeners TradingView deviennent des **enrichisseurs de signal** (top gainers, volume breakouts) sur l'univers déjà validé.

- **Batch ticker par 10 paires** : Réduit le nombre d'appels `kraken ticker` (coûteux/lent) et évite les timeouts. Exemple : 50 paires USDC = 5 appels au lieu de 50.

- **Mapping Kraken → TradingView explicite** : Via la variable `TV_MAP` (XBT→BTC, XDG→DOGE). Chaque entrée tradable inclut à la fois `coin` (Kraken) et `tv_symbol` (TradingView) pour Phase 2.

- **portfolio_coins comme fallback non négociable** : Même si XRP (volume 0.68M) ou SOL (1.29M) tombent juste sous le seuil 1M, ils restent candidats pour préserver les positions existantes. Contrôlé par la ligne `if vol >= MIN_VOLUME_USDC or coin in portfolio_coins`.

- **min_volume_usdc configurable** : Permet d'ajuster le seuil (1M par défaut) sans toucher au code Python — idéal pour tester différentes stratégies (e.g., 500k pour plus de diversité, 2M pour du blue-chip).

## Impact sur l'architecture

**Impact significatif sur Phase 1 → Phase 2** :
- Auparavant : univers défini par TradingView/config → Phase 1 faisait juste la validation Binance
- Maintenant : univers défini par Kraken **au cœur de Phase 1** → screeners TradingView enrichissent mais ne définissent plus le flux

**Flux modifié** :
```
Phase 1 (ancien) : config → TradingView screeners → Binance validation → univers
Phase 1 (nouveau) : Kraken pairs → volume filter (1M) → portfolio_coins fallback → univers
                     ↓
               Phase 2 : enrichissement TradingView (4h/1D) + screeners top gainers
```

**Impact sur les données** :
- Fichier `/tmp/cycle_{CYCLE_ID}_phase1_output.json` : structure inchangée, mais contenu réfléchit Kraken (ex: 4 coins au lieu de 15)
- Variables Phase 2 : les screeners `top_gainers_symbols` et `breakout_symbols` ne définissent plus l'univers; un coin peut être candidat même s'absent des screeners

**Impact CPU/temps** :
- **Réduction** : moins de paires à analyser (Kraken USDC ≈ 10-20 paires vs TradingView dynamique)
- **Réseau** : ~5-8 appels `kraken ticker` au lieu de 1-2 appels TradingView screeners

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : Préservée dans phase1_scan.py ligne 18 — `os.path.dirname(os.path.dirname(...))` reste rotatif sans dépendre de chemins hardcodés Mac/VPS.

- **Règle 3 (Modifications via binance-dev)** : Cette PR a suivi le workflow standard — issue #311 → board "Binance Bot Agent" → branche `feat/issue-311-*` → PR → merge.

- **Règle 6 (UTC interne)** : Pas de changement horaire dans cette PR; les volumes 24h sont intrinsèquement en UTC (Kraken les reporte en 24h depuis minuit UTC).

- **Règle 7 (Auto-scheduler dans main_loop)** : Phase 1 est appelée par `run_trade_workflow()` via le scheduler — aucune modification du scheduler lui-même.

- **Contrainte : pas de dépendances lourdes** : Utilise uniquement `json`, `subprocess` (pour `kraken` CLI), et `os` — aucune dépendance supplémentaire ajoutée.

- **IPv6 / curl uniquement pour Telegram** : Phase 1 n'envoie pas directement de notifications; appels Kraken via le CLI `kraken` (binaire local), pas de réseau cru — compatible.

