# Journal quotidien — agent-binance

Récaps quotidiens auto-générés par l'agent `daily-recap` (PR mergées, issues fermées, nouveaux tickets, angles narratifs). Matière première pour des articles Medium réguliers.

**Trigger 1** : slash command `/journal` lancée manuellement par l'utilisateur (mode interactif, pas de commit auto).

**Trigger 2** : routine Claude Code remote (cron `0 21 * * *` UTC = 23h Europe/Paris) qui tourne chaque soir et commit+push le récap du jour sur la branche dédiée `doc/medium-report` (pas main). Pilotée depuis https://claude.ai/code/routines.

Les entrées les plus récentes sont en haut. Le fichier de référence chronologique du projet reste `docs/medium-recap.md` (récap des 9 étapes structurantes du POC à v2, couvre la période 19→21 mai 2026).

---

## 2026-05-25 — Récap quotidien

### PR mergées (3)

#### #106 — [OPT] Phase 1 filtre USDC non tradables + Phase 2 appels 1D couplés par coin
- **Branche** : `feat/issue-105-filtre-usdc-1d-sequentiel`
- **Mergée à** : 11:48 (Europe/Paris)
- **Volume** : +31 / -14 lignes (`prompts/trade_prompt.txt`)
- **Quoi** : double optimisation du scan marché. Phase 1 ajoute un filtre tradabilité explicite via `binance-cli spot ticker-price` : les coins sans paire USDC valide (STEEM, PEOPLE…) sont éliminés avant tout appel TradingView. Phase 2 regroupe les candidats par groupes de 4 et couple immédiatement l'appel 1D après chaque résultat 4H BUY, plutôt que d'envoyer un second batch massif une fois tous les 4H traités.
- **Pourquoi c'est intéressant pour Medium** : corrige un bug de rate-limit TradingView (`Expecting value: line 1 column 1`) qui n'était pas évident — la cause réelle était un batch de 9 appels 1D en rafale après 14 appels 4H parallèles. Le fix est architecturalement plus fin que le symptôme.
- **Doc tech** : [docs/technique/pr-106-filtre-usdc-couplage-1d.md](../technique/pr-106-filtre-usdc-couplage-1d.md)

#### #117 — ci: skip tech-lead-review et doc-tech sur doc/medium-report
- **Branche** : `ci/skip-doc-medium-report`
- **Mergée à** : 18:33 (Europe/Paris)
- **Volume** : +7 / -1 lignes (2 fichiers YAML CI)
- **Quoi** : ajout de filtres `if:` dans les deux workflows CI (`claude-code-review.yml`, `claude-doc-tech.yml`) pour éviter qu'ils se déclenchent sur la branche `doc/medium-report`. Cette branche accumule uniquement des commits de journal markdown — pas de code Python à reviewer, pas de PR à documenter.
- **Pourquoi c'est intéressant pour Medium** : bonne illustration du coût invisible des workflows CI sur les branches longues. 7 lignes de YAML qui économisent N appels API à chaque commit de routine nocturne.
- **Doc tech** : [docs/technique/pr-117-ci-skip-doc-medium-report.md](../technique/pr-117-ci-skip-doc-medium-report.md)

#### #118 — feat(medium): dossier medium-articles + agent medium-articles-manager + CI skip article/*
- **Branche** : `docs/articles-brainstorm`
- **Mergée à** : 19:01 (Europe/Paris)
- **Volume** : +585 / -5 lignes (6 fichiers)
- **Quoi** : mise en place de l'infrastructure complète pour gérer les articles Medium. Nouvel agent `medium-articles-manager` (277 lignes) qui pilote 3 actions : `/medium new "Titre"` (crée une branche `article/NN-slug`, initialise le brouillon avec frontmatter YAML, ouvre une issue de tracking), `/medium publish NN https://...` (passe le statut à `published`, met à jour l'index README, ferme l'issue), `/medium update-index` (resynchronise le tableau README). Extension du skip CI aux branches `article/*` et `docs/medium-*`. Premier brouillon d'article (`01-setup-projet-prompt-mcp.md`) ajouté en mode plan détaillé.
- **Pourquoi c'est intéressant pour Medium** : méta-sujet — utiliser un agent Claude pour gérer le cycle de vie des articles qui parlent de Claude. La plomberie (branches, frontmatter, index) est automatisée ; la rédaction reste à l'utilisateur. Pattern "agent = tâches répétitives, humain = fond".
- **Doc tech** : [docs/technique/pr-118-medium-articles-workflow.md](../technique/pr-118-medium-articles-workflow.md)

