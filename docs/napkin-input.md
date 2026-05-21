# Documentation pour Napkin AI — agent-binance

Document source à copier-coller dans l'interface Napkin AI (https://app.napkin.ai) pour générer des visuels.

**Mode d'emploi** : chaque section ci-dessous (titre `##`) est conçue pour produire **un visuel indépendant**. Copie une section entière (titre inclus) dans Napkin → il proposera 3 à 5 styles de diagrammes. Choisis celui qui colle le mieux, exporte en SVG, et place-le dans `docs/visuals/` puis insère-le dans le README aux endroits indiqués.

Les textes sont volontairement rédigés en phrases complètes et descriptives (pas en code, pas en bullet-points secs) — c'est ce qui donne les meilleurs résultats avec Napkin.

---

## 1. Architecture système — vue d'ensemble

Agent-binance est un bot de trading crypto piloté par Telegram. Il tourne comme un unique processus Python en polling-only, sans aucun port entrant ni tunnel.

Le processus principal est `webhook_server.py`. Il poll l'API Telegram en long-polling toutes les 30 secondes pour recevoir les commandes de l'utilisateur. Il intègre aussi un auto-scheduler interne qui déclenche un cycle de trading toutes les 4 heures, aligné sur les clôtures de bougies TradingView.

À chaque cycle, le serveur lance un sous-processus Claude CLI qui orchestre l'analyse complète. Ce sous-processus n'écrit pas directement les ordres : il appelle binance-cli en subprocess pour interagir avec l'API Binance Spot.

Pour les données de marché, Claude utilise le serveur MCP TradingView qui fournit le top des gainers, les breakouts de volume, le sentiment global et l'analyse multi-timeframe.

Les résultats de chaque cycle sont persistés dans MongoDB Atlas (collection `cycles`) et résumés par une notification Telegram envoyée à l'utilisateur.

L'utilisateur communique uniquement via Telegram : il envoie des commandes (`/trade`, `/status`, `/perf`, `/raisonnement`, `/reset`) et reçoit en retour des notifications structurées en français vulgarisé.

**Flux principal** : utilisateur → Telegram → webhook_server → Claude CLI → binance-cli → Binance Spot. En parallèle, Claude CLI → TradingView MCP pour les données, et Claude CLI → MongoDB Atlas pour la persistance.

---

## 2. Stack technique et services externes

Le bot agent-binance s'appuie sur cinq services externes et trois outils en ligne de commande.

Côté services cloud, Telegram Bot API fait office d'interface utilisateur entrante et sortante. Binance Spot exécute les ordres réels sur le marché. TradingView fournit les données techniques en temps réel via un serveur MCP. MongoDB Atlas héberge la base persistante des cycles de trading. Anthropic Claude fournit le modèle d'IA qui orchestre chaque cycle.

Côté outils locaux, trois CLI sont indispensables. Claude CLI lance le sous-processus IA à chaque cycle. binance-cli encapsule les appels à l'API Binance. curl est utilisé pour tous les appels Telegram sortants (la bibliothèque urllib Python échoue dans certains environnements réseau).

Le code applicatif est écrit en Python 3.11 dans un environnement virtuel local. Les dépendances runtime sont minimales : pymongo pour MongoDB et loguru pour les logs structurés. Aucun framework lourd comme pandas ou scipy n'est utilisé — toutes les statistiques (Sharpe, p-value, drawdown) sont implémentées à la main pour garder le projet portable.

Le projet est mono-fichier : tout tient dans `scripts/webhook_server.py` (environ 750 lignes). Cette simplicité est un choix assumé pour faciliter la maintenance d'un projet personnel sans équipe.

---

## 3. Cycle de trading en 7 phases

Un cycle de trading complet se déroule en sept phases séquentielles, orchestrées par le sous-processus Claude CLI. Chaque phase envoie une notification Telegram avant de passer à la suivante.

**Phase 0 — Vérifications préalables.** Lecture du portefeuille Binance, calcul du budget disponible, vérification que la limite de perte journalière (5 pour cent) n'est pas atteinte. Réconciliation des trades ouverts avec les ordres Binance actifs pour détecter les positions clôturées depuis le dernier cycle.

