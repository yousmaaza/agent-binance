# `pnl_usdc` est un PnL NET depuis #382 — et les limites du backfill

## Le changement de sémantique

Depuis l'issue #382 (mergée le 2026-08-22), `pnl_usdc` dans `state/trade_history.json` est **net de frais**. L'ancien calcul (différence de prix seule) est conservé sous `pnl_gross_usdc`.

Ce choix a été fait délibérément plutôt que d'ajouter un champ `pnl_net_usdc` séparé : tous les consommateurs existants — notifications Telegram, `/perf`, rapports, MongoDB — disent ainsi la vérité sans modification. Le revers est qu'un champ existant a changé de sens ; ne pas comparer des `pnl_usdc` d'avant et d'après sans précaution.

Champs associés ajoutés : `entry_fee_usdc`, `exit_fee_usdc`, `fees_usdc`, `maker_or_taker`, `pnl_gross_pct`.

**Invariant à préserver** : `pnl_pct` est lui aussi net, en miroir de `pnl_usdc`. Une première version de #382 avait laissé `pnl_pct` en brut, ce qui affichait dans Telegram des lignes du type « +0,45 % | −1,53 USDC » — un pourcentage positif à côté d'un montant négatif. Le helper `compute_net_pnl()` de `core/trade_helpers.py` calcule les quatre valeurs ensemble, c'est le seul endroit où la formule doit vivre.

## Le backfill : ce qu'il couvre et ce qu'il ne couvre pas

`scripts/backfill_fees.py` reconstitue les frais historiques depuis `kraken trades-history`.

**Limite dure** : l'API Kraken ne remonte qu'au **03/07/2026**. Les trades antérieurs (une trentaine) ont des frais **estimés** au taux du palier de l'époque et portent `fees_estimated: true`. Ne jamais présenter ces valeurs comme mesurées.

**Méthode de rapprochement validée** : les entrées par `entry_order_id` ; les sorties, dont aucun txid n'est stocké, par **paire + volume exact à 8 décimales** — 41 correspondances sans ambiguïté, 0 ambiguë. Prévoir une fenêtre temporelle large (jusqu'à ~48 h) pour les sorties par stop-loss : le stop s'exécute sur Kraken plusieurs heures avant que le bot ne le détecte au cycle suivant (écarts constatés de −7 500 s à −67 000 s).

## Deux garde-fous à ne pas affaiblir

**Le diagnostic de cohérence.** Une première version du backfill recalculait `pnl_gross_usdc` depuis `(exit_price − entry_price) × quantity` au lieu de reprendre la valeur stockée. Sur 76 trades sur 77 les deux coïncidaient — mais sur un enregistrement legacy de l'ère Binance (trade `38515bab`, SYN, `exit_price` corrompu depuis l'origine), cela a injecté **+44 USDC fictifs** dans l'historique. Depuis, `_coherence_diagnostic()` écarte sans les modifier les trades dont l'écart relatif dépasse 1 %, et le signale dès le `--dry-run`.

Deux trades sont durablement écartés par ce garde-fou et n'ont donc pas de `fees_usdc` : **SYN** (écart 102,7 %, données corrompues) et **PENDLE** (écart 1,7 % mais seulement 0,004 USDC en absolu — un artefact d'arrondi, écarté par excès de prudence du seuil purement relatif).

**Un `--dry-run` doit montrer ce qu'une exécution réelle produirait.** Lors du premier incident, le dry-run était rassurant alors que l'écriture corrompait l'historique. C'est le défaut de sécurité le plus grave rencontré sur ce script.

## Précautions d'exécution

`state/trade_history.json` est **tracké par git** et constitue la source de vérité de `/perf`. Avant toute exécution réelle : sauvegarde hors dépôt, et vérification qu'aucun cycle ne tourne (`state/agent_lock.json`). Le TP watcher écrit dans ce fichier toutes les 2 minutes — arrêter le service si l'opération modifie des trades clôturés.

Voir aussi [[frais-kraken]] et [[verifier-le-travail-des-agents]].
