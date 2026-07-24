# Tests d'intégration pour les phases de trading

## Contexte et problème

Le bot exécute un cycle de trading en 9 étapes (Phase 0 à 8), orchestrées par Claude à l'exécution mais dont la majorité de la logique (scan, scoring, sizing, persistance) vit dans des scripts Python déterministes sous `binance-bot/core/phases/`. Aujourd'hui, `tests/` ne contient que 2 fichiers de tests unitaires très ciblés (`test_reward_risk_ratio_default.py`, `test_phase0_trailing_stop.py`), et **aucun test ne tourne automatiquement en CI**. Une évolution du code (config, scoring, sizing) peut donc casser silencieusement le comportement du bot sans qu'aucun signal n'apparaisse avant qu'un cycle réel échoue en production.

## Objectif

Ajouter des tests d'intégration couvrant les scripts de phases et le routing des commandes Telegram (`webhook_server.py`), exécutés automatiquement en CI sur chaque PR — sans jamais appeler la vraie API Kraken ni risquer un trade réel.

## Cas particulier : Phase 5 (exécution)

**Constat** : contrairement aux autres phases, `phase5_execution.py` ne contient aujourd'hui aucune logique — c'est Claude qui exécute directement les appels `kraken` en bash (re-fetch prix, check drift, BUY MARKET, query du fill, recalcul TP/SL, pose du stop-loss), décrits dans `prompts/phases/phase5_execution.txt`. Le script Python n'est appelé qu'à la toute fin, pour enregistrer le résultat.