**Phase 1 — Scan marché.** Quatre screeners TradingView sont lancés en parallèle : top gainers, breakouts de volume, sentiment global, filtre par note technique. Le bot construit un univers de 20 cryptomonnaies maximum à analyser.

**Phase 2 — Analyse multi-timeframe.** Pour chaque coin retenu, deux analyses parallèles sont lancées sur les timeframes 4 heures et 1 jour. Les indicateurs collectés sont RSI, MACD, ADX, signal directionnel et tendance de fond.

**Phase 3 — Scoring et sélection.** Chaque coin reçoit un score de 0 à 10 basé sur huit critères techniques. Les filtres bloquants sont appliqués : score minimum, corrélation entre positions, liquidité, nombre maximum de positions ouvertes. Décision finale par coin : BUY, HOLD, SELL ou SKIP.

**Phase 4 — Sizing des ordres.** Le risque est fixé à 1 pour cent du portefeuille par trade. Le stop-loss est calculé à 2 fois l'ATR. Le take-profit vise un ratio gain/risque de 3 pour 1. La quantité est ajustée selon les contraintes Binance (montant minimum, précision du pas).

**Phase 5 — Exécution.** Placement d'ordres OTOCO atomiques sur Binance Spot. Un seul appel API place simultanément l'ordre d'entrée, le take-profit et le stop-loss. Notification Telegram pour chaque ordre placé ou rejeté.

**Phase 6 — Rapport.** Génération d'un rapport Markdown complet dans le dossier reports avec le résumé du contexte marché, le tableau des décisions et les ordres exécutés.

**Phase 7 — Persistance.** Sauvegarde du cycle complet en base MongoDB. Envoi d'une notification Telegram de synthèse en français vulgarisé. Libération du verrou de cycle.

---

## 4. Auto-scheduler aligné TradingView

Le bot déclenche automatiquement un cycle de trading toutes les 4 heures, sans aucune intervention de l'utilisateur. Ces déclenchements sont alignés sur les clôtures de bougies TradingView, ce qui permet à l'analyse technique de travailler sur des données fraîchement consolidées.

Les six slots quotidiens sont fixes en horaire UTC : 00 h 05, 04 h 05, 08 h 05, 12 h 05, 16 h 05 et 20 h 05. Le décalage de 5 minutes après la clôture exacte laisse à TradingView le temps de consolider les indicateurs.

Le scheduler ne vit pas dans un cron système ni un service systemd : il est intégré directement dans la boucle principale de polling Telegram. À chaque itération, le serveur calcule le prochain slot, et lance le cycle dès que l'heure courante le dépasse.

Si l'utilisateur lance manuellement un cycle via la commande `/trade`, le slot suivant est conservé tel quel : il n'y a pas de chevauchement possible grâce au verrou `agent_lock.json` qui empêche deux cycles de tourner simultanément.

Le passage entre l'horaire UTC interne et l'affichage local pour l'utilisateur se fait au moment de l'envoi des notifications Telegram, jamais avant. Cela garantit que la logique interne reste indépendante du fuseau horaire de la machine.

---

## 5. Ordre OTOCO — entrée + TP + SL en un seul appel

Binance Spot interdit de placer un ordre de vente sur un actif que l'on ne détient pas encore. Cette contrainte rendait impossible le placement simultané d'un BUY LIMIT, d'un take-profit et d'un stop-loss : les deux ordres de vente étaient rejetés tant que le BUY n'était pas exécuté.

La solution est l'ordre OTOCO (One-Triggers-OCO). C'est un type d'ordre composite supporté par Binance Spot qui combine un ordre actif (working order) et deux ordres en attente (pending orders) liés par une logique OCO (One-Cancels-Other).

**Ordre actif** : un BUY LIMIT au prix d'entrée calculé. Tant qu'il n'est pas rempli, les deux ordres en attente restent inertes.

**Ordre pending au-dessus** : un take-profit LIMIT_MAKER au prix cible, soit l'entrée majorée de trois fois la distance au stop.

