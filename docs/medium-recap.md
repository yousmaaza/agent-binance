# Récap pour article Medium — agent-binance

Document de travail (non publié) pour structurer un article Medium sur la mise en place du projet. Chronologie reconstituée depuis l'historique git.

**Période couverte** : 19 → 21 mai 2026 (3 jours, 23 commits, ~6 900 lignes ajoutées).

**Stack finale** : Python 3.11 mono-fichier, Telegram polling, Claude CLI en subprocess, Binance Spot via OTOCO, TradingView via MCP, MongoDB Atlas, GitHub Actions pour la CI/review.

---

## Introduction (à enrichir par toi)

À écrire en intro : ton angle personnel — pourquoi tu as lancé ce projet, ton rapport au trading, ce qui t'a poussé à le coder toi-même plutôt que d'utiliser un bot existant. Mentionne que c'est un projet **personnel** (pas pour vendre du trading-as-a-service), une expérience qui combine ingénierie logicielle moderne (agents IA, CI/CD, observabilité) et trading systématique.

Idée d'accroche : « En 72 heures, j'ai construit un bot de trading crypto qui s'auto-debug, s'auto-review, et s'auto-documente. Voici ce que j'ai appris. »

---

## Étape 1 — POC : du script qui poll Telegram à la première trade

**Date** : 19 mai 2026 — commits `b05f075`, `314ea8e`.

**Le problème.** Je voulais un bot qui scanne le marché, prenne des décisions de trading, et m'envoie un résumé sur Telegram. Toutes les solutions existantes (3commas, freqtrade, etc.) sont soit chères, soit overkill, soit limitées à une stratégie figée.

**La décision technique.** Faire le bot le plus simple possible :
- Un seul fichier Python (`webhook_server.py`).
- Telegram en polling (pas de webhook entrant, pas de tunnel, pas de port ouvert).
- L'intelligence est entièrement déléguée à un sous-processus Claude CLI lancé à la demande.
- Auto-scheduler interne, pas de cron système.

**Le résultat.** Une release v2 immédiatement : scoring multi-timeframe 4h+1d, exécution BUY+SL+TP, auto-scheduler aligné sur les clôtures 4h TradingView, journal des trades avec `/perf` (winrate, Sharpe, p-value t-test).

