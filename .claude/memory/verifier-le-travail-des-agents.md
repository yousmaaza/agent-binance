# Vérifier le travail des agents — ce que les tests ne rattrapent pas

Retour d'expérience de la session du 22-23/08/2026, où quatorze PR ont été produites par des agents `binance-dev`. Plusieurs défauts sérieux ont été trouvés **après** que l'agent ait annoncé « suite complète verte ». Aucun n'aurait été détecté par la relecture du rapport de l'agent seul.

## Les défauts trouvés, et comment

**Un test de garde-fou qui ne tombait pas.** Le test de cohérence prompt ↔ script (#403) passait alors qu'on rejouait exactement l'incident qu'il devait prévenir. Deux versions successives ont été nécessaires. Trouvé en **cassant délibérément le contrat dans un worktree jetable** et en constatant que le test restait vert. Un test de garde-fou qui n'a pas été mis à l'épreuve donne une fausse assurance — pire que pas de test.

**Une modification de compteur qui mentait.** Les ordres maker en attente étaient comptés comme « exécutés » dans `PHASE5_DONE|executed=N`, ce qui se propageait au journal de cycle, à MongoDB et aux rapports. Trouvé en lisant le diff, pas le rapport.

**Un `pnl_pct` resté brut** alors que `pnl_usdc` devenait net, produisant des messages Telegram du type « +0,45 % | −1,53 USDC ». Trouvé en cherchant les incohérences de signe dans les données réelles.

**Un backfill qui corrompait l'historique.** Recalcul du PnL brut au lieu de reprendre la valeur stockée : +44 USDC fictifs injectés sur un enregistrement legacy. Trouvé en comparant les totaux **avant/après** contre une sauvegarde, pas en relisant le code.

## Ce qui a fonctionné pour les trouver

- **Exécuter réellement**, pas seulement lire. Lancer le script en sous-processus, forcer `TZ=UTC`, rejouer l'incident sur les fichiers du dépôt puis restaurer.
- **Comparer avant/après sur données réelles.** Toute opération sur `state/trade_history.json` doit être encadrée d'un instantané et d'un contrôle de dérive trade par trade.
- **Lire le diff, pas le résumé.** Les rapports d'agent sont fidèles sur ce qu'ils ont fait, muets sur ce qu'ils n'ont pas vu.
- **Vérifier le contrat, pas seulement l'unité.** Les tests valident chaque script isolément ; les ruptures se produisent aux jointures (prompt ↔ script, script ↔ script, compteur ↔ consommateur).

## Le piège récurrent : l'outillage de review automatique

Un bot de review pousse des commits sur les branches actives pendant qu'un agent travaille. Il a cassé **quatre fois** le contrat de chemins prompt ↔ script en appliquant la règle bandit B108, dont deux fois d'une manière qui aurait cassé la production. Voir [[contrat-prompts-scripts]].

Conséquence pratique : **relire le diff complet de la branche, pas seulement ce que l'agent dit avoir fait.** Des modifications arrivent en continu depuis d'autres sources.

## Un principe qui revient trois fois

À chaque itération du test #403, le même défaut reparaissait sous une forme différente : quand l'analyse ne sait pas conclure, elle laisse passer. Liste blanche par fichier, puis silence sur les chemins irrésolubles.

**Pour un garde-fou, l'absence de preuve ne doit jamais valoir preuve de conformité.** Un cas non analysable doit faire échouer et réclamer une justification explicite — jamais passer discrètement.
