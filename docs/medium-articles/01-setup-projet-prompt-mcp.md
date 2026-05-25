---
status: writing
number: 01
slug: 01-setup-projet-prompt-mcp
title: "Setup d'un bot de trading piloté par Claude + MCP TradingView"
target_length: 1500-2200 mots
target_audience: devs senior curieux des LLM en production, pas forcément traders
tags_medium: [Python, Claude, LLM, MCP, Trading, Automation]
created: 2026-05-25
published_url: ""
github_issue: "#119"
---

# Article 01 — Setup d'un bot de trading piloté par Claude + MCP TradingView

> Brouillon de travail. Le but est de **brainstormer** la structure et le contenu avant la rédaction finale.

## Pourquoi cet article (l'angle)

Premier article de la série. Il sert de **porte d'entrée** : on présente le projet, le setup minimal, et surtout les **deux briques d'IA atypiques** — le prompt monolithique et la connexion MCP — qui rendent le bot possible avec si peu de code.

**Promesse au lecteur** :
> En 1 fichier Python de 750 lignes, un prompt de 600 lignes, et 5 outils MCP TradingView, tu peux faire tourner un agent de trading qui scanne le marché, décide, et exécute des ordres OTOCO sur Binance. Voici comment c'est branché et pourquoi cette architecture marche.

**Ce que l'article n'est PAS** :
- Pas un tuto trading (les choix de stratégie sont anecdotiques).
- Pas un comparatif d'agents IA.
- Pas une démo "vibe coding" — c'est du code en prod qui prend des décisions financières réelles.

---

## Plan détaillé

### Hook (3-4 paragraphes)

- Anecdote d'ouverture : un cycle qui tourne pendant la rédaction de l'article. Capture Telegram à l'appui (notif Phase 0 → Phase 5 → résumé).
- Tension : « le code Python qui fait ça ne contient aucune logique de scoring, aucun appel à TradingView, aucun calcul d'ATR ». Comment ?
- Réponse en une phrase : tout l'intellect vit dans **un prompt** que Claude exécute en sous-processus, et toutes les données arrivent via **un MCP** que Claude utilise comme une bibliothèque standard.

### Section 1 — L'architecture en une image

Diagramme à embarquer : `docs/visuals/architecture.svg`.

Description en 5 boîtes :
1. **`binance-bot/webhook_server.py`** : process Python unique. Poll Telegram, gère le scheduler 4h, lance les sous-processus Claude.
2. **Sous-processus Claude CLI** : lancé à chaque cycle. Reçoit le prompt en argument, tourne 3-8 minutes, écrit le résultat dans MongoDB.
3. **MCP TradingView** : connecté côté Claude. Fournit 5 outils de scan/analyse marché.
4. **`binance-cli`** : appelé par Claude via Bash. Exécute les ordres OTOCO sur Binance Spot.
5. **MongoDB Atlas + fichiers locaux** : persistance des décisions et de l'état.

Souligner la **direction du flux** : utilisateur → Telegram → bot Python → Claude → (TradingView via MCP, Binance via CLI) → Mongo + Telegram.

### Section 2 — Le code Python ne fait *presque rien*

Quoi montrer concrètement :
- **Que fait le code Python ?** : polling Telegram, scheduling 4h, lancement de subprocess, persistance des logs.
- **Que ne fait-il pas ?** : aucune décision de trading, aucun appel API marché, aucun calcul technique.
- Snippet (5-10 lignes) : la fonction qui lance le subprocess Claude.

```python
# binance-bot/orchestration/cycle_runner.py (approximatif — vérifier le chemin exact)
process = subprocess.Popen(
    ["claude", "--print", "--verbose", "--output-format", "stream-json",
     "--dangerously-skip-permissions", prompt],
    stdout=subprocess.PIPE, stderr=err_f, text=True, cwd=PROJECT_DIR
)
```

→ Insister : **la totalité de l'intelligence du bot tient dans la variable `prompt`**.

### Section 3 — Le prompt monolithique en 8 phases

Le fichier `prompts/trade_prompt.txt` fait ~600 lignes (29 Ko). Il est injecté tel quel comme dernier argument du CLI Claude.

Structure documentée :

