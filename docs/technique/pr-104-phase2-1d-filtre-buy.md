# PR #104 — Optimiser Phase 2 : appel 1D filtré sur candidats 4h BUY

> **Mergée le** : 2026-05-24  
> **Branche** : `feat/issue-103-phase2-1d-filtre-buy`  
> **Issues** : #103

## Contexte

Phase 2 du prompt de trading exécutait **en parallèle** une analyse 4h sur l'univers complet ET une analyse 1D sur les mêmes coins, sans discriminant. Cela générait un nombre important d'appels TradingView MCP inutiles (exemple : ~14 appels 1D par cycle pour des coins sans signal 4h positif). 

La PR #103 demande une optimisation : filtrer avant d'appeler l'analyse 1D, en ne conservant que les coins avec un signal 4h haussier (BUY ou STRONG_BUY). Réduction attendue : ~14 appels → ~8–10 appels par cycle typique.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Modification | Phase 2 restructurée en 3 étapes séquentielles (A/B/C) au lieu d'un unique bloc |

### Fonctions touchées dans le prompt

| Phase | Action | Description |
|---|---|---|
| Phase 2 — Analyse multi-timeframe | Modifiée | Scission en 3 étapes : Étape A (analyse 4h parallèle), Étape B (filtrage BUY 4h), Étape C (analyse 1D filtrée) |

### Détails du changement — Lignes 301–320 de `trade_prompt.txt`

**Avant** : Un bloc unique parallèle qui lançait coin_analysis 4h et 1d simultanément sur l'univers complet.

**Après** : 
```
Étape A — Analyse 4h pour TOUS les candidats (en parallèle)
  Pour chaque coin : mcp__tradingview__coin_analysis(..., timeframe: 4h)
  Mémorise : recommendation (signal_4h) et rsi

Étape B — Filtrage BUY
  Identifie coins avec signal_4h = BUY ou STRONG_BUY → liste coins_buy_4h
  Autres coins : signal_1d = "NEUTRAL" par défaut (contributeur zéro au scoring Phase 3)

Étape C — Analyse 1D uniquement pour coins_buy_4h
  Si coins_buy_4h vide : passer directement au scoring (0 appel 1D)
  Sinon : pour chaque coin de coins_buy_4h, en parallèle :
    mcp__tradingview__coin_analysis(..., timeframe: 1d)
```

## Décisions techniques notables

- **Filtrage conservateur** : Un signal NEUTRAL, SELL, ou STRONG_SELL en 4h n'entraîne aucun appel 1D, économisant directement la moitié ou plus des appels TradingView. Les coins hors filtre reçoivent automatiquement `signal_1d = "NEUTRAL"`, qui est neutre pour le scoring Phase 3 (contribue 0 point).
  
- **Pas d'impact sur le scoring Phase 3** : Les coins sans analyse 1D ont le même comportement que s'ils avaient été analysés et jugés NEUTRAL — compatible avec la règle de scoring qui donne +2 points pour un signal 1d BUY/STRONG_BUY et 0 pour NEUTRAL.

- **Robustesse du cas zéro appel 1D** : Si aucun coin ne passe le filtre BUY 4h (cas rare), la Phase 2 se termine proprement avec 0 appel 1D et passe directement au scoring. Aucun appel dummy ni fallback nécessaire.

## Impact sur l'architecture

Changement isolé à la Phase 2 du prompt. Aucun impact sur :
- Les phases 0–1 (vérifications, scan marché) et phases 3–7 (scoring, ordres, exécution) — inchangées
- L'interface Telegram — le message de fin Phase 2 inclut désormais les deux compteurs : "N coins analysés 4h, M coins analysés 1D (filtrés BUY)"
- La structure `trade_history.json` et `state/` — aucune modification
- Les constantes `config.json` — aucun nouveau paramètre

**Réduction TradingView estimée** : Univers typique 7 coins, 2–3 coins BUY en 4h → Avant : 14 appels (7×4h + 7×1d), Après : ~9 appels (7×4h + 2–3×1d).

## Références CLAUDE.md respectées

- **Règle 4** (stdout/stderr toujours sauvegardés) : Inchangé — les logs de Phase 2 continueront à être écrits dans `logs/stdout/cycle_*.log`
- **Règle 5** (UTC interne, local à l'affichage) : Inchangé — les timestamps restent en UTC
- Pas de secrets hardcodés, pas de dépendance nouvelle, pas de modification de `webhook_server.py`
