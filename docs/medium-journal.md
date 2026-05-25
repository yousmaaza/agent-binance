# Journal quotidien — agent-binance

Récaps quotidiens auto-générés par l'agent `daily-recap` (PR mergées, issues fermées, nouveaux tickets, angles narratifs). Matière première pour des articles Medium réguliers.

**Trigger 1** : slash command `/journal` lancée manuellement par l'utilisateur (mode interactif, pas de commit auto).

**Trigger 2** : routine Claude Code remote (cron `0 21 * * *` UTC = 23h Europe/Paris) qui tourne chaque soir et commit+push le récap du jour sur la branche dédiée `doc/medium-report` (pas main). Pilotée depuis https://claude.ai/code/routines.

Les entrées les plus récentes sont en haut. Le fichier de référence chronologique du projet reste `docs/medium-recap.md` (récap des 9 étapes structurantes du POC à v2, couvre la période 19→21 mai 2026).

---

## 2026-05-25 — Récap quotidien

### PR mergées (1)

#### #106 — [OPT] Phase 1 filtre USDC non tradables + Phase 2 appels 1D couplés par coin
- **Mergée à** : matin (heure exacte n/a — snapshot rétro)
- **Quoi** : double optimisation du scan marché. Phase 1 filtre désormais en amont les coins non tradables en USDC sur Binance (évite des appels morts vers TradingView). Phase 2 couple les analyses 4h et 1d par coin (un seul aller-retour MCP par candidat au lieu de deux).
- **Pourquoi c'est intéressant pour Medium** : optim de latence assez classique mais qui illustre un pattern récurrent — un cycle qui prenait 5-8 min est progressivement trimé à 3-4 min sans changer la stratégie. Bon exemple de "petites optims qui s'additionnent".

### Issues fermées (1)
- **#105** — [M104] Filtre USDC + 1D séquentiel

### Nouveaux tickets (n/a)
Snapshot rétro : non collecté en détail.

### Matériel disponible pour l'article
- **Diff** : `git show 92a68a2 --stat -- '*.py' '*.json'`
- **Doc tech** : `docs/technique/pr-106-*.md` (généré par binance-doc-tech)

### Idée d'angle Medium
"L'art de tailler les latences sans changer la stratégie" — comment 4 PR d'opti étalées sur 4 jours (#100, #104, #106) ont divisé par 2 le temps de cycle, en attaquant uniquement la couche scan/analyse.

---

## 2026-05-24 — Récap quotidien

### PR mergées (2)

#### #100 — [M99] Supprimer le fallback API — ne pas charger ANTHROPIC_API_KEY dans le bot
- **Quoi** : retrait du chemin de bascule abonnement→API. Le bot tourne désormais en abonnement Claude Code exclusivement. La variable `ANTHROPIC_API_KEY` n'est plus lue par le runtime.
- **Pourquoi c'est intéressant pour Medium** : un revirement assumé. 48h plus tôt (22 mai), le fallback API avait été ajouté comme filet de sécurité. Avec le recul, il introduisait une asymétrie de coût et de complexité. Le retirer simplifie la facturation et le debug. Pattern "supprimer ce qu'on a ajouté hier" = signe de maturité, pas de gaspillage.

#### #104 — [M103] Optimiser Phase 2 — appel 1D filtré sur candidats 4h BUY
- **Quoi** : Phase 2 ne lance plus l'analyse 1d sur tous les coins de l'univers, mais uniquement sur ceux qui ont déjà un signal 4h BUY ou STRONG_BUY. Pour les autres, on saute directement à la décision HOLD/SKIP.
- **Pourquoi c'est intéressant pour Medium** : exemple de filtre en cascade qui réduit les appels MCP de ~50%. Bonus narratif : ce changement vient d'une review tech-lead-reviewer qui avait flaggé la duplication d'analyse.

### Issues fermées (2)
- **#99** — fermée par #100
- **#103** — fermée par #104

### Idée d'angle Medium
"Supprimer ce qu'on a ajouté hier" — la PR #100 retire le fallback API ajouté 48h plus tôt par #50. Article court sur l'importance d'oser défaire ses propres décisions quand le contexte change.

---

## 2026-05-23 — Récap quotidien

### PR mergées (5)

#### #80 — [M79] Forcer claude-sonnet-4-6 sur abonnement et API fallback
- **Quoi** : pin explicite du modèle Sonnet 4.6 dans tous les appels Claude (subprocess principal + agents). Évite que la CLI choisisse automatiquement Haiku ou Opus selon le contexte.

