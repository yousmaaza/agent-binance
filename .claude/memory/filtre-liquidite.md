# Filtre de liquidité — calibrage du seuil de spread et incident TRUMP

## L'incident fondateur

Le 22/08/2026, le bot a acheté **TRUMP** puis perdu **13,20 USDC** — 43 % de plus que le risque prévu de 9,22 USDC. Décomposition : le stop posé à 2,321 s'est exécuté à **2,2676**, soit **2,3 % en dessous** (glissement, ~2,83 USDC), plus 1,12 USDC de frais.

Trois causes conjuguées :
- Le mode dégradé avait abaissé le seuil de score (voir plus bas).
- TRUMP avait un volume de **21 617 USDC** l'après-midi, monté à **586 836** dans la nuit — un pic de **×27**, typique d'un memecoin en pompe — franchissant tout juste le seuil de 500 000. Il a donc été jugé tradable sur un pic éphémère.
- Son spread était de **0,126 %**, douze fois celui de XBT ou SOL. Le filtre volume ne voyait pas cette différence.

**Le point structurel** : le filtre validait la liquidité **au scan**, alors que la liquidité qui compte est celle **du moment où le stop se déclenche**, plusieurs heures plus tard, dans un marché en baisse où le volume s'évapore. C'est la sortie qui est risquée, pas l'entrée.

## Le calibrage retenu — et pourquoi pas plus strict

`max_spread_pct` = **0,0008 (0,08 %)**, avec `volume_persistence_periods` = 6.

La première proposition était 0,05 %. Elle a été rejetée après mesure croisant le filtre avec le PnL net par coin :

| Paire | Spread | 0,05 % | 0,08 % | PnL net historique |
|---|---|---|---|---|
| XBT | 0,017 % | ✓ | ✓ | +3,11 |
| ETH | 0,010 % | ✓ | ✓ | −2,10 |
| SOL | 0,022 % | ✓ | ✓ | +2,42 |
| XRP | 0,026 % | ✓ | ✓ | −1,45 |
| **ADA** | **0,054 %** | **✗** | ✓ | **+10,57** |
| LINK | 0,130 % | ✗ | ✗ | −0,89 |
| TRUMP | 0,121 % | ✗ | ✗ | −13,20 |

À 0,05 %, le filtre excluait **ADA, le coin le plus profitable de l'historique**, pour un dépassement de 4 millièmes de pour-cent — et réduisait l'univers à 4 paires dont 3 déjà dans `portfolio_coins`, soit **un seul candidat réellement nouveau**. Sur un bot qui skippe déjà 84 % de ses cycles faute de candidats atteignant le seuil de score, cela aurait remplacé un problème de risque par un problème d'inactivité.

**Règle de conduite** : tout resserrement de filtre doit être mesuré en nombre de paires survivantes avant d'être adopté. L'univers Kraken USDC est structurellement étroit (46 paires, dont 3 à 5 tradables par cycle).

## Deux réserves à garder en tête

- **Le spread varie dans le temps.** ADA a été mesurée à 0,060 % puis 0,054 % à quelques heures d'intervalle ; TRUMP est passé de 0,126 % à 0,081 %. Un coin peut donc entrer et sortir de l'univers d'un cycle à l'autre. Cela plaide pour un seuil avec de la marge plutôt qu'ajusté au plus près.
- **Le bon PnL d'ADA ne prouve pas que son spread est inoffensif.** Ses trades n'ont peut-être jamais subi de stop en marché tombant. C'est une corrélation, pas une démonstration.

## Le glissement au stop est un risque de queue, pas systématique

Mesuré sur les 13 sorties par stop de l'historique : **une seule a réellement glissé** (TRUMP, −2,302 %). Huit se sont remplies *au-dessus* du prix de stop. ADA, avec un spread de 0,054 %, n'a glissé que de 0,081 %.

C'est pourquoi l'idée d'« élargir le stop ou réduire la taille sur les paires à spread large » (axe 3 de l'issue #407) **n'a volontairement pas été implémentée** : le seul cas problématique est désormais exclu par le filtre de spread, et la correction aurait réduit toutes les positions sur paires moyennes pour un risque qui n'existe plus. À rouvrir seulement si un glissement supérieur à 0,5 % réapparaît sur une paire ayant passé le filtre.

## Le mode dégradé — l'autre cause de l'incident

Quand tous les coins en signal 4h acheteur voient leur appel TradingView 1D échouer, le seuil de score passe de 6 à `min_signal_score_degraded` (4). L'intention est saine : le signal 1D vaut 2 points, sans lui aucun coin ne peut atteindre 6 et le bot cesserait de trader pendant les limitations.

Le défaut était que cette compensation ne s'accompagnait **d'aucun durcissement**. TRUMP est passé avec un score de 4 et un **RSI de 70,4**, très au-dessus du plafond de 65. Corrigé par l'issue #406 : en mode dégradé, le RSI doit désormais être dans la zone saine comme **condition d'éligibilité**, pas comme simple bonus. Un RSI inconnu vaut inéligibilité — deux inconnues ne se compensent pas.