| Phase | Rôle | Sorties clés |
|---|---|---|
| **PHASE 0** | Vérifications préalables (portfolio, daily loss limit, réconciliation trades ouverts) | `portfolio_total`, `budget_disponible`, `open_positions` |
| **PHASE 1** | Scan marché parallèle (4 screeners TradingView) | univers de 20 coins |
| **PHASE 2** | Analyse multi-timeframe 4h + 1d couplée par coin | `signals_4h`, `signals_1d`, `RSI`, `MACD`, `ADX` |
| **PHASE 3** | Scoring 0-10 + filtres (corrélation, liquidité, positions max) | BUY candidates |
| **PHASE 4** | Sizing (risk 1% portfolio, stop ATR×2, TP 3:1) | ordres préparés |
| **PHASE 5** | Exécution OTOCO atomique sur Binance | order IDs |
| **PHASE 6** | Rapport Markdown dans `reports/` | fichier rapport |
| **PHASE 7** | Persistance MongoDB (décisions + `explanation_fr` vulgarisée) | document `cycles` |

À développer côté narratif :
- Pourquoi **8 phases séquentielles** plutôt qu'un prompt en flow libre ? Réponse : la séquence force Claude à matérialiser chaque étape (notif Telegram à la fin de chaque phase), ce qui permet à l'humain de suivre le raisonnement et à un crash en Phase 3 d'être debug sans re-scanner le marché entier.
- 4 substitutions automatiques (`__BOT_TOKEN__`, `__CHAT_ID__`, `__PROJECT_DIR__`, `__CYCLE_ID__`) qui rendent le prompt portable.
- Le prompt **ne contient aucun code de trading lui-même** — il décrit ce que Claude doit faire, et Claude génère + exécute le code Python à l'intérieur du subprocess. Ce paradoxe (un agent qui écrit son propre code à chaque exécution) mérite un paragraphe.

Snippet à montrer : extrait de Phase 1 où on liste les MCP appelés en parallèle.

```
PHASE 1 — SCAN MARCHÉ (tout en parallèle)
Lance simultanément :
- mcp__tradingview__top_gainers (exchange: BINANCE) → top gainers
- mcp__tradingview__volume_breakout_scanner (exchange: BINANCE) → breakouts volume
- mcp__tradingview__market_sentiment → sentiment global
- mcp__tradingview__rating_filter (exchange: BINANCE, rating: BUY) → coins notés BUY
```

→ Insister : Claude lit ces noms d'outils MCP **comme un humain lirait une doc d'API**. Pas de SDK, pas de wrapper, pas d'import. Juste la convention `mcp__server__tool`.

### Section 4 — MCP : le bus de données qui rend tout ça possible

**Définition simple du MCP (Model Context Protocol)** :
> Un protocole standard qui permet à n'importe quel LLM de découvrir et d'utiliser des outils externes via un serveur dédié. C'est l'USB du LLM : tu branches un serveur MCP, et le modèle voit immédiatement les outils que ce serveur expose.

**Les 5 outils MCP TradingView utilisés par le bot** (validés dans le code) :

| Outil | Quand | Que retourne |
|---|---|---|
| `mcp__tradingview__top_gainers` | Phase 1 | Liste des coins en plus forte hausse sur 24h |
| `mcp__tradingview__volume_breakout_scanner` | Phase 1 | Coins avec volume anormalement élevé |
| `mcp__tradingview__market_sentiment` | Phase 1 | Score de sentiment global du marché crypto |
| `mcp__tradingview__rating_filter` | Phase 1 | Coins notés BUY/STRONG_BUY par TradingView |
| `mcp__tradingview__coin_analysis` | Phase 2 | Analyse technique complète (RSI, MACD, ADX, signal) pour un coin et un timeframe donnés |

**Pourquoi MCP plutôt que des appels REST directs ?**
- Pas besoin d'écrire de wrapper. Le modèle découvre les outils tout seul.
- Pas de gestion d'auth dans le code Python. Le serveur MCP s'en occupe.
- Pas de format à parser. Le modèle reçoit du JSON structuré et le manipule directement.

**Configuration MCP — `.mcp.json` à la racine** :

```json
{
  "mcpServers": {
    "telegram-assistant": {
      "command": "python",
      "args": ["/Users/.../telegram-assistant-mcp/mcp_telegram_tool.py"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "${TELEGRAM_BOT_TOKEN}",
        "TELEGRAM_CHAT_ID": "${TELEGRAM_CHAT_ID}"
      }
    }
  }
}
```