### Issues fermées (3)
- **#105** — [OPT] Phase 1 filtre paires USDC non tradables + Phase 2 appels 1D séquentiels — fermée par PR #106 — [lien](https://github.com/yousmaaza/agent-binance/issues/105)
- **#119** — [ARTICLE] 01 — Setup d'un bot de trading piloté par Claude + MCP TradingView — fermée à 20:56 (issue de tracking article 01, premier article publié) — [lien](https://github.com/yousmaaza/agent-binance/issues/119)
- Aucune autre issue fermée aujourd'hui.

### Nouveaux tickets (9)

Tickets créés aujourd'hui — dont 8 `[REC]` auto-créés par `tech-lead-reviewer` (auteur : `github-actions[bot]`) suite à la review PR #107, et 1 ticket utilisateur :

- **#108** — [REC] Clarifier la mécanique de fusion du journal (insertion vs remplacement) — `enhancement` — auteur github-actions[bot]
- **#109** — [REC] Test extraction URL — `enhancement` — auteur github-actions[bot] *(ticket de test, à fermer)*
- **#110** — [REC] Clarifier la mécanique de fusion du journal (insertion vs remplacement) — `enhancement` — auteur github-actions[bot] *(doublon de #108)*
- **#111** — [REC] Clarifier détection et usage de PR_NUMBER en mode CI — `enhancement` — auteur github-actions[bot]
- **#112** — [REC] Ajouter rappel git-perso dans le mode interactif du daily-recap — `enhancement` — auteur github-actions[bot]
- **#113** — [REC] Ajouter structure d'articles et bullet-lists dans docs/medium-journal.md — `enhancement` — auteur github-actions[bot]
- **#114** — [REC] Ajouter gestion d'erreur pour 'gh pr list' dans daily-recap — `enhancement` — auteur github-actions[bot]
- **#115** — [REC] Ajouter vérification post-checkout de la branche doc/medium-report — `enhancement` — auteur github-actions[bot]
- **#116** — [REC] Implémenter la déduplification des PR dans les récaps quotidiens — `enhancement` — auteur github-actions[bot]
- **#119** — [ARTICLE] 01 — Setup d'un bot de trading piloté par Claude + MCP TradingView — `documentation` — auteur yousmaaza *(ticket de tracking article, fermé le soir même)*

### Matériel disponible pour l'article
- **Diff PR #106** : `git show 92a68a2 --stat -- '*.txt'` — +31/-14 sur `prompts/trade_prompt.txt`
- **Diff PR #118** : `git show 10b37b5 --stat` — +585/-5 sur 6 fichiers (agent, commands, workflows, articles)
- **Doc tech #106** : `docs/technique/pr-106-filtre-usdc-couplage-1d.md` — diagramme avant/après du pattern de regroupement
- **Doc tech #118** : `docs/technique/pr-118-medium-articles-workflow.md` — architecture en tableau (4 composants)
- **Brouillon article 01** : `docs/medium-articles/01-setup-projet-prompt-mcp.md` — plan complet du 1er article, status `published` en fin de journée
- **Diagramme** : `docs/visuals/` (à générer si besoin avec `/generate-diagrams`)
- **Screenshot Telegram** : "à faire" — notification Phase 2 avec le nouveau compteur `coins_1d_count`

### Idée d'angle Medium

**Angle 1 — "Corriger un rate-limit qu'on ne comprend pas tout de suite"**
L'erreur `Expecting value: line 1 column 1` retournée par TradingView MCP ressemble à un bug de parsing JSON. C'est en réalité un throttle silencieux : TradingView renvoie une réponse vide quand le débit dépasse son seuil. Le fix (groupes de 4, couplage 4H+1D) est d'ordre architectural, pas d'ordre de code. Bon exemple de debugging à rebours — symptôme trompeur → cause profonde dans la stratégie d'appels parallèles.

**Angle 2 — "Automatiser la plomberie pour se concentrer sur l'écriture"**
La PR #118 pose une infrastructure complète pour publier des articles Medium : branches git, frontmatter YAML, index README, issues GitHub — le tout piloté par un agent Claude. Le paradoxe plaisant : un agent LLM gère les métadonnées des articles qui décrivent comment on utilise des agents LLM. Article court sur la limite saine entre ce qu'on délègue à l'agent (tâches répétitives sans créativité) et ce qu'on garde (fond, angle, prose).

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
