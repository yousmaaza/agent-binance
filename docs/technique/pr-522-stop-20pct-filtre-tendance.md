# PR #522 — Stop de départ à −20 % et filtre de tendance de fond (EMA100 1d)

> **Mergée le** : 2026-10-08
> **Branche** : `feat/issue-521-stop-20pct-filtre-tendance`
> **Issues** : #521

## Contexte

La stratégie antérieure plaçait des stops basés sur l'ATR (volatilité 4h) pondérée par un multiplicateur 2,5x, ce qui générait des stops très larges (6–8 % typique, jusqu'à 12+ % en marché volatile) et des positions trop petites en conséquence. Les résultats de rejeu sur 2022→2025 montraient une perte cumulée de −73,9 % à −96,1 % selon la fenêtre. 

Cette PR introduit deux améliorations majeures :
1. **Stop fixe à −20 %** : distance constante sous le prix d'entrée, indépendante de l'ATR. Permet des positions plus grandes à risque égal.
2. **Filtre de tendance de fond** : n'achète un coin que si sa clôture 1d ET celle de BTC se trouvent toutes deux au-dessus de l'EMA100 1d, en utilisant les bougies Kraken 1d (la bougie du jour en cours est exclue pour garantir que la clôture est figée).

La rejeu complet (Binance 4h, risque 2 %, capital 380 USDC, commission 0,9 %) montre une amélioration significative : perte réduite à −37,6 % sur 2025 (vs −90,9 %), quasi stable sur 3 mois (+0,0 %) et amélioration sur Kraken (−0,1 % palier intérieur vs −30,0 % actuel).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase3_scoring.py` | Modification majeure | Ajout du filtre de tendance de fond ; nouvelles clés config `trend_filter_enabled` et `trend_filter_ema_days` |
| `binance-bot/core/phases/phase4_sizing.py` | Modification majeure | Mode stop variable (`stop_mode: "fixed"` ou `"atr"`) ; `fixed_stop_pct` configurable ; plafond `max_stop_distance_pct` non appliqué en mode fixe |
| `binance-bot/core/trade_helpers.py` | Ajout fonctions | Nouvelle fonction `ema_last()` pour EMA(n) simple ; nouvelle fonction `fetch_daily_trend()` pour récupérer (clôture 1d, EMA100 1d) depuis Kraken |
| `config.json` | Ajout clés | 4 nouvelles clés : `stop_mode` (défaut `"fixed"`), `fixed_stop_pct` (défaut 0.20), `trend_filter_enabled` (défaut `true`), `trend_filter_ema_days` (défaut 100) |
| `scripts/stop_trend_replay.py` | Nouveau | Script complet de rejeu pour benchmark stop −20 % vs ATR, filtre seul vs combiné, et palier intermédiaire (grille 3×3) sur Binance 4h et Kraken 4h |
| `docs/strategie.html` | Modification | Mise à jour des phases 3/4/5 avec les nouvelles méchaniques ; section 08/10 : grille complète du palier intermédiaire (X, Y) |
| `docs/strategie.md` | Régénéré | Depuis `docs/strategie.html` via `scripts/strategie_to_md.py` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `trend_block_detail(coin)` | Ajoutée | Retourne `None` si la tendance de fond autorise l'achat, sinon le skip_detail texte (TYPE_A). Vérifie que le coin ET BTC clôturent au-dessus de l'EMA100 1d (bougies Kraken). Cache les résultats par coin pour éviter les appels répétés dans un même cycle. |
| `ema_last(values, n)` | Ajoutée | Calcule la dernière valeur de l'EMA(n) avec α = 2/(n+1), amorcée sur la première valeur (même formule que `scripts/stop_trend_replay.py`). Retourne `None` si moins de n valeurs disponibles. |
| `fetch_daily_trend(coin, ema_days, now_ts)` | Ajoutée | Fetch les bougies 1d Kraken pour un coin, exclut la bougie du jour en cours (clôture pas figée), retourne `(clôture 1d, EMA(ema_days))`. Retourne `None` si Kraken indisponible, inexploitable, ou < ema_days bougies clôturées — l'appelant ne doit pas acheter. |
| `phase3_scoring.py (loop)` | Modifiée | Appel à `trend_block_detail(coin)` après vérification de runup, résultat classé comme TYPE_A skip si tendance baissière ou indisponible. |
| `phase4_sizing.py (loop)` | Modifiée | Calcul de `stop_distance_pct` basé sur `stop_mode` : fixe (0,20) ou ATR×2,5. Application du plafond `max_stop_distance_pct` **uniquement en mode ATR** (non en mode fixe, où le risque est borné par le dimensionnement). |

## Décisions techniques notables

- **Défauts conservateurs** : `stop_mode="fixed"` et `trend_filter_enabled=true` sont activés par défaut dans `config.json`. Le code tolère l'absence de ces clés (défauts sensibles) pour rester rétrocompatible.

- **Cache de tendance par cycle** : `_trend_cache = {}` dans `phase3_scoring.py` accumule les résultats `fetch_daily_trend()` pour chaque coin/BTC appelé plusieurs fois. Cela réduit les appels Kraken de O(n_coins) à O(2) par cycle (coin + BTC).

- **Exclusion de la bougie du jour** : `fetch_daily_trend()` exclus la bougie 1d en cours en vérifiant `float(c[0]) + CANDLE_1D_SECONDS <= now_ts`. Garantit que la clôture est figée (pas en cours de formation).

- **Plafond `max_stop_distance_pct` en mode fixe** : Le plafond 12 % est ignoré en mode `"fixed"` car 20 % > 12 % bloquerait tous les trades. Le risque reste borné à `risk_per_trade_pct` (2 %) via le dimensionnement Phase 4 : `quantité = 2% / (20% + 0,9%)`, soit environ 9,6 % du portefeuille par trade.

- **Rejeu multiplate-forme** : `scripts/stop_trend_replay.py` teste sur Binance 4h (données longues depuis 2021-05, 10 coins) et Kraken 4h (720 bougies récentes, même univers). Résultats : le filtre + stop −20 % améliore tout, le palier intermédiaire ne gagne rien.

- **Palier intermédiaire écarté** : Grille testée (9 combinaisons X×Y de baisse+remontée) ne gagne jamais. Les meilleures cases (2%, 5%) ne compensent les pertes que sur 3 fenêtres sur 5, jamais toutes.

## Impact sur l'architecture

- **Phase 3 enrichie** : Ajout du filtre de tendance en tant que déclencheur TYPE_A skip (même priorité que runup, RSI dégradé, positions max). Type_detail exact et chiffré pour le debug.

- **Phase 4 dupliquée de logique** : Stop ATR vs fixe calculé en deux branches ; plafond appliqué conditionnellement. Simplifie : aucune nouvelle abstraction, seulement deux calculs parallèles.

- **Dépendance à Kraken 1d** : Filtre de tendance tombe gracieusement (pas d'achat) si Kraken indisponible ou < 100 bougies clôturées — sécurité avant opportunité.

- **Pas de nouvel état persistant** : Les skip TYPE_A du filtre sont loggés comme les autres (skip_type + skip_detail dans MongoDB et cycle_log.jsonl).

- **Tests passants** : Suite complète `pytest tests` → 740 passed (tous les tests CLI Kraken et phases patchés).

## Références CLAUDE.md respectées

- **Minimalisme** : Pas de classe, pas de config builder. Deux simples calculs parallèles de stop_distance_pct ; une boucle de filtre de tendance par coin.

- **Pas de gestion d'erreur sur scénarios impossibles** : Les trois clés config manquantes utilisent des defaults sensibles (décrit dans le code). Les erreurs réseau Kraken sont captées au plus bas niveau (except large dans `fetch_daily_trend`).

- **UTC interne, affichage local** : Aucun changement. Les timestamps Kraken restent UTC, aucune conversion d'affichage Telegram n'a besoin de changer.

- **Pas de modification CLAUDE.md** : Aucune règle métier touchée, juste une stratégie enrichie.

- **Tests via `unittest` stdlib** : `tests/test_stop_trend_521.py` couvre break-even, partiel, cible, stop suiveur avec stop −20 % ; rejeu dans `scripts/stop_trend_replay.py` sur bougies publiques pour la validation métier.

- **Secrets uniquement via `.env`** : Aucun secret ajouté. Kraken est déjà initié globalement.

- **Config.json uniquement** : Les quatre nouvelles clés sont stockées en config, pas hardcodées.

## Notes futures

- **Recalibrage Phase 0** : Le recalibrage TP (#344) utilise `stop_distance_pct` depuis l'ordre d'entrée stocké. Depuis cette PR, si `stop_mode="fixed"`, la distance est figée à 0,20. Le calcul TP mécanique (RR 1,5) reste identique.

- **Filtre de tendance en Phase 0** : Actuellement activé seulement en Phase 3. Si une position montre un break de la tendance (clôture 1d < EMA100) après l'entrée, elle n'est pas vendue — c'est une limite acceptée pour éviter le sur-trading.

- **Mesure produit (30j+)** : Le palier intermédiaire a été mesuré mais rejeté ; ne pas le réintroduire sans nouvelles données. Stop −20 % + filtre seuls suffisent et sont plus simples.