(Le MCP TradingView est configuré côté utilisateur Claude Code, pas dans le projet — à clarifier dans l'article : différence entre MCP **projet** et MCP **utilisateur**.)

À développer narrativement :
- Comment vérifier qu'un MCP est branché ? Claude le mentionne au démarrage de la session (`mcp_servers: [...]`).
- Que faire quand un MCP rate (TradingView down) ? Le prompt anticipe : « Si analyse non disponible pour ce coin, marque-le SKIP avec motif `api_error` ».
- Le MCP TradingView n'est pas officiel Anthropic — c'est un serveur communautaire. Mentionner la source (lien GitHub) à ajouter avant publication.

### Section 5 — Le skill binance : comment Claude sait utiliser binance-cli

Le bot exécute des ordres réels sur Binance. Claude n'a pas cette connaissance en natif — il faut lui donner une documentation opérationnelle de l'outil `binance-cli`.

C'est le rôle du **skill binance** : un fichier markdown dans `.agents/skills/binance/SKILL.md` qui documente toutes les commandes disponibles (Spot, Futures, Convert, etc.) avec leurs flags, leurs contraintes et les règles de sécurité à respecter.

Ce skill est une **extension de contexte**, pas du code. Claude Code le lit au démarrage et sait ainsi qu'il peut appeler `binance-cli spot post-order --symbol BTCUSDC --side BUY --type LIMIT ...` dans un sous-processus Bash, avec les bonnes options et dans le bon ordre.

Points à développer :
- Différence entre skill (documentation locale consommée par Claude) et MCP (serveur d'outils connecté au runtime).
- Le skill est installé via `skills-lock.json` (similaire à un `package.json` pour les skills Claude Code).
- La règle de sécurité du skill : toujours demander `CONFIRM` avant d'exécuter une transaction réelle. Dans le bot, c'est géré autrement (le prompt définit le contexte auto-validé) — expliquer pourquoi on a overridé.
- Snippet : la définition du profil `agent-profile` dans `binance-cli` et comment le prompt y fait référence.

```bash
# Installation du binaire
npm install -g @binance/binance-cli

# Création du profil dédié au bot (une seule fois)
binance-cli profile create \
  --name agent-profile \
  --api-key TON_API_KEY \
  --api-secret TON_API_SECRET \
  --env prod
```

### Section 6 — Créer son bot Telegram en 5 minutes

Toutes les notifications du bot passent par Telegram. Deux éléments sont nécessaires : un token de bot et un chat ID.

**Créer le bot — @BotFather** :
1. Ouvrir Telegram, chercher `@BotFather`.
2. Envoyer `/newbot` → choisir un nom (ex : "Mon bot de trading") et un username (ex : `monbot_trade_bot`).
3. BotFather renvoie le token : `123456789:ABCdef...`. C'est `TELEGRAM_TOKEN` dans `.env`.

**Obtenir son chat ID — @userinfobot** :
1. Chercher `@userinfobot` dans Telegram.
2. Envoyer `/start` → il répond avec ton user ID. C'est `TELEGRAM_CHAT_ID` dans `.env`.

**Pourquoi le chat ID est important** : le bot filtre toutes les commandes entrantes sur ce chat ID. Toute autre personne qui trouverait l'username du bot ne pourrait pas déclencher de trades.

**Limites à mentionner** :
- Le bot ne fonctionne qu'en polling (il interroge Telegram toutes les 30 secondes). Pas de webhook, pas de port ouvert — choix délibéré pour tourner sur un réseau corporate qui bloque les connexions entrantes.
- Un seul bot pour un seul utilisateur. Multi-user aurait nécessité une gestion de sessions.

### Section 7 — Le setup minimal (reproductibilité)

5 étapes pour avoir un bot fonctionnel sur sa machine :

1. **Cloner** : `git clone https://github.com/yousmaaza/agent-binance`
2. **Installer le venv 3.11** + dépendances (`pymongo`, `loguru`).
3. **Configurer `.env`** : `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `MONGODB_URI`. (Notamment **pas** d'`ANTHROPIC_API_KEY` — on utilise l'abonnement Claude Code.)
4. **Configurer `binance-cli`** : profil `agent-profile` avec clés API Binance.
5. **Lancer** : `nohup .venv/bin/python -u binance-bot/webhook_server.py >> state/daemon.log 2>&1 &`

Mentionner : pas de tunnel, pas de port ouvert, pas de webhook entrant. **Polling-only** — ça tourne derrière n'importe quel réseau corporate.

### Section 8 — Pourquoi ça marche (en 3 leçons)

1. **Le code Python est une coquille, pas le cerveau.** Cette inversion (l'IA décide, le code orchestre) change le rapport effort/résultat. Ajouter une stratégie = éditer un prompt, pas refactor 500 lignes.

2. **Le MCP est un standard, pas une lib.** En passant par MCP, on s'épargne 100 % du code d'intégration TradingView. Le modèle découvre les outils, les appelle, parse les résultats. Zéro adapter à maintenir.

3. **La séquentialité du prompt rend l'IA observable.** 8 phases avec une notif Telegram à la fin de chacune, c'est l'équivalent d'un debugger pour LLM. On voit où ça se passe, on voit où ça plante.

### Outro (1 paragraphe)

- Teaser pour les articles suivants : « la suite couvre le pivot OTOCO suite à un bug Binance, et l'industrialisation avec une chaîne de 3 agents Claude qui se passent le relais en CI ».
- Lien vers le repo GitHub.
- Petit disclaimer trading : « ne reproduisez pas ça avec de l'argent que vous ne pouvez pas perdre. Le bot a déjà eu des cycles qui plantaient. »

---

## Matériel à préparer avant publication

- [ ] **Capture Telegram** : notif d'un cycle complet (Phase 0 → résumé). Cacher les montants si besoin.
- [ ] **Capture du fichier `prompts/trade_prompt.txt`** dans l'IDE (juste l'arborescence des PHASE pour montrer la structure).
- [ ] **Diagramme architecture** : `docs/visuals/architecture.svg` → vérifier qu'il est à jour avec la nouvelle arbo `binance-bot/`.
- [ ] **Lien GitHub** vers le MCP TradingView utilisé (à retrouver — pas dans `.mcp.json` du repo).
- [ ] **Vérifier les chemins de code cités** (`binance-bot/orchestration/cycle_runner.py` etc.) — l'arbo a changé récemment.

## Questions ouvertes (à trancher avant rédaction finale)

1. **Inclure ou pas un snippet du `TRADE_PROMPT` complet ?** Pro : transparence. Contre : 600 lignes c'est long, ça casse le rythme. Décision provisoire : juste 3 extraits courts (Phase 1, Phase 5, fonction `tg()`).

2. **Mentionner les coûts ?** « ~0.10 $ par cycle Claude API, gratuit en abonnement ». Pro : utile pour le lecteur. Contre : ça date vite.

3. **Mentionner que c'est mon bot perso qui trade vraiment ?** Pro : crédibilité. Contre : ça peut être lu comme un pitch trading. Décision provisoire : oui, mais dans le hook, pas dans l'outro.

4. **Captures d'écran ou mockups ?** Si captures réelles, brouiller les montants. Si mockups, c'est plus propre mais moins authentique.

5. **Cibler Medium ou aussi dev.to / personal blog ?** Pour rentabiliser l'effort, multi-publication possible. À voir selon ta stratégie audience.

---

## Notes / brouillon libre

(Espace pour griffonner — toutes les idées qui te viennent pendant la rédaction.)

- ...

---

# 📝 DRAFT — Version article à relire et corriger

> Status : **writing** — prose complète, à affiner avant publication.
> Longueur cible : 1800-2200 mots.

---

## J'ai un compte Binance. J'avais besoin de quelqu'un pour le surveiller.

L'idée de départ n'était pas de construire un bot de trading sophistiqué. C'était beaucoup plus simple : j'avais un compte Binance avec quelques positions ouvertes, et **personne pour le surveiller**.

Pas le temps de regarder les graphiques toutes les 4 heures. Pas envie de me réveiller la nuit pour vérifier si un support a tenu. Pas de service d'alertes qui place les ordres à ma place.

Ce que je voulais, c'est un **bot de suivi de compte** — pas un agent de trading autonome. Quelque chose qui surveille le marché à intervalle régulier, évalue si les positions en cours tiennent la route, et passe les ordres nécessaires quand les conditions sont réunies. Avec des stop-loss et des take-profit posés automatiquement pour ne jamais laisser une position sans protection.

Il est 8h54 un mercredi matin. Je reçois quatre notifications Telegram en rafale.

> 📋 **Phase 0** — Portfolio : 412 USDC | Budget dispo : 206 USDC | 2 positions ouvertes | PnL jour : +1.2 USDC
> 📡 **Phase 1** — Sentiment : Strongly Bullish | 14 candidats : BTC, SOL, ATOM, STX, SUI…
> 📊 **Phase 2** — Analyse terminée | BTC 49.7 / BUY / SELL | ATOM 58.5 / BUY / BUY ⭐
> ⚡ **BUY ATOM** | 12.4 USDC @ 6.82 | 🛑 Stop : 6.54 | 🎯 TP : 7.64 | Score : 7/10

Le bot vient de scanner 14 cryptomonnaies, analyser les signaux techniques sur deux timeframes, calculer un sizing basé sur l'ATR, et placer un ordre avec stop-loss et take-profit intégrés — le tout en 6 minutes, sans que j'aie touché à mon ordinateur.

Ce qui me fascine encore, c'est que **le code Python qui orchestre tout ça ne contient aucune logique d'analyse de marché**. Pas de calcul de RSI, pas d'appel à TradingView, pas d'algorithme de scoring. Zéro.

Voici comment c'est possible, et comment le brancher.

---

### L'inversion qui change tout : le code est une coquille, l'IA est le cerveau

La plupart des bots que j'ai croisés suivent le même schéma : du code Python qui appelle des APIs, calcule des indicateurs, applique des règles `if RSI < 30 and MACD > 0 then BUY`. La logique est dans le code. Pour modifier le comportement, on refactore.

Mon bot fonctionne à l'envers. **La logique d'analyse vit dans un fichier texte — un prompt de 600 lignes** injecté à chaque cycle dans un sous-processus Claude CLI. Le code Python ne fait qu'une seule chose : lancer ce sous-processus.

```python
# binance-bot/orchestration/cycle_runner.py
process = subprocess.Popen(
    ["claude", "--print", "--output-format", "stream-json",
     "--dangerously-skip-permissions", prompt],
    stdout=subprocess.PIPE, stderr=err_f,
    text=True, cwd=PROJECT_DIR
)
```

`prompt` est une variable de 29 Ko. Elle contient 8 phases séquentielles qui décrivent exactement ce que Claude doit faire — surveiller le portefeuille, scanner le marché, analyser, scorer, dimensionner les positions, exécuter. Claude lit ça comme un développeur lirait une spec, et l'exécute.

Modifier le comportement du bot, c'est éditer un fichier texte. Ajouter un critère d'analyse, c'est rajouter une ligne dans le prompt. Pas de refactoring.

---

### L'architecture en 5 composants

```
Telegram ←→ webhook_server.py (polling 30s + scheduler 4h)
                    ↓
              subprocess claude
              ↙            ↘
    TradingView MCP      binance-cli
    (données marché)    (ordres réels)
              ↘            ↙
           MongoDB Atlas + fichiers locaux
                    ↓
              Telegram (notifications)
```

**`binance-bot/webhook_server.py`** est le process principal. Il poll l'API Telegram toutes les 30 secondes, répond aux commandes (`/trade`, `/status`, `/perf`), et déclenche automatiquement un cycle de trading toutes les 4 heures sur les clôtures de bougies TradingView.

**Le sous-processus Claude CLI** est lancé à chaque cycle avec le prompt de trading. Il tourne 3 à 8 minutes, exécute les 8 phases, et écrit un rapport complet. C'est lui qui prend les décisions.

**TradingView MCP** est un serveur de protocole MCP connecté à Claude. Il expose 5 outils que Claude peut appeler pour obtenir des données de marché en temps réel.

**`binance-cli`** est un outil en ligne de commande installé en npm. Claude l'appelle via Bash pour placer les ordres sur Binance Spot.

**MongoDB Atlas** stocke l'historique complet de chaque cycle — décisions, ordres, et une explication vulgarisée en français que le bot m'envoie sur commande.

---

### Le prompt : 8 phases, 600 lignes, zéro code de trading

Le fichier `prompts/trade_prompt.txt` est le cœur du bot. Il décrit à Claude ce qu'il doit faire, étape par étape, sans lui donner d'algorithme — il lui donne une méthode.

| Phase | Ce que Claude fait |
|---|---|
| **Phase 0** | Vérifie le portefeuille Binance, calcule le budget disponible, réconcilie les trades ouverts vs les ordres actifs |
| **Phase 1** | Lance 4 screeners TradingView en parallèle pour construire l'univers de coins à analyser |
| **Phase 2** | Analyse chaque coin sur les timeframes 4h et 1d (RSI, MACD, ADX, signal directionnel) |
| **Phase 3** | Score chaque coin de 0 à 10, applique les filtres (corrélation, liquidité, positions max) |
| **Phase 4** | Calcule le sizing (risque 1% du portfolio, stop-loss à 2× ATR, TP à ratio 3:1) |
| **Phase 5** | Place les ordres OTOCO atomiques sur Binance (BUY + TP + SL en un seul appel) |
| **Phase 6** | Génère un rapport Markdown dans `reports/` |
| **Phase 7** | Persiste le cycle complet dans MongoDB avec une explication en français |

La séquentialité n'est pas un détail. À la fin de chaque phase, Claude m'envoie une notification Telegram. Je peux suivre le raisonnement en direct. Si ça plante en Phase 3, je sais exactement où chercher dans les logs — pas besoin de redémarrer le scan depuis le début.

Le prompt contient 4 substitutions automatiques faites par le code Python avant l'injection :

```
__BOT_TOKEN__  →  token Telegram
__CHAT_ID__    →  mon chat ID Telegram
__PROJECT_DIR__ → chemin absolu du projet
__CYCLE_ID__   → timestamp du cycle YYYYMMDD_HHMMSS
```

Ces 4 lignes, c'est tout le "code" que le serveur injecte dans le prompt. Le reste est du langage naturel.

---

### MCP : l'USB du LLM

Pour que Claude puisse scanner le marché, il lui faut des données. Pas question d'écrire un wrapper TradingView en Python — j'utilise le **Model Context Protocol (MCP)**.

MCP est un protocole standard qui permet à n'importe quel LLM de découvrir et utiliser des outils externes via un serveur dédié. Le modèle voit les outils disponibles comme il verrait une liste de fonctions dans une doc API. Il les appelle en langage naturel — via la convention `mcp__server__tool` — et reçoit les résultats en JSON structuré.

Dans mon projet, le **MCP TradingView** expose 5 outils que Claude utilise directement dans le prompt :

| Outil | Ce qu'il retourne |
|---|---|
| `mcp__tradingview__top_gainers` | Coins en plus forte hausse sur 24h |
| `mcp__tradingview__volume_breakout_scanner` | Coins avec volume anormalement élevé |
| `mcp__tradingview__market_sentiment` | Score de sentiment global du marché |
| `mcp__tradingview__rating_filter` | Coins notés BUY ou STRONG_BUY |
| `mcp__tradingview__coin_analysis` | Analyse technique complète (RSI, MACD, ADX) |

Dans le prompt, Phase 1 ressemble à ça :

```
PHASE 1 — SCAN MARCHÉ (tout en parallèle)
Lance simultanément :
- mcp__tradingview__top_gainers (exchange: BINANCE)
- mcp__tradingview__volume_breakout_scanner (exchange: BINANCE)
- mcp__tradingview__market_sentiment
- mcp__tradingview__rating_filter (exchange: BINANCE, rating: BUY)
```

Claude lit ces noms d'outils comme un développeur lirait une doc. Pas de SDK, pas d'import, pas de wrapper à écrire ou maintenir. Le serveur MCP gère l'authentification, le rate limiting, et la sérialisation des données.

La configuration côté projet tient en quelques lignes dans `.mcp.json`. Le MCP TradingView est configuré côté utilisateur Claude Code (pas dans le repo) — c'est la différence entre un MCP *projet* (partagé avec l'équipe) et un MCP *utilisateur* (personnel, sur ta machine).

---

### Le skill binance : donner à Claude la doc de son outil

Claude sait utiliser des outils en ligne de commande, mais il ne connaît pas `binance-cli` par défaut. Il faut lui fournir la documentation opérationnelle.

C'est le rôle du **skill binance** : un fichier markdown dans `.agents/skills/binance/SKILL.md` qui documente toutes les commandes disponibles — Spot, Futures, Convert, ordres OCO, gestion des profils — avec les flags, les cas limites et les règles de sécurité.

Ce skill est une **extension de contexte**, pas du code. Claude Code le lit au démarrage de chaque session et sait ainsi qu'il peut appeler :

```bash
binance-cli spot post-order \
  --symbol ATOMUSDC --side BUY \
  --type LIMIT --quantity 12.4 \
  --price 6.82 --timeInForce GTC \
  --profile agent-profile
```

...avec les bonnes options, dans le bon ordre, en gérant les cas d'erreur documentés.

Le skill est installé une fois via `skills-lock.json` (l'équivalent d'un `package.json` pour les skills Claude Code). Il est versionné dans le repo et partagé avec tous les agents du projet.

---

### Créer son bot Telegram en 5 minutes

Toutes les notifications passent par Telegram. Deux éléments suffisent.

**Le token du bot — @BotFather**

1. Ouvre Telegram, cherche `@BotFather`.
2. Envoie `/newbot`, choisis un nom ("Mon bot de trading") et un username (doit finir en `_bot`).
3. BotFather te renvoie un token du type `123456789:ABCdef...`. C'est `TELEGRAM_TOKEN` dans `.env`.

**Ton chat ID — @userinfobot**

1. Cherche `@userinfobot` dans Telegram.
2. Envoie `/start` — il te répond avec ton user ID numérique. C'est `TELEGRAM_CHAT_ID` dans `.env`.

Le bot filtre toutes les commandes entrantes sur ce chat ID. Même si quelqu'un trouve l'username du bot, il ne peut rien déclencher.

Note importante sur l'architecture réseau : le bot fonctionne uniquement en **polling** — il interroge l'API Telegram toutes les 30 secondes. Pas de webhook, pas de port ouvert, pas de tunnel Cloudflare. C'est un choix délibéré : mon réseau d'entreprise bloque les connexions entrantes. Le polling passe partout.

---

### Les commandes disponibles aujourd'hui

Une fois le bot lancé, toute l'interaction passe par Telegram. Sept commandes sont disponibles :

| Commande | Ce qu'elle fait |
|---|---|
| `/trade` | Lance immédiatement un cycle complet d'analyse et de suivi |
| `/status` | Affiche le portefeuille Binance en temps réel (solde, positions ouvertes, ordres en attente, heure du prochain cycle automatique) |
| `/perf` | Statistiques sur tous les trades fermés : win rate, espérance de gain, Sharpe annualisé, drawdown max, p-value |
| `/raisonnement` | Explication en français vulgarisé du dernier cycle (lue depuis MongoDB) — "pourquoi le bot a acheté ATOM et pas SOL ce matin" |
| `/cout` | Historique du coût par cycle (utile pour valider que l'abonnement est bien utilisé, pas l'API pay-per-use) |
| `/eval` | Rapport hebdomadaire : performance des trades, fiabilité des cycles, comparatif coût abonnement vs API |
| `/reset` | Débloque le bot si un cycle précédent s'est arrêté anormalement (remet le verrou à zéro) |

Le bot répond aussi automatiquement à chaque fin de phase pendant un cycle, sans qu'on envoie rien.

---

### Le scheduler 4h : surveiller sans être là

Le vrai intérêt d'un bot de suivi, c'est qu'il tourne **sans intervention humaine**. Pas de cron système, pas de tâche planifiée externe — l'auto-scheduler est intégré directement dans la boucle principale du bot.

Toutes les 30 secondes, après avoir traité les commandes Telegram, le bot calcule l'heure du prochain slot d'analyse et vérifie si c'est le moment de lancer :

```python
# binance-bot/core/timing.py
def next_4h_slot() -> datetime:
    """Prochain slot 4h UTC + 5 min (aligné sur clôtures TradingView)."""
    slot_hour = (now.hour // 4) * 4
    nxt = now.replace(hour=slot_hour, minute=5, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(hours=4)
    return nxt
```

Les 6 slots quotidiens sont **00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC**. Le décalage de 5 minutes après la clôture exacte de la bougie laisse le temps à TradingView de consolider les indicateurs.

Pourquoi ces horaires précis ? Parce que les signaux TradingView (RSI, MACD, ADX) sont calculés sur des bougies closes. Lancer l'analyse à 04:00 UTC — soit en pleine bougie ouverte — donnerait des signaux provisoires. Attendre 04:05, c'est travailler sur des données stables.

Le /status le confirme à chaque fois :

> ⏰ Prochain cycle auto : **aujourd'hui à 20:05 (heure locale)**

---

### Zéro surcoût : l'abonnement Claude Code à la place de l'API

C'est un point qui mérite d'être explicite, parce qu'on suppose souvent que faire tourner un LLM en production coûte cher à l'usage.

Ce bot utilise **Claude Code avec un abonnement fixe** (20 €/mois ou l'abonnement Max), pas l'API Anthropic pay-per-use. La différence est importante :

- **API pay-per-use** : on paie par token. Un cycle d'analyse complet consomme entre 50 000 et 150 000 tokens. Au tarif Sonnet 4.6, ça représente ~0,10 à 0,30 $ par cycle, soit ~1,80 $ par jour pour 6 cycles. Sur un mois, ~55 $.
- **Abonnement Claude Code** : forfait mensuel fixe. Les cycles de trading consomment du quota d'abonnement, mais aucun coût variable supplémentaire.

Comment c'est implémenté ? Le code **interdit explicitement** l'injection de `ANTHROPIC_API_KEY` dans le processus :

```python
# binance-bot/webhook_server.py
KEYS_NEVER_LOAD = {"ANTHROPIC_API_KEY"}

def _load_env():
    for key, val in env_vars:
        if key in KEYS_NEVER_LOAD:
            continue  # force l'abonnement, pas l'API
        os.environ.setdefault(key, val)
```

Sans cette clé dans l'environnement, Claude CLI utilise automatiquement la session OAuth de l'abonnement connecté (`claude login`). Si le quota journalier est épuisé, le bot envoie une alerte Telegram et skip le cycle — pas de fallback API surprise.

Le modèle est fixé explicitement sur Sonnet 4.6 (l'abonnement pourrait choisir Opus par défaut, beaucoup plus lent) :

```python
CLAUDE_CLI_FLAGS = [
    "--model", "claude-sonnet-4-6",
    "--print", "--verbose",
    "--output-format", "stream-json",
    "--dangerously-skip-permissions",
]
```

---

### Le setup complet (checklist)

Pour avoir un bot fonctionnel :

**1. Prérequis**
```bash
# Claude Code (CLI)
npm install -g @anthropic-ai/claude-code

# binance-cli
npm install -g @binance/binance-cli

# Python 3.11 avec venv
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # pymongo, loguru
```

**2. Configurer Binance**
```bash
binance-cli profile create \
  --name agent-profile \
  --api-key TON_API_KEY \
  --api-secret TON_API_SECRET \
  --env prod
```
Permissions API requises : Spot trading. Pas besoin de retrait.

**3. Configurer `.env`**
```env
TELEGRAM_TOKEN=123456789:ABCdef...    # @BotFather
TELEGRAM_CHAT_ID=987654321            # @userinfobot
MONGODB_URI=mongodb+srv://...         # Atlas M0 gratuit
MONGODB_DB=agent-binance
```

**4. Lancer**
```bash
nohup .venv/bin/python -u binance-bot/webhook_server.py \
  >> state/daemon.log 2>&1 &
```

Envoie `/status` sur Telegram — le bot répond en moins de 5 secondes.

---

### Pourquoi cette architecture tient en production

**Le code est une coquille, pas le cerveau.** Cette inversion change tout. Ajouter un indicateur technique au scoring ? 2 lignes dans `prompts/trade_prompt.txt`. Modifier le critère de sélection des coins ? Un paragraphe dans la Phase 3. Zéro déploiement, zéro refactoring.

**Le MCP est un standard, pas une lib.** Pas de wrapper TradingView à écrire, maintenir, ou mettre à jour quand l'API change. Le modèle découvre les outils, les appelle, gère les erreurs. Si TradingView est down, le prompt prévoit : "si analyse non disponible, marque SKIP avec motif `api_error`".

**La séquentialité du prompt rend l'IA observable.** 8 phases avec une notification Telegram à la fin de chacune, c'est l'équivalent d'un debugger pour LLM. Quand un cycle plante, je sais en quelques secondes à quelle phase et pourquoi — sans fouiller 500 lignes de code.

---

### La suite

Ce bot de suivi est fonctionnel, mais deux problèmes se posent rapidement dès qu'on commence à le faire évoluer.

**Le premier est technique.** Binance interdit de poser un stop-loss sur un actif qu'on ne détient pas encore. Quand on place un BUY LIMIT qui n'est pas encore rempli, le SELL de protection est rejeté immédiatement. La position reste ouverte sans filet. Le prochain article couvre ce pivot — de 3 appels API séparés vers un ordre OTOCO atomique (One-Triggers-OCO) qui place l'entrée, le take-profit et le stop-loss en un seul appel atomique.

**Le second est organisationnel.** Dès qu'on commence à itérer sérieusement — corriger des bugs, ajouter des features, améliorer le prompt — on se retrouve à répéter les mêmes actions manuellement : créer un ticket GitHub, ouvrir une branche, écrire du code, ouvrir une PR, faire la review. La deuxième partie de la série couvre la mise en place d'une chaîne de 3 agents Claude qui automatisent ce workflow de développement :

- **`ticket-manager`** — transforme n'importe quelle idée ou bug en issue GitHub structurée sur le board de projet
- **`binance-dev`** — prend un ticket "In progress", crée la branche, implémente, ouvre la PR
- **`tech-lead-reviewer`** — review automatique du code (ruff, radon, bandit, mypy), note de maintenabilité 0-10, commentaire structuré sur la PR

Ces trois agents tournent en local dans Claude Code et en CI via GitHub Actions. Développer le bot ressemble à travailler avec une petite équipe — sans en avoir une.

Le code est open source : [github.com/yousmaaza/agent-binance](https://github.com/yousmaaza/agent-binance).

*Disclaimer : ce bot surveille un compte réel et passe des ordres réels. Il a déjà eu des cycles qui plantaient. Ne le déployez pas avec de l'argent que vous ne pouvez pas perdre.*