**Angle narratif.** Le bot ne fait pas le trading lui-même — il sert d'orchestrateur léger autour d'un LLM qui décide. Cette inversion (l'IA est le cerveau, le code est la coquille) change tout : ajouter une nouvelle stratégie, c'est éditer un prompt, pas refactor 500 lignes.

---

## Étape 2 — Visibilité : capturer le raisonnement de l'IA

**Date** : 20 mai 2026 — commit `790b83a`.

**Le problème.** Au bout de quelques cycles, je me suis retrouvé devant un bot qui prenait des décisions… que je ne pouvais pas expliquer. Pourquoi a-t-il acheté STX et pas SOL ce matin ? Aucune trace. Juste un trade dans mon historique.

**La décision technique.** Trois couches d'observabilité :
1. **Logs locaux par cycle** : stdout et stderr de chaque sous-processus Claude écrits dans `logs/stdout/cycle_<id>.log` et `logs/stderr/cycle_<id>.log`. Identifiant horodaté UTC.
2. **MongoDB Atlas** : à la fin de chaque cycle, Claude persiste un document structuré contenant les décisions par coin, les scores, les ordres, et — surtout — un champ `explanation_fr` en français vulgarisé.
3. **Commande `/raisonnement`** : lit le dernier cycle dans Mongo et m'envoie l'explication sur Telegram.

**Angle narratif.** Demander à l'IA de **se raconter** est aussi important que la décision elle-même. Le `explanation_fr` est ce qui m'a permis de faire confiance au bot et de l'améliorer.

---

## Étape 3 — Conventions : naissance de `CLAUDE.md`

**Date** : 20 mai 2026 — commit `2bf48c0`.

**Le problème.** Chaque fois que je relançais une session Claude pour ajouter une feature, l'IA réinventait l'architecture : remplaçait `curl` par `urllib`, hardcodait des chemins, oubliait que les ordres doivent être passés en UTC. Régression à chaque modification.

**La décision technique.** Créer un fichier `CLAUDE.md` à la racine du projet qui contient :
- Les règles non négociables (curl-only pour Telegram, secrets via `.env` uniquement, `PROJECT_DIR` dynamique, UTC interne / local pour l'affichage).
- Les pièges connus (réseau corporate qui bloque QUIC, IPv6 sans connectivité, etc.).
- Le workflow type d'une modification (test syntaxe, redémarrage du bot, vérification du startup).

Ce fichier est lu automatiquement par Claude Code à chaque session — il devient le "passé partagé" entre l'utilisateur et l'IA.

**Angle narratif.** `CLAUDE.md` est l'équivalent du `CONTRIBUTING.md` pour une équipe humaine, mais à destination d'une IA. Ça transforme l'IA d'exécutante en collègue qui se souvient des décisions passées.

---

## Étape 4 — Le bug Binance : pivot vers OTOCO

**Date** : 21 mai 2026 — commit `a45443a`.

**Le problème.** Trois trades passés un matin (BTC, STX, SOL) : `entry_order_id` bien rempli, mais `stop_order_id` et `tp_order_id` à `null`. Le bot avait acheté sans poser de filets de sécurité. Cause : Binance Spot interdit de placer un SELL sur un actif qu'on ne détient pas encore — donc tant que le BUY LIMIT n'est pas rempli, impossible d'armer le stop-loss et le take-profit.

**La décision technique.** Bascule de 3 appels API séparés vers un seul ordre **OTOCO** (One-Triggers-OCO) :
- Working order : BUY LIMIT au prix d'entrée.
- Pending above : LIMIT_MAKER au take-profit.
- Pending below : STOP_LOSS_LIMIT au stop.

Un seul appel atomique. Dès que le BUY est rempli, Binance arme automatiquement le TP+SL en OCO (l'un annule l'autre).

**Angle narratif.** Le bug a forcé à **lire la doc Binance plus profondément**. Ce qui semblait être une limitation absurde était en réalité une primitive (`order-list-otoco`) qu'on n'avait pas vue. Leçon : avant d'inventer une réconciliation à base de polling, vérifie si l'exchange propose déjà la primitive atomique.

---

## Étape 5 — Streaming logs : voir Claude en direct

**Date** : 21 mai 2026 — commit `a45443a` (même PR que l'OTOCO).

**Le problème.** Pendant qu'un cycle tournait (3 à 8 minutes), je n'avais aucune visibilité sur ce que faisait Claude. Le fichier `logs/stdout/cycle_<id>.log` n'était écrit qu'à la fin, et ne contenait que la réponse finale — pas les actions intermédiaires (tool calls, résultats Binance, MCP TradingView).

**La décision technique.** Trois changements :
1. `subprocess.run(capture_output=True)` → `subprocess.Popen` qui pipe stdout directement.
2. Passer Claude CLI en `--output-format stream-json` qui émet un événement JSON par ligne (un event = un tool call, ou un message, ou un result).
3. Parser inline en Python qui transforme chaque ligne JSONL en ligne lisible avec timestamp et émoji (`🔧 Bash`, `✅ tool_result`, `💬 message`, `🏁 done`).

Résultat : `tail -f logs/stdout/cycle_<id>.log` montre maintenant le déroulé temps réel du cycle.

**Angle narratif.** Le streaming a transformé l'IA de boîte noire en **collègue qui pense à voix haute**. Quand le bot prend une décision étrange, je peux maintenant la voir se former en direct.

---

## Étape 6 — De l'abonnement à l'API : pay-per-use

**Date** : 21 mai 2026 — commit `a45443a`.

**Le problème.** Au premier cycle qui a planté, l'erreur était claire : `You've hit your session limit · resets 1:20pm`. Mon abonnement Claude Code personnel sert aussi à mon travail quotidien — pas question qu'un cycle de trading mange mon quota.

**La décision technique.** Ajouter `ANTHROPIC_API_KEY` dans `.env`. Quand cette variable est présente, le sous-processus Claude bascule automatiquement en pay-per-use via l'API au lieu de consommer le quota OAuth de la session connectée. Fallback automatique si la clé est absente.

**Angle narratif.** Une ligne dans `.env` qui sépare deux dimensions économiques : ce que je consomme pour mon travail (forfait fixe) et ce que je consomme pour mes projets perso (au cycle, ~0.10 $). Cette frontière budgétaire a rendu le bot honnête vis-à-vis de mes vrais coûts.

---

## Étape 7 — Industrialisation : agents Claude + GitHub Actions

**Date** : 21 mai 2026 — commits `361eec5`, `154562a`, `a6c6c84`, `805332c`.

**Le problème.** Au-delà de quelques features, je me suis retrouvé à répéter les mêmes prompts à Claude :
- « Crée un ticket pour cette idée sur le board GitHub. »
- « Review cette PR avant que je merge. »
- « Implémente le ticket #14, écris une PR. »

**La décision technique.** Créer une famille d'**agents Claude Code locaux**, chacun avec une responsabilité unique :

- **`ticket-manager`** : convertit n'importe quel plan en issues GitHub structurées (epic + sous-tickets, board #4, status/priority/size, relation parent/enfant via GraphQL).
- **`binance-dev`** : prend un ticket "In progress" du board, crée la branche `feat/issue-<N>-<slug>`, code la feature, ouvre la PR liée. Invoque `feature-dev` pour le cadrage avant code.
- **`tech-lead-reviewer`** : review Python (ruff + radon + bandit + mypy) sur les fichiers modifiés, calcule une note de maintenabilité 0-10 via barème pondéré, poste un commentaire structuré sur la PR.
- **Workflow GitHub Actions** : sur chaque PR ouverte, déclenche automatiquement `tech-lead-reviewer` en CI avec Sonnet (max 40 turns, budget 2 $).
- **Workflow post-review** : si la review trouve des bloquants → un job Claude les corrige automatiquement et push. Si elle trouve des recommandations → un autre job crée des tickets `[REC]` P2 sur le board.

**Angle narratif.** Le projet a maintenant une **chaîne d'agents qui se passent le relais** : un plan devient des tickets, un ticket devient une PR, une PR est reviewée par un tech lead virtuel, les bloquants sont fixés automatiquement, et le reste devient des tickets dans le backlog. C'est la version IA d'une équipe de dev de 5 personnes.

---

## Étape 8 — Discipline d'environnement : `.venv` + `git-perso`

**Date** : 21 mai 2026 — commit `e972055`.

**Le problème.** Sur la même machine, j'ai un compte Git pro et un compte Git perso. Quand Claude lançait `git commit` ou `pip install`, il utilisait parfois le mauvais index pip (corporate) ou attribuait le commit au mauvais compte.

**La décision technique.** Deux règles ajoutées dans `CLAUDE.md` :
1. Tout `python`/`pip` passe par le venv local `.venv` (Python 3.11, recréé sur chaque machine).
2. Tout `git`/`gh` qui touche au remote passe par `git-perso` (un alias shell perso qui configure `user.email`, `user.name`, `signingkey` et l'index pip).

L'agent `binance-dev` vérifie ces deux conditions en Phase 0 et refuse de continuer si elles ne sont pas satisfaites.

**Angle narratif.** L'environnement de dev est un sujet souvent négligé dans les projets perso. Le coder dans `CLAUDE.md` (donc dans le contexte de l'IA) garantit que **chaque action future** sera conforme. Plus de commit pollué par accident.

---

## Étape 9 — Documentation vivante

**Date** : 21 mai 2026 — commits `054dc1f`, `b15acc8`, `89787dc`, `38f0cd2`.

**Le problème.** Le code grossissait, le `CLAUDE.md` aussi, mais aucune doc utilisateur ni doc d'architecture. Je passais 10 minutes à fouiller mes propres scripts pour expliquer à un ami ce que faisait le bot.

**La décision technique.** Trois piliers :
1. **`docs/fonctionnel/`** : un fichier markdown par commande Telegram (`trade.md`, `status.md`, `perf.md`, `raisonnement.md`, `reset.md`, `auto-scheduler.md`). Index auto-géré, miroir GitHub Wiki.
2. **`docs/technique/`** : un `SPEC.md` global mis à jour à chaque PR mergée, plus un fichier `pr-<N>-<slug>.md` par PR pour tracer l'historique technique.
3. **Deux agents documentaires** : `binance-doc-fonc` créé après chaque `ExitPlanMode` (nouvelle feature), `binance-doc-tech` déclenché en GitHub Actions à chaque PR mergée.

S'ajoute la couche visuelle : **diagrammes D2 + Kroki.io** (6 visuels : architecture, data-flow, commands, trade-phases, trade séquence, auto-scheduler), embarqués dans le `SPEC.md` et les docs fonctionnelles.

**Angle narratif.** La doc n'est plus une corvée post-feature : elle est générée par un agent au moment où la feature est cadrée (planning) et au moment où elle est mergée (PR). Le code et la doc évoluent en synchronisation, sans effort humain conscient.

---

## Bilan — Ce qui a changé en 72 heures

**Ligne par ligne** :
- 6 900 lignes ajoutées sur 76 fichiers.
- 23 commits, 1 PR mergée.
- ~750 lignes de code applicatif (`webhook_server.py`).
- Le reste : agents (`.claude/`), workflows (`.github/`), docs (`docs/`), prompts.

**Côté humain** :
- Temps total : environ 25-30 heures sur 3 jours.
- Coût Claude API : ~15 $ (cycles de trading + agents + reviews CI).
- Aucun test unitaire. La feature, c'est la commande qui arrive sur Telegram et la notif qui repart.

**Trois apprentissages** :

1. **Le code est une coquille, pas le cerveau.** Quand tu délègues l'intelligence à un LLM, ton job devient designer de prompts et d'agents, pas développeur d'algorithmes. Le code python pur représente moins de 15 % du repo final.

2. **Les conventions sont plus importantes que le code.** `CLAUDE.md` est probablement le fichier le plus précieux du projet. Sans lui, chaque session repart de zéro et casse les invariants.

3. **L'automatisation ne s'arrête pas au déploiement.** Review automatique, fix automatique des bloquants, création automatique de tickets, doc automatique : il y a 10 ans, c'était SRE et tech lead. Aujourd'hui, c'est un fichier `.yml` + un agent.

---

## Points narratifs forts (à choisir pour l'angle Medium)

Plusieurs angles possibles pour ton article, à choisir selon ton audience :

### Angle 1 — « J'ai laissé une IA coder mon bot de trading pendant 3 jours »
Ton : storytelling, défi 72h. Insister sur le bug OTOCO, le streaming logs, le pivot pay-per-use. Public : large, devs curieux.

### Angle 2 — « Comment j'ai industrialisé un projet perso comme une équipe de 5 »
Ton : technique, agents + CI/CD. Insister sur l'étape 7 (agents qui se passent le relais). Public : tech leads, devs senior.

### Angle 3 — « La fin du code : 85 % de mon repo n'est pas du Python »
Ton : provocateur, méta. Insister sur le ratio code/agents/docs. Public : observateurs du dev moderne.

### Angle 4 — « OTOCO, streaming, et autres trous noirs que j'ai découverts en 72h »
Ton : leçons apprises, format "ce que j'aurais aimé savoir". Public : devs qui démarrent un projet d'API exchange ou un projet LLM en subprocess.

### Angle 5 — « CLAUDE.md, ou comment apprivoiser une IA en 100 lignes »
Ton : focalisé sur le fichier de conventions. Insister sur l'étape 3. Public : early adopters de Claude Code / Cursor / Aider.

---

## Matériel disponible pour illustrer

- Screenshots Telegram (cycle en cours, notifs OTOCO, /perf, /raisonnement)
- Logs streaming (`logs/stdout/cycle_*.log` après bascule stream-json)
- Diagrammes D2 (`docs/visuals/architecture.svg`, `trade-phases.svg`, etc.)
- Snippets de code clé : la fonction `_format_stream_event`, le bloc OTOCO du prompt, le frontmatter de `tech-lead-reviewer.md`
- Tableau du board GitHub avec issues créées par `ticket-manager`

---

## Notes de rédaction

- Évite le ton trop technique en intro : commence par le **résultat** (un bot qui trade, qui se review, qui se documente) avant les détails d'implémentation.
- Chaque étape se prête bien à un format "Problème → Décision → Résultat" qui se lit vite.
- Si tu veux 1500-2000 mots : prends 5-6 étapes et le bilan.
- Si tu veux 3000+ mots : prends les 9 étapes + un appendix code.
- Tag Medium suggérés : `Python`, `Trading`, `Claude AI`, `Automation`, `DevOps`.