**Ordre pending en-dessous** : un stop-loss STOP_LOSS_LIMIT à 2 fois l'ATR sous le prix d'entrée, avec un trigger légèrement supérieur au prix limite pour assurer l'exécution en cascade baissière.

Le déroulé d'un OTOCO réussi est le suivant. L'appel API est atomique : un seul appel place les trois ordres. Dès que le BUY LIMIT est rempli, Binance arme automatiquement les deux ordres pending en mode OCO. Si le take-profit se déclenche, le stop-loss est automatiquement annulé, et inversement. Si le BUY LIMIT n'est jamais rempli (le prix s'éloigne), aucun des deux pending ne s'arme : l'ordre OTOCO entier peut être annulé d'un seul appel.

Tous les identifiants des trois ordres et l'identifiant du groupe OTOCO sont sauvegardés dans l'historique local de trades pour permettre une annulation groupée si nécessaire.

---

## 6. Scoring multi-critères 0 à 10

Chaque coin candidat reçoit un score sur 10 calculé par addition de huit critères techniques indépendants. Aucun critère seul ne peut bloquer un trade, mais chaque point gagné renforce la conviction de l'IA.

**Signal TradingView 4 heures haussier** rapporte 2 points. C'est le critère le plus important car le timeframe 4 heures est la base de la stratégie.

**Signal TradingView 1 jour haussier** rapporte aussi 2 points. Un alignement des deux timeframes (4h et 1d) signale une tendance multi-échelle.

**RSI 4 heures entre 30 et 55** rapporte 1 point. Cette zone est considérée comme la fenêtre d'entrée optimale, ni survendue ni surachetée.

**Croisement haussier MACD sur 4 heures** rapporte 1 point. C'est un signal classique de retournement de momentum.

**Présence dans le screener de breakout de volume** rapporte 1 point. Un volume anormalement élevé valide la conviction du marché.

**ADX 4 heures supérieur à 20** rapporte 1 point. C'est la confirmation qu'une tendance est en place, qu'elle soit haussière ou baissière.

**Sentiment global du marché haussier** rapporte 1 point. C'est un critère macro qui favorise les longs quand l'ensemble du marché crypto est en accumulation.

**Présence dans le top des gainers du jour** rapporte 1 point. C'est un critère de momentum court terme qui privilégie les coins en mouvement.

Pour qu'un trade soit déclenché, deux conditions doivent être réunies : score total supérieur ou égal à 6, et signal 4 heures explicitement haussier. Un signal 1 jour baissier n'est pas bloquant en soi : il réduit simplement le score total.

---

## 7. Commandes Telegram

Le bot répond à cinq commandes principales émises par l'utilisateur depuis l'application Telegram. Chaque commande déclenche un comportement précis et renvoie une notification structurée.

**Commande /trade.** Lance immédiatement un cycle complet d'analyse et de trading. Le bot envoie une notification au début de chaque grande étape pour permettre à l'utilisateur de suivre le raisonnement. Si un cycle est déjà en cours, le bot signale qu'il attend la fin avant d'en démarrer un nouveau.

**Commande /status.** Affiche une vue instantanée du portefeuille sur Binance. Solde disponible, montant verrouillé dans des ordres en cours, positions ouvertes suivies par le bot, ordres en attente côté Binance, et heure du prochain cycle automatique calculée en temps local.

**Commande /perf.** Statistiques de performance calculées sur tous les trades fermés depuis le début. Taux de réussite, espérance de gain par trade, profit factor, ratio de Sharpe annualisé, perte maximale en série, et test de significativité statistique avec une p-value.

**Commande /raisonnement.** Explication en français vulgarisé du dernier cycle de trading. Décrit ce que le bot a analysé, pourquoi il a acheté ou non, et son évaluation du contexte de marché. Ce texte est lu directement depuis MongoDB.

**Commande /reset.** Déverouille le bot si un cycle précédent s'est arrêté de façon anormale (plantage, timeout, fermeture brutale). Cette commande remet le verrou agent_lock à l'état libre.

En parallèle de ces cinq commandes, le bot fonctionne aussi en mode entièrement autonome grâce à l'auto-scheduler qui déclenche un cycle toutes les 4 heures sans intervention.

