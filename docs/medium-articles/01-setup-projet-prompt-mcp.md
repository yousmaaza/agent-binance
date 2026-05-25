---
status: draft
target_length: 1500-2200 mots
target_audience: devs senior curieux des LLM en production, pas forcément traders
tags_medium: [Python, Claude, LLM, MCP, Trading, Automation]
created: 2026-05-25
published_url: ""
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

### Section 5 — Le setup minimal (reproductibilité)

5 étapes pour avoir un bot fonctionnel sur sa machine :

1. **Cloner** : `git clone https://github.com/yousmaaza/agent-binance`
2. **Installer le venv 3.11** + dépendances (`pymongo`, `loguru`).
3. **Configurer `.env`** : `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `MONGODB_URI`. (Notamment **pas** d'`ANTHROPIC_API_KEY` — on utilise l'abonnement Claude Code.)
4. **Configurer `binance-cli`** : profil `agent-profile` avec clés API Binance.
5. **Lancer** : `nohup .venv/bin/python -u binance-bot/webhook_server.py >> state/daemon.log 2>&1 &`

Mentionner : pas de tunnel, pas de port ouvert, pas de webhook entrant. **Polling-only** — ça tourne derrière n'importe quel réseau corporate.

### Section 6 — Pourquoi ça marche (en 3 leçons)

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

(Espace pour griffonner — toutes les idées qui te viennent pendant le brainstorming.)

- ...
- ...
- ...