#### #82 — [M81] Afficher modèle et mode (abonnement/API) dans les notifications de cycle
- **Quoi** : chaque notification Telegram de démarrage de cycle indique désormais quel modèle Claude tourne et en quel mode (abonnement vs API).
- **Pourquoi c'est intéressant** : transparence sur ce qui consomme quoi. Petit changement, gros impact ergonomique.

#### #87 — [M86] Migrer agents et workflows CI/CD vers claude-haiku
- **Quoi** : bascule des workflows CI (tech-lead-reviewer, doc-tech, post-review) sur claude-haiku-4-5. Sonnet reste sur le bot de trading où la qualité de décision prime.
- **Pourquoi c'est intéressant pour Medium** : différenciation explicite entre tâches "à enjeu" (Sonnet) et tâches "outillage" (Haiku, ~10x moins cher). Pattern de cost-engineering pertinent pour tout projet LLM.

#### #91 — [M90] Commande /eval : rapport performance + coût abonnement vs API
- **Quoi** : nouvelle commande Telegram `/eval` qui produit un rapport comparatif consommation/coût entre les deux modes (abonnement Claude Code vs API pay-per-use).

#### #98 — [M97] Fallback API : reprendre la session Claude via --resume
- **Quoi** : quand le fallback API se déclenche, la session Claude est reprise via `--resume <session-id>` plutôt que repartir de zéro. Préserve le contexte et le travail déjà fait.

### Issues fermées (5)
- **#79**, **#81**, **#86**, **#90**, **#97** (chacune par sa PR)

### Idée d'angle Medium
"Le jour où j'ai mappé les coûts LLM pièce par pièce" — récit de la journée du 23 mai qui a vu l'ajout de la transparence modèle/mode (#82), la migration des workflows sur Haiku (#87), et la commande /eval (#91). Angle cost-engineering pour projets LLM.

---

## 2026-05-22 — Récap quotidien

### PR mergées (6)

#### #43 — [M1] Supprimer écriture orpheline de state/pending_callback.json
- **Quoi** : nettoyage. Le fichier `pending_callback.json` n'était plus utilisé depuis la v2 mais était encore écrit à chaque cycle.

#### #46 — [REC] Ajouter prompt_version dans le fallback Mongo erreur
- **Quoi** : quand un cycle plante et que le fallback Mongo écrit une trace minimale, le champ `prompt_version` (sha1 du prompt) est désormais inclus. Permet de corréler les erreurs à la version exacte du TRADE_PROMPT.

#### #48 — [M1] Suivre le coût API par cycle et exposer via /cout
- **Quoi** : nouvelle commande Telegram `/cout` qui agrège le coût USD par cycle (champ `total_cost_usd` du stream-json Claude) et présente une stats hebdo/mensuelle.

#### #50 — [M1] Fallback abonnement→API Sonnet si ressource insuffisante
- **Quoi** : si le subprocess Claude plante avec un message de type "session limit", le bot retente automatiquement avec `ANTHROPIC_API_KEY` (API pay-per-use). Filet de sécurité contre les blocages d'abonnement.
- **Pourquoi c'est intéressant** : design défensif typique. Ce fallback sera retiré 48h plus tard par #100 — voir cycle de décision côté 24 mai.

#### #56 — [M1] Phase 0 — Trailing stop : remonter le stop-loss si le prix a progressé
- **Quoi** : nouvelle logique en Phase 0. Pour chaque position ouverte, si le prix actuel est > entry_price × 1.02, le stop-loss est remonté à break-even ou au-dessus. Verrouille du gain plutôt que de risquer un retour au stop initial.
- **Pourquoi c'est intéressant pour Medium** : c'est une vraie amélioration de stratégie de trading, pas juste de l'ingénierie. Bonne section technique pour un article orienté finance/trading.

#### #65 — [hotfix] Ajouter session limit dans _RESOURCE_ERROR_PATTERNS
- **Quoi** : extension du pattern matcher d'erreurs de ressource pour inclure "session limit" dans les triggers de fallback API. Hotfix après détection d'un cas non couvert par #50.

### Issues fermées (6)
- **#4**, **#26**, **#47**, **#49**, **#55** (par leurs PR respectives) + 1 hotfix

### Idée d'angle Medium
"Trailing stop, cost tracking, résilience : la journée la plus dense" — 6 PR sur des sujets variés (stratégie, observabilité, résilience). Format possible : "1 journée, 6 leçons" en mode listicle.

---