---

## 8. Persistance des données

Le bot utilise quatre couches de persistance complémentaires.

**Historique de trades local.** Le fichier `state/trade_history.json` est la source de vérité pour tous les trades passés et actifs. Chaque entrée contient le coin tradé, le sens, les prix d'entrée stop et take-profit, la quantité, le risque en USDC, les identifiants des ordres Binance, l'identifiant OTOCO du groupe, le statut (open ou closed), le PnL réalisé et les dates de début et fin. Ce fichier est lu et mis à jour à chaque cycle.

**Verrou de cycle.** Le fichier `state/agent_lock.json` empêche deux cycles de tourner en parallèle. Il contient un drapeau actif/inactif et un timestamp de démarrage. Il se libère automatiquement à la fin d'un cycle ou via la commande /reset.

**Position de lecture Telegram.** Le fichier `state/telegram_offset.json` mémorise le dernier message Telegram traité afin d'éviter de retraiter les anciens messages après un redémarrage du bot.

**Base MongoDB Atlas.** La collection `cycles` stocke un document complet par cycle de trading. Contexte de marché analysé, décisions prises pour chaque crypto avec leur motif, ordres placés avec leurs identifiants, budget utilisé, et explication vulgarisée en français. C'est cette base qui alimente la commande /raisonnement.

À ces quatre couches s'ajoutent les journaux locaux : log quotidien du processus principal avec rotation automatique, log de sortie et d'erreurs par cycle pour le débogage, et rapports lisibles par cycle au format Markdown dans le dossier reports.

---

## 9. Flux de données entrant et sortant

Les données circulent dans agent-binance selon un schéma à trois étages : sources externes en entrée, traitement par le serveur et le sous-processus IA, et productions à destination de l'utilisateur et du stockage.

**Sources entrantes.** L'utilisateur émet des commandes via Telegram. TradingView fournit les données de marché en temps réel sous forme de scores techniques et de classements. Binance fournit les soldes du portefeuille, la liste des ordres en cours et les confirmations d'exécution.

**Traitement par le serveur principal.** Le serveur webhook reçoit les commandes Telegram en continu. Pour une demande de statut portefeuille, il interroge Binance directement et renvoie le résultat. Pour une analyse de performance, il consulte l'historique local des trades. Pour une explication du dernier cycle, il interroge MongoDB. Pour lancer un cycle de trading complet, il démarre un sous-processus Claude CLI dédié.

**Traitement par le sous-processus IA.** Le sous-processus Claude lit la configuration et l'historique des trades, puis interroge TradingView pour analyser le marché. Il calcule les meilleures opportunités, prépare les ordres OTOCO et les envoie à Binance pour exécution. Enfin il sauvegarde le rapport complet du cycle dans MongoDB et envoie une synthèse à l'utilisateur via Telegram.

**Productions sortantes.** Notifications Telegram envoyées à l'utilisateur à chaque étape importante. Rapport de cycle sauvegardé localement en format Markdown lisible. Historique complet du cycle stocké dans MongoDB pour archivage et explication ultérieure. Journaux techniques pour le débogage en cas de problème.

---

## Intégration des visuels dans le README

Une fois les SVG générés depuis Napkin, place-les dans `docs/visuals/` puis insère-les dans le `README.md` aux endroits suivants :

- **Architecture système** : juste sous le titre principal, avant la section Prérequis.
- **Stack technique** : dans la section Prérequis pour remplacer le tableau actuel.
- **Cycle en 7 phases** : remplace le bloc ASCII actuel de la section « Workflow d'un cycle ».
- **Auto-scheduler** : nouvelle section juste après « Démarrage ».
- **OTOCO** : nouvelle section juste après la section Configuration.
- **Scoring** : remplace le tableau actuel de la section « Scoring des signaux ».
- **Commandes Telegram** : remplace le tableau actuel de la section « Commandes Telegram ».
- **Persistance** : nouvelle section à insérer dans Architecture.
- **Flux de données** : nouvelle section à insérer dans Architecture.

Syntaxe d'insertion d'une image dans le README :

```markdown
![Architecture système](docs/visuals/architecture.svg)
```
