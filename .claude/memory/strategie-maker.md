# Stratégie maker sur les entrées — conception et premières mesures

## Pourquoi elle existe

Avant le 2026-08-22, **99 exécutions sur 99 étaient « taker »** : le bot ne passait que des ordres au marché, donc toujours au tarif le plus cher. Au Tier 2, le maker coûte exactement la moitié (voir [[frais-kraken]]). Sur la période mesurée, cela représentait **27,56 USDC d'économie potentielle**, à comparer à un PnL net total de +11,11 USDC — le levier le plus rentable identifié sur le projet.

Fait décisif qui rend l'arbitrage favorable : les spreads mesurés (XBT 0,017 %, ETH 0,010 %, SOL 0,022 %) sont **3 à 30 fois plus petits que l'économie de frais (0,30 %)**. Même en concédant tout le spread pour être exécuté, on reste gagnant. Le seul vrai risque n'est donc pas le prix d'entrée, c'est la **non-exécution**.

## Les deux primitives Kraken qui rendent la chose possible

- **`kraken order amend --txid <ID> --limit-price <P>`** modifie un ordre vivant **en préservant sa priorité dans le carnet**. Un cycle annuler/replacer ferait repartir l'ordre en fin de file à chaque ajustement, ce qui ruinerait les chances d'exécution.
- **`--oflags post`** (post-only) garantit le statut maker : si l'ordre croiserait le carnet, Kraken le **rejette** au lieu de l'exécuter en taker. C'est le garde-fou qui empêche de perdre l'économie sans s'en apercevoir.

## La hiérarchie des bornes d'arrêt — ne pas l'inverser

1. **Budget de concession, 0,30 %** — borne principale, égale à l'économie de frais. Au-delà, poursuivre n'a plus aucun intérêt économique. Ce critère s'autorégule selon la volatilité de chaque paire, ce qu'un délai fixe ne fait pas.
2. **Invalidation du signal, 2 %** — réutilise `price_deviation_max_pct`. Au-delà, la thèse du trade est morte : on abandonne, on ne se replie pas au marché.
3. **Garde-fou temporel, 60 min** — uniquement pour libérer le solde réservé (`hold_trade`) et garantir la résolution avant le cycle suivant.

**Pourquoi le temps ne doit pas être la borne principale** : mesuré sur 721 bougies de 5 minutes, le prix ne bouge en médiane que de 0,10 à 0,16 % en 5 minutes, contre un budget de 0,30 %. Un délai court couperait la poursuite alors qu'il reste les deux tiers du budget — on paierait le taker sans raison. Une première version du ticket proposait 5 minutes ; c'était une erreur, corrigée après mesure.

## Premières mesures réelles (nuit du 22 au 23/08/2026)

```
total_fills: 2   ·   total_fallbacks: 0
TRUMP  rempli en 110 s   ·   frais d'entrée 0,396 USDC (maker)
XDG    rempli en  94 s   ·   frais d'entrée 0,163 USDC (maker)
```

**Moins de deux minutes, sans aucun ajustement de prix nécessaire, aucun repli au marché.** Les délais sont donc bien plus courts qu'estimé — mais le garde-fou à 60 min reste justifié, il ne coûte rien quand les remplissages sont rapides.

## Réglages

`maker_entry_enabled` (true), `maker_tick_seconds` (20), `maker_max_concession_pct` (0.003), `maker_timeout_seconds` (3600).

**`maker_entry_enabled: false` restaure exactement le comportement d'avant**, sans redéploiement de code — c'est le repli d'urgence si quelque chose se passe mal en production.

## Ce qui manque encore pour juger la stratégie

Le watcher persiste `total_fills` et `total_fallbacks` mais **pas les abandons** (issue #408). Or le risque principal de cette stratégie est de **rater des trades** : sans ce compteur, l'économie de frais est visible mais son coût ne l'est pas. C'est aussi un préalable au rendu enrichi de `/perf` (#396).

L'extension aux **sorties** (#390) est volontairement repoussée : une sortie qu'on n'arrive pas à exécuter laisse la position exposée, ce qui est bien plus grave qu'une entrée manquée. Décision à reprendre une fois le taux de remplissage réel mesuré sur les entrées.

Note pour l'avenir : `maker_or_taker_from_ordertype()` retourne **`None`** pour les types d'ordre qu'il ne sait pas classer, plutôt qu'une valeur affirmative fausse — tout affichage consommant ce champ doit gérer ce cas. Les 77 trades antérieurs au déploiement portent `None`, le backfill ne l'ayant pas renseigné rétroactivement.
