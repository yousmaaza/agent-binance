# Mémoire thématique du projet

Un fichier par sujet durable — le *pourquoi* d'une décision, les chiffres mesurés, les pièges découverts en pratique. Complète `../MEMORY.md` (journal chronologique) et `../../CLAUDE.md` (règles).

Ce qui n'a **pas** sa place ici : ce que le code, `git log` ou `docs/technique/` racontent déjà.

| Fichier | À lire avant de… |
|---|---|
| [frais-kraken.md](frais-kraken.md) | toucher au calcul d'un coût, changer de palier, ou s'étonner d'un taux de frais |
| [pnl-net-semantique.md](pnl-net-semantique.md) | interpréter un `pnl_usdc`, relancer le backfill, comparer des trades d'avant/après le 22/08 |
| [ratio-gain-risque-reel.md](ratio-gain-risque-reel.md) | modifier un TP, un stop, un dimensionnement, ou `reward_risk_ratio` |
| [strategie-maker.md](strategie-maker.md) | régler le watcher maker, étendre aux sorties, ou juger si la stratégie marche |
| [filtre-liquidite.md](filtre-liquidite.md) | resserrer un filtre d'univers, ou expliquer une perte supérieure au risque prévu |
| [contrat-prompts-scripts.md](contrat-prompts-scripts.md) | déplacer un chemin de fichier d'échange, ou déplacer de la logique entre Python et prompt |
| [verifier-le-travail-des-agents.md](verifier-le-travail-des-agents.md) | relire une PR produite par un agent |

## Le fait dominant, si on ne lit qu'une ligne

Au 23/08/2026, le bot affichait historiquement **+68 USDC de gain** ; le PnL réel net de frais était de **+11 USDC**, puis **−13 USDC** après deux stops touchés. Le ratio gain/risque réel est de **1,20** alors qu'il est configuré à 2,00.

La stratégie ne perd pas sur le marché — elle perd sur les frais. Toute décision de conception doit partir de là.