**Décision** : refactorer `phase5_execution.py` pour qu'il contienne la logique complète (actuellement dans le prompt), à l'identique des garde-fous existants :
- Skip `TYPE_C` si drift prix > `price_deviation_max_pct`
- Skip `TYPE_C` si solde USDC insuffisant au moment de l'exécution
- BUY MARKET, query du fill (jusqu'à 3 tentatives)
- Si le prix a déjà dépassé le TP au moment du fill → clôture immédiate au marché (`close_reason: "market_above_tp_at_fill"`)
- Sinon, pose du stop-loss ; si la pose échoue → `protection_failed: true` + notification Telegram (position non protégée)

Claude passe d'un rôle d'exécutant à un rôle d'orchestrateur pour cette phase, exactement comme pour les phases 1/3/4/6/7/8 : écrire l'input JSON (liste `ordres_prepares` de la Phase 4), appeler le script, lire l'output.

**Bénéfice secondaire** (pas l'objectif premier, mais réel) : réduit la marge d'improvisation de Claude sur la partie la plus sensible du cycle (placement d'ordres réels) — remplacée par du code testé et revu.

**Hors périmètre de ce refactor** : aucun changement de la logique métier elle-même (seuils, formules de calcul de stop/TP) — uniquement un déplacement de "prompt" vers "script", comportement identique.

## Harness de test — faux `kraken-cli`

Un stub (`tests/fixtures/fake_kraken.py`, exécutable) imitant les sous-commandes utilisées par le bot (`ticker`, `balance`, `order buy`, `order sell`, `query-orders`, `pairs`). Piloté par un fichier de scénario JSON dont le chemin est lu depuis une variable d'environnement (`FAKE_KRAKEN_SCENARIO`) :

```json
{
  "ticker": {"ETHUSDC": {"c": ["1900.0", "0.01"]}},
  "balance": {"USDC": "500.0", "ETH": "0.0"},
  "order_buy_ETHUSDC": {"txid": ["TXID123"]},
  "query-orders_TXID123": {"TXID123": {"status": "closed", "cost": "190.0", "vol_exec": "0.1"}}
}
```

Chaque test écrit son propre scénario (fichier temporaire), lance `KRAKEN_CLI_PATH=tests/fixtures/fake_kraken.py`, puis appelle le script de phase réel et vérifie son output JSON / les side-effects (ex: `trade_history.json`, `tg()` appelé — `tg()` lui-même utilise `curl`, donc mocké séparément via `unittest.mock.patch` sur `subprocess.run` ciblé, pour ne jamais taper l'API Telegram réelle pendant les tests).

Framework : **`unittest`** (stdlib), cohérent avec les 2 tests existants — pas de nouvelle dépendance (`pytest` non introduit).

**Convention de nommage** : un fichier de test par script de phase, nommé `tests/test_<nom_du_module>.py` (ex: `tests/test_phase3_scoring.py`, `tests/test_phase5_execution.py`) — plus explicite que les 2 fichiers historiques (`test_reward_risk_ratio_default.py`), pas de renommage de l'existant nécessaire.

## Couverture de tests visée

| Phase / module | Cas testés |
|---|---|
| `phase1_scan.py` | Filtre volume (`min_volume_usdc`), `portfolio_coins` toujours inclus même sous le seuil, mapping Kraken→TradingView (`XBT→BTC`) |
| `phase3_scoring.py` | Formule de score (chaque critère +N points), seuil `min_signal_score`, mode dégradé (`min_signal_score_degraded`), exigence `signal_4h` BUY/STRONG_BUY en plus du score, `max_open_positions`, `max_correlated_positions`, décision SELL (score ≤ 3 + en portefeuille) |
| `phase4_sizing.py` | Calcul stop (`atr_stop_multiplier`), calcul TP (`reward_risk_ratio`), filtre `min_order_usdc`/`ordermin`/`costmin`, arrondi lot/step |
| `phase5_execution.py` (post-refactor) | Skip `TYPE_C` drift, skip `TYPE_C` solde insuffisant, BUY+SL réussi, clôture immédiate si prix > TP au fill, `protection_failed` si la pose du SL échoue |
| `phase0_*.py` (snapshot, profit, trailing_stop, oco_retry) | Clôture auto si profit > `min_profit_pct_take`, recalcul trailing stop, retry OCO |
| `phase6_next_cycle.py` | Calcul du prochain slot 4h UTC |
| `phase7_mongo.py` / `phase7_hb_check.py` | Détection de heartbeats manquants (le client MongoDB lui-même est mocké — pas de vraie connexion Atlas en test) |
| `phase8_cycle_log.py` | Append JSONL, rotation à 90 lignes (le `git commit`/`push` interne n'est pas exécuté en test — mocké) |
| `webhook_server.py` | Routing `/status`, `/trade`, `/perf`, `/reset`, commande inconnue — sans invoquer le vrai CLI `claude` (subprocess mocké) |

## CI

Nouveau `.github/workflows/tests.yml` : sur chaque PR (`pull_request: [opened, synchronize, reopened]`), installe Python 3.11 + `requirements.txt`, lance `python -m unittest discover tests/ -v`. Rapide (aucun appel réseau réel), gratuit (runner GitHub-hosted standard).

## Découpage en tickets (ordre d'implémentation)

1. **Refactorer Phase 5** en script déterministe (bloque tout le reste — priorité la plus haute)
2. **Harness de test** : stub `fake_kraken.py` + conventions `tests/` + workflow CI + tests de démonstration sur `phase3_scoring.py`
3. **Tests phases 0/1** (snapshot, profit, trailing stop, OCO retry, scan univers)
4. **Tests phases 4/5** (sizing, exécution — une fois la Phase 5 refactorée)
5. **Tests phases 6/7/8 + routing `webhook_server.py`**

Chaque ticket est implémenté via le workflow standard (`binance-dev`, branche → PR → review), un ticket par invocation, dans l'ordre ci-dessus (le ticket 2 dépend du 1, les tickets 3-5 dépendent du 2).

## Hors périmètre

- Aucun test ne fait de vrai appel réseau (ni Kraken, ni Telegram, ni MongoDB Atlas, ni TradingView MCP) — tout est simulé.
- `kraken paper` (mode paper-trading intégré à `kraken-cli`) n'est pas utilisé dans la suite de tests automatisée — documenté comme option de validation manuelle/staging sûre si besoin plus tard (hors scope ici).
- Aucune modification de la logique métier (seuils, formules) — uniquement l'ajout de tests et le déplacement Phase 5 prompt→script à comportement identique.
- Le raisonnement de Claude lui-même (quels outils appeler, dans quel ordre) n'est pas testable de façon déterministe et reste hors périmètre.
