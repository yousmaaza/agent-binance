# Frais Kraken — grille, palier du compte, et pourquoi ils dominent le résultat

## La grille appliquée au compte

Kraken est passé le **9 juillet 2026** à une grille « cross-platform » : le palier dépend du **meilleur des trois critères sur 30 jours** — volume spot, volume futures, ou actifs détenus sur la plateforme (AoP).

| Palier | Seuil (volume spot 30j) | Maker | Taker |
|---|---|---|---|
| Tier 1 | > 0 | 0,40 % | **0,80 %** |
| Tier 2 | > 2 500 USD | 0,30 % | **0,60 %** |
| Tier 3 | > 10 000 USD (ou 20k AoP) | 0,22 % | 0,38 % |

Le compte est au **Tier 2** (volume spot 30j ≈ 6 100 USD, AoP ≈ 600 USD). Vérifiable à tout moment par `kraken volume -o json` (champs `domain_spot_volume_30d` et `domain_assets_on_platform`).

Les trois taux observés dans l'historique (0,40 % avant le 8/07, 0,80 % du 10 au 22/07, 0,60 % depuis) correspondent exactement à cette grille — **ce ne sont pas des anomalies de facturation**, la question a été instruite et close.

## Deux mécaniques non évidentes

**Le tarif maker est exactement la moitié du taker** aux Tiers 1 et 2 (0,30/0,60 et 0,40/0,80). Ce rapport de 2× cesse d'être exact aux Tiers 3-4 (0,22/0,38 puis 0,20/0,35) — toute formule qui suppose « maker = moitié du taker » devra être revue si le compte monte de palier.

**Le palier s'auto-entretient par l'activité du bot.** Le Tier 2 est atteint grâce au volume généré par le bot lui-même. Si l'activité ralentit et que le volume 30j repasse sous 2 500 USD, le compte **retombe au Tier 1 et les frais augmentent** de 0,60 à 0,80 %. Une baisse d'activité coûte donc double.

## Ce que les frais représentent réellement

Mesuré sur 99 exécutions (03/07 → 21/08/2026) : **53,50 USDC de frais pour 8 645 USDC de volume**, soit 0,619 % par exécution et ~1,24 % aller-retour.

Sur les trades clôturés, cela signifiait un PnL brut de +68,17 USDC pour un **net réel de +11,11 USDC** — les frais absorbaient 84 % du gain apparent. C'est le fait dominant du projet : la stratégie ne perd pas sur le marché, elle perd sur les frais.

## Comment lire un frais réel

Le champ `fee` est renvoyé par `kraken query-orders <txid> -o json` (niveau ordre) et par `kraken trades-history -o json` (niveau exécution, qui expose en plus `maker`). `cost` y est le notionnel hors frais — vérifié : `cost == price × vol` sur les 99 exécutions. Le taux se calcule donc `100 × fee / cost`.

Voir aussi [[pnl-net-semantique]] pour la façon dont ces frais sont désormais persistés, et [[ratio-gain-risque-reel]] pour leur effet sur la stratégie.
