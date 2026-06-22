# Journal quotidien — agent-binance

Récaps quotidiens auto-générés par l'agent `daily-recap` (PR mergées, issues fermées, nouveaux tickets, angles narratifs). Matière première pour des articles Medium réguliers.

**Trigger 1** : slash command `/journal` lancée manuellement par l'utilisateur (mode interactif, pas de commit auto).

**Trigger 2** : routine Claude Code remote (cron `0 21 * * *` UTC = 23h Europe/Paris) qui tourne chaque soir et commit+push le récap du jour sur la branche dédiée `doc/medium-report` (pas main). Pilotée depuis https://claude.ai/code/routines.

Les entrées les plus récentes sont en haut. Le fichier de référence chronologique du projet reste `docs/medium-recap.md` (récap des 9 étapes structurantes du POC à v2, couvre la période 19→21 mai 2026).

---

## 2026-06-22

### PRs mergées (5)

#### #238 — fix: TRADE_PROMPT disallows skill invocation

- **Mergée à** : 10:25 UTC
- **Branche** : `feat/issue-237-trade-prompt-disallow-skills`
- **Issues fermées** : #237
- **Quoi** : correction d'un bug de comportement découvert le matin même. Le cycle auto du 22 juin à 08:05 UTC n'avait duré que 57 secondes au lieu des 400-600 secondes normales. Explication : le sous-processus Claude, voyant le skill `start-agent` disponible dans la session, l'avait invoqué à la place d'exécuter les phases 1 à 7. Résultat : aucune analyse de trading, zéro décision, un CronCreate qui pointait vers un mauvais répertoire. Le fix ajoute un bloc d'instruction explicite en tête de `prompts/trade_prompt.txt` : interdiction de tout skill, interdiction de CronCreate/CronDelete, obligation d'exécuter les phases directement via Bash/Read/Write.
- **Quoi c'est intéressant** : aucune ligne de code Python touchée. Un problème de comportement LLM résolu par de la clarification de prompt.
- **Doc tech** : [docs/technique/pr-238-trade-prompt-disallow-skills.md](../technique/pr-238-trade-prompt-disallow-skills.md)

---

#### #241 — [M1] feat: cycle horaire de gestion des positions ouvertes (POSITION_PROMPT)

- **Mergée à** : 19:46 UTC
- **Branche** : `feat/issue-239-position-prompt`
- **Issues fermées** : #239
- **Quoi** : ajout d'un deuxième cycle Claude — un cycle horaire léger dédié à la prise de profit automatique sur les positions ouvertes. Jusqu'ici, le bot ne regardait ses positions que lors des cycles 4h de trading. Désormais, 23 fois par jour (toutes les heures à :05 UTC, sauf les 6 slots 4h pour éviter les collisions), un sous-processus Claude distinct lit `trade_history.json`, récupère les prix en live sur Binance, calcule le P&L de chaque position, et vend immédiatement si le profit atteint `min_profit_pct_take` (2,0% par défaut). La logique de scheduling est intégrée dans `main_loop()` via un helper unifié `_check_and_run_scheduled()`. Le cycle position partage le lock du cycle trade — si un cycle 4h est en cours, le cycle position attend silencieusement.
- **Scope du changement** : 7 fichiers (`timing.py`, `env.py`, `runner.py`, `webhook_server.py`, `config.json`, `prompts/position_prompt.txt` nouveau, `scripts/test_next_1h_slot_weekly.py` nouveau). Refactor de `runner.py` avec extraction de `_run_workflow_cycle()` pour éliminer la duplication entre les deux types de cycles.
- **Coût estimé** : ~0,10-0,20 USD/heure (vs ~1,50 USD pour cycle 4h).
- **Doc tech** : [docs/technique/pr-241-cycle-position-horaire.md](../technique/pr-241-cycle-position-horaire.md)

---

#### #242 — feat: tickets [REC] via REC-AUTO + binance-dev sur branche PR existante

- **Mergée à** : 19:21 UTC
- **Branche** : `feat/fix-rec-auto-workflow`
- **Issues fermées** : N/A (amélioration CI/CD)
- **Quoi** : finalisation du pipeline d'auto-implémentation des recommandations tech lead. Avant cette PR, le workflow `claude-post-review` créait des issues [REC] mais sans associer la branche source — elles étaient orphelines. `binance-dev-auto` ne savait pas non plus travailler sur une branche existante, seulement créer une nouvelle branche depuis `main`. Après cette PR, le flux complet fonctionne : tech lead review → issue [REC] créée avec métadonnées de branche (`<!-- pr_branch -->` / `<!-- pr_number -->`) → `auto-dispatch` détecte le label `REC-AUTO` et extrait ces métadonnées → `binance-dev-auto` checkout la branche existante de la PR, implémente, commit, ferme l'issue. Trois workflows GitHub Actions révisés en coordination.
- **Doc tech** : [docs/technique/pr-242-rec-auto-workflow.md](../technique/pr-242-rec-auto-workflow.md)

---

#### #256 — feat: commande Telegram /calibrage pour déclencher le cycle position

- **Mergée à** : 20:20 UTC
- **Branche** : `feat/issue-254-calibrage-command`
- **Issues fermées** : #254
- **Quoi** : expose `/calibrage` comme commande Telegram manuelle pour déclencher le cycle de gestion des positions à la demande. Avant cette PR, le cycle position ne se déclenchait qu'automatiquement toutes les heures. Le handler suit le même pattern que `/trade` : confirmation immédiate (`"⚙️ Calibrage des positions en cours..."`), puis lancement en thread daemon. 7 lignes de code, 2 lignes de mise à jour des messages d'aide.
- **Doc tech** : [docs/technique/pr-256-calibrage-command.md](../technique/pr-256-calibrage-command.md)

---

#### #257 — feat: position_prompt.txt — inclure les OCO manuels Binance (open-orders)

- **Mergée à** : 20:20 UTC
- **Branche** : `feat/issue-255-position-oco-manuels`
- **Issues fermées** : #255
- **Quoi** : enrichissement du prompt de gestion des positions pour qu'il voie aussi les ordres OCO placés manuellement sur Binance (XRP, HBAR, STX, SUI, etc.), pas seulement les positions du bot. Le cycle position appelle désormais `binance-cli spot open-orders`, merge les deux sources (bot + manuels), calcule le P&L de chaque coin exposé quelle que soit son origine, et réalise le profit si le seuil est atteint — y compris sur les OCO manuels (annulation OCO, puis SELL MARKET). Champ `source` ("bot" vs "manual") ajouté pour tracer l'origine dans les rapports.
- **Impact utilisateur** : les positions ouvertes manuellement sur Binance sont désormais sous surveillance automatique du bot.
- **Doc tech** : [docs/technique/pr-257-position-oco-manuels.md](../technique/pr-257-position-oco-manuels.md)

---

### Issues fermées (16)

**Issues features :**

- **#237** — bug: TRADE_PROMPT invoque skill start-agent au lieu d'exécuter les phases — fermée par PR #238
- **#239** — feat: cycle horaire de gestion des positions ouvertes (POSITION_PROMPT) — fermée par PR #241
- **#254** — feat: commande Telegram /calibrage pour déclencher le cycle position manuellement — fermée par PR #256
- **#255** — feat: position_prompt.txt — inclure les OCO manuels Binance (open-orders) — fermée par PR #257

**Tickets [REC] auto-implémentés sur PR #241 (pipeline REC-AUTO) :**

- **#249, #250** — Extraire `_run_workflow_cycle()` et `_check_and_run_scheduled()` pour réduire la duplication — implémentés dans PR #241
- **#251** — Documenter le comportement silencieux du position check (lock occupé) — implémenté dans PR #241
- **#252** — Clarifier Bandit B101 (assert comme type guard mypy) — implémenté dans PR #241
- **#253** — Tester `next_1h_slot()` sur une semaine UTC (anti-collision) — script de test ajouté dans PR #241
- **#243, #244, #245, #246, #247** — Duplicatas des tickets ci-dessus (issues créées en doublon lors du premier run du pipeline REC-AUTO avant correction de PR #242)
- **#248** — [REC] Test extraction numéro (issue de test fonctionnel du pipeline, fermée manuellement)

**Issue fermée comme non planifiée :**
- **#158** — [REC] Ajouter un exemple minimal au TRADE_PROMPT — fermée comme `not_planned`

---

### Nouveaux tickets créés

- **#240 — feat: Phase 0 TRADE_PROMPT — résumé positions ouvertes avant nouveaux achats** [enhancement · AUTO] : avant chaque cycle de trading 4h, Claude lirait `trade_history.json` + appellerait `binance-cli open-orders` pour avoir une vue consolidée des expositions en cours (bot + manuelles) avec P&L actuels. Ce contexte permettrait d'éviter d'ouvrir une position sur un coin déjà exposé via OCO manuel, et d'ajuster dynamiquement `max_open_positions` en tenant compte du capital réellement disponible. Ticket ouvert, pas encore assigné.

---

### Matériel pour Medium

> **Angle principal** : "Un bot qui apprend à surveiller ses positions — et celles qu'on place à sa place". La journée du 22 juin raconte une évolution en deux temps : d'abord on donne au bot un cycle autonome de gestion des positions (PR #241, 7 fichiers, refactor majeur) ; puis, en soirée, on lui montre qu'il y a des positions qu'il ne voyait pas — les OCO manuels (PR #257). En quelques heures, le bot passe d'un système qui ne regardait ses positions que 6 fois par jour à un système qui surveille 23 fois par jour toutes les expositions du compte, bot ou manuelles. La commande `/calibrage` (PR #256) complète le tableau en donnant à l'utilisateur un levier d'intervention manuel.

> **Angle secondaire** : "Un cycle auto qui s'emballe — et le prompt qui l'a corrigé". Le bug du 22 juin matin (PR #238) illustre un problème propre aux LLM orchestrateurs : Claude voit un skill `start-agent` et l'invoque à la place d'exécuter les 7 phases de trading. Résultat : cycle de 57s, aucune analyse, aucun trade. Fix : une ligne d'instruction en tête du prompt. Pas de code Python, pas de tests. Un problème de comportement LLM résolu par de la clarification textuelle.

> **Angle système** : "Comment on a câblé le feedback loop des recommandations tech lead" (PR #242) — le pipeline REC-AUTO qui permet aux recommandations du tech lead reviewer de devenir des commits directement sur la branche de la PR d'origine, sans intervention humaine. Les 12 tickets [REC] fermés aujourd'hui sont la première démonstration en conditions réelles de ce pipeline.

---

### Chiffres du jour

- PRs mergées : 5
- Issues fermées : 16 (4 features + 12 [REC]/doublons)
- Tickets créés : ~16 (dont 1 ouvert : #240)
- Fichiers modifiés au total (PRs features) : ~12 fichiers

---

## 2026-06-21

### PRs mergées

Aucune PR mergée aujourd'hui.

### Issues fermées

Aucune issue fermée aujourd'hui.

### Nouveaux tickets

- **#236 — [CONFIG] min_order_usdc trop élevé pour le portfolio actuel — 4 TYPE_B en 7 jours** [enhancement · M] : l'agent `analyse-config` (cron 20h UTC) a détecté 4 cycles TYPE_B en 7 jours causés par le même calcul bloquant — avec un portfolio de 30 à 36 USDC et `risk_per_trade_pct = 0.02`, le sizing ATR génère des positions de 8 à 11 USDC, juste sous le seuil actuel de 11 USDC. Il recommande d'abaisser `min_order_usdc` de 11 à 9 USDC (ou 10 USDC en version conservatrice), sous condition que le portfolio soit stable à ≥ 25 USDC et que le minimum notional Binance soit vérifié manuellement sur les paires concernées (BTCUSDC, SOLUSDC).

### Matériel pour Medium

> Angle possible : "Quand le seuil minimum d'ordre devient le plafond de verre du bot" — le ticket #236 illustre une tension précise entre la contrainte Binance (minimum notional ~10 USDC) et la mécanique de risk management par ATR : avec un capital résiduel de 30-36 USDC, le bot génère des signaux valides (score 6, sentiment Bullish) mais ne peut pas les exécuter parce qu'il se censure lui-même via un paramètre de configuration. Un article sur la calibration fine des seuils dans un bot à faible capital — comment un seul entier dans `config.json` change la fréquence d'exécution réelle du bot.

### Chiffres du jour
- PRs mergées : 0
- Issues fermées : 0
- Tickets ouverts : 1

---

## 2026-06-15 — Récap quotidien

### PR mergées (1)

#### #235 — [M218] Augmente max_single_position_pct de 0.40 à 0.65

- **Branche** : `feat/issue-218-config-max-single-position`
- **Mergée à** : 22:29 (Europe/Paris)
- **Volume** : 1 ligne modifiée (`config.json`)
- **Issues fermées** : #218
- **Quoi** : modification d'un seul paramètre de configuration — `max_single_position_pct` passe de `0.40` à `0.65`. L'issue #218 avait été créée le 12 juin par l'agent `analyse-config` (cron 20h UTC) après avoir détecté deux cycles TYPE_B consécutifs avec le même calcul bloquant : `17.24 USDC × 0.40 = 6.90 USDC < 11 USDC (seuil min_order_usdc)`. Avec la nouvelle valeur, le calcul donne `17.24 × 0.65 = 11.21 USDC`, juste au-dessus du seuil. Aucun changement de code applicatif — uniquement `config.json`.
- **Pourquoi c'est intéressant pour Medium** : la PR illustre un cycle de décision complet — de la détection automatique (agent cron) au ticket structuré (#218 avec tableau de 4 cycles, calcul chiffré, conditions d'application, risques), jusqu'au correctif minimaliste (1 ligne) 3 jours plus tard. L'écart entre la date du diagnostic (12 juin) et la date du merge (15 juin) reflète le fait que les conditions d'application posées dans le ticket n'étaient pas encore réunies (capital insuffisant, positions ouvertes en perte).
- **Doc tech** : [docs/technique/pr-235-augmente-max-single-position.md](../technique/pr-235-augmente-max-single-position.md)

---

### Issues fermées (1)

- **#218** — [CONFIG] TYPE_B récurrent + drawdown -70% : `max_single_position_pct` trop restrictif avec capital résiduel faible — fermée par PR #235 — [lien](https://github.com/yousmaaza/agent-binance/issues/218)

Ticket ouvert le 12 juin à 20:07 UTC par l'agent `analyse-config`. Il avait analysé 4 cycles sur 7 jours, identifié le calcul bloquant, et conditionné l'application du correctif à : BTC sentiment Bullish, top_score ≥ 6, portfolio > 50 USDC. Ces conditions n'étaient pas réunies le 12 juin (portfolio à 24.63 USDC, drawdown -70%). La PR a été ouverte et mergée le 15 juin, après rechargement du capital.

---

### Nouveaux tickets créés (0)

Aucun ticket créé aujourd'hui.

---

### Comportement du bot en production (5 cycles)

| Heure UTC | Score | Décision | Skip detail | Portfolio | Open pos. |
|---|---|---|---|---|---|
| 08:05 | 5/10 | TYPE_A | Score < 6, signaux 1D tous Neutral | 0.02 USDC | 3 |
| 12:05 | 5/10 | TYPE_A | Score 5/10 < seuil 6/10 | 0.00 USDC | 3 |
| 17:19 | 5/10 | TYPE_B | Budget 0.00 USDC < seuil 11 | 0.00 USDC | 0 |
| 17:41 | 5/10 | — | (pas de skip) | 100.00 USDC | 0 |
| 20:05 | 7/10 | **BUY** ✅ | Premier exécuté | 100.00 USDC | 1 |
| 20:37 | 7/10 | TYPE_A | WLD déjà en position, autres < 6/10 | 71.73 USDC | 1 |

Les deux premiers cycles de la journée (08:05 et 12:05) tournaient avec 3 positions ouvertes en perte, portfolio quasi nul. Entre 12:05 et 17:19, les stop-losses ont été déclenchés (open_positions 3 → 0), mais le capital résiduel était à zéro. À 17:41, le portfolio est rechargé à 100 USDC (rechargement manuel probable). À 20:05 UTC — 24 minutes avant le merge de PR #235 — le bot exécute son premier BUY de la journée (top_score 7/10, sentiment Bullish). La PR #235 n'a donc pas déclenché ce premier BUY : c'est la remise à 100 USDC qui a débloqué la situation. La PR, elle, protège les prochains cycles contre un reblocage TYPE_B si le capital résiduel redescend autour de 17 USDC.

---

### Matériel disponible pour illustrer

- **`state/cycle_log.jsonl`** : lignes `20260615_*` — les 5 cycles du jour avec progression portfolio (0.02 → 0 → 0 → 100 → 100 → 71.73), bon visualiseur de la journée.
- **Issue #218 complète** : tableau des 4 cycles analysés le 12 juin avec le calcul bloquant `17.24 × 0.40 = 6.90` — tel quel, sans mise en forme, c'est le dossier brut produit par l'agent d'analyse.
- **Diff PR #235** : 1 ligne changée dans `config.json` (`0.40` → `0.65`). Bon exemple de correctif minimaliste après un diagnostic long et structuré.
- **Timeline du ticket** : #218 créée le 12 juin à 20:07 UTC → PR #235 ouverte le 15 juin à 20:25 UTC → mergée le 15 juin à 20:29 UTC. Le ticket a mis 3 jours à passer en PR — non pas par oubli, mais parce que les conditions posées dans le ticket lui-même n'étaient pas réunies plus tôt.

---

### Idée d'angle Medium

**"Le ticket qui pose ses propres conditions de résolution"**

L'issue #218, générée automatiquement le 12 juin, ne dit pas juste "change ce paramètre". Elle liste les conditions précises sous lesquelles appliquer le changement : sentiment Bullish, score ≥ 6, portfolio > 50 USDC. Ces conditions n'étaient pas réunies le 12 juin — le portfolio était à 24.63 USDC, drawdown -70%. La PR n'a été mergée que le 15 juin, après rechargement du capital. Article sur une idée contre-intuitive : un ticket bien rédigé peut contenir sa propre condition de blocage. Quand un agent formule des prérequis d'application, il crée une gate qui empêche l'automatisation aveugle. Le correctif attend le bon contexte plutôt que d'être appliqué immédiatement.

**Angle secondaire — "La journée en creux : 5 cycles, 0 achats avant 22h, 1 vrai BUY"**

La journée du 15 juin est d'abord une journée de liquidation (stop-losses à la chaîne) et de rechargement. Les 3 premiers cycles du jour tournent avec un portfolio à quasi zéro et des positions bloquées. Ce n'est qu'après que le compte repasse à 100 USDC que le bot retrouve sa capacité d'action — et exécute un BUY à 22h05 (Europe/Paris), 24 minutes avant que la PR censée débloquer ses TYPE_B futurs soit mergée. Court article sur la différence entre un bug structurel (le paramètre trop restrictif) et un problème conjoncturel (capital insuffisant) : les deux se ressemblent en surface (le bot ne trade pas), mais les correctifs sont orthogonaux.

---

## 2026-06-14 — Récap quotidien

### PR mergées (2)

#### #231 — chore: consolidation [REC] AUTO — 2026-06-14

- **Branche** : `feat/consolidate-rec-20260614_191332`
- **Mergée à** : 19:18 (Europe/Paris)
- **Volume** : n/a (consolidation de PRs #226, #227, #230)
- **Issues fermées** : #156, #172, #228
- **Quoi** : consolidation de trois PRs [REC] générées automatiquement, regroupant un refactoring architectural majeur : extraction du monolithe `webhook_server.py` en modules spécialisés (`orchestration/`, `core/`, `commands/`, `storage/`, `botlogging/`), externalisation du `TRADE_PROMPT` dans `prompts/trade_prompt.txt`, et injection dynamique des helpers via `tempfile.mkstemp()`. Cette PR semble également avoir clos des tickets pendants anciens — #156 (clarification CYCLE_ID dans le prompt, ouvert le 28 mai) et #172 (blacklist auto USDC, ouvert le 29 mai) — via la PR #230 intégrée.
- **Pourquoi c'est intéressant pour Medium** : c'est le type de PR qui illustre la différence entre un refactoring "humain" (planifié, discuté) et un refactoring "émergent" (déclenché par des reviews automatiques qui accumulent de la dette puis la liquident en une consolidation). Trois PRs [REC] générées par CI, fusionnées en une seule merge.
- **Doc tech** : [docs/technique/pr-231-consolidation-rec-auto.md](../technique/pr-231-consolidation-rec-auto.md)

---

#### #234 — [M232] Fix outils MCP TradingView — restaurer atilaahmettaner

- **Branche** : `feat/issue-232-fix-tradingview-mcp-tools-v2`
- **Mergée à** : 21:28 (Europe/Paris)
- **Volume** : n/a (modifications dans `.mcp.json` et `prompts/trade_prompt.txt`)
- **Issues fermées** : #232
- **Quoi** : le `TRADE_PROMPT` référençait les outils MCP du mauvais serveur TradingView. Le serveur configuré était `tradesdontlie` (nécessite l'application desktop via CDP), alors que le serveur déployé est `atilaahmettaner` (API publique). En Phase 1, `quote_get` est remplacé par trois appels : `top_gainers`, `volume_breakout_scanner`, `market_sentiment`. En Phase 2, la séquence `chart_set_symbol + chart_set_timeframe + data_get_study_values + data_get_ohlcv` est remplacée par deux appels `coin_analysis` par coin (4h + optionnellement 1D). En Phase 3, les critères "variation 24h > 3%" et "ADX > 20" — qui dépendaient de données non disponibles via `atilaahmettaner` — sont remplacés par `+1 si top_gainers` et `+1 si volume_breakout_scanner`. La configuration `.mcp.json` est également corrigée pour pointer vers `uvx --from tradingview-mcp-server tradingview-mcp`.
- **Pourquoi c'est intéressant pour Medium** : ce bug illustre une classe d'erreur spécifique aux projets LLM + MCP : l'agent s'adapte à la volée à l'absence des outils (génère du bruit dans les logs, ralentit les cycles) sans jamais planter clairement — le cycle "fonctionne" mais pas avec les données attendues. La PR #228 (la PR [REC] qui a diagnostiqué le problème) a été créée aujourd'hui même à 17h08, et la correction (PR #234) était mergée à 21:28 — un aller-retour diagnostic → fix → merge en 4h20 sur un problème de configuration silencieux.
- **Doc tech** : [docs/technique/pr-234-fix-tradingview-mcp-tools-v2.md](../technique/pr-234-fix-tradingview-mcp-tools-v2.md)

---

### Issues fermées (4)

- **#232** — [BUG] TRADE_PROMPT utilise les outils MCP du mauvais serveur TradingView — fermée par PR #234 — [lien](https://github.com/yousmaaza/agent-binance/issues/232)
- **#228** — [BUG] TRADE_PROMPT référence 4 outils MCP TradingView inexistants — fermée par PR #231 — [lien](https://github.com/yousmaaza/agent-binance/issues/228)
- **#172** — [AMÉLIORATION] Blacklist auto-mise à jour des coins sans paire USDC — fermée par PR #231 — [lien](https://github.com/yousmaaza/agent-binance/issues/172)
- **#156** — [REC] Clarifier la notation CYCLE_ID et les phases dans TRADE_PROMPT — fermée par PR #231 — [lien](https://github.com/yousmaaza/agent-binance/issues/156)

---

### Nouveaux tickets (2)

- **#232** — [BUG] TRADE_PROMPT utilise les outils MCP du mauvais serveur TradingView — `bug`, `AUTO` — auteur yousmaaza *(créé à 19:22, fermé à 21:28 le même jour)*
- **#228** — [BUG] TRADE_PROMPT référence 4 outils MCP TradingView inexistants — `bug`, `AUTO` — auteur yousmaaza *(créé à 17:08, fermé à 17:18 par PR #231)*

Note : les deux tickets sont de nature utilisateur (pas [REC]). Le #228 avait diagnostiqué la mauvaise couche (les outils inexistants dans le mauvais sens), le #232 a reposé le diagnostic correctement après identification du vrai serveur cible (`atilaahmettaner` vs `tradesdontlie`).

---

### Matériel disponible pour illustrer

- **`.mcp.json` avant/après** : `git show <sha> -- .mcp.json` — la diff est minimale (1 entrée JSON) mais l'impact est structurant pour tous les cycles.
- **`prompts/trade_prompt.txt` diff PR #234** : lignes 329–482, remplacement des trois séquences d'appels MCP. Bon exemple concret de ce que ça change d'un serveur MCP à l'autre en termes d'interface.
- **Issue #232 complète** : tableau des 4 outils disponibles avec signatures exactes — bon format d'illustration pour un article sur le "contrat d'interface MCP".
- **Issue #228 complète** : le diagnostic inverse — liste des outils que le prompt appelait en pensant les trouver, avec les vraies commandes disponibles. Bon matériel pour montrer la confusion entre deux serveurs de même nom de domaine.
- **Timeline du jour** : #228 créée 17:08 → PR #231 mergée 17:18 (ferme #228) → #232 créée 19:22 → PR #234 mergée 21:28. La résolution complète du problème MCP s'est faite en 4h20, avec deux passes de diagnostic successives.

---

### Idée d'angle Medium

**"Deux serveurs MCP, même nom, interface incompatible — le bug silencieux des agents adaptatifs"**

La journée du 14 juin expose une classe de bug propre à l'IA agentique : le `TRADE_PROMPT` appelait des outils qui n'existaient pas. Mais l'agent ne plantait pas — il s'adaptait en silence, réinventait ses propres heuristiques, et continuait le cycle avec des données dégradées. Ce n'est pas un crash, c'est une dérive silencieuse. Le problème sous-jacent : deux serveurs MCP TradingView (tradesdontlie et atilaahmettaner) ont des interfaces radicalement différentes mais partagent le même namespace dans le prompt. Angle narratif : la robustesse d'un agent (continuer malgré les erreurs) peut masquer des incohérences structurelles qu'un crash aurait immédiatement révélées. Et quand le contrat MCP change, qui détecte la rupture ?

**Angle secondaire — "Deux diagnostics pour un bug : quand la première PR rate la cause"**

Le ticket #228 avait bien identifié que le prompt appelait des outils inexistants, mais dans le mauvais sens — il proposait de réécrire le prompt pour appeler les outils `quote_get` du serveur `tradesdontlie`. La PR #231 avait fermé ce ticket dans le batch du matin. Une heure plus tard, le ticket #232 reposait le diagnostic dans l'autre sens : c'est le serveur configuré qui était faux, pas les appels dans le prompt. Court article sur la valeur du "deuxième diagnostic" dans les projets complexes — et sur la différence entre corriger un symptôme et identifier la cause racine quand les deux lectures sont plausibles.

---

## 2026-06-13 — Récap quotidien

### PR mergées (3)

#### #217 — Consolidation [REC] AUTO — 6 PRs (créée le 12, mergée ce matin à 07:42 UTC)

- **Branche** : `feat/consolidate-rec-20260612_174455`
- **PRs consolidées** : #204, #205, #207, #212, #213, #214
- **Issues fermées** : #25, #123, #136, #137, #138, #139

**Récit**

Six PRs [REC] générées par `binance-dev-auto` sur la journée du 12 juin ont été consolidées en une seule merge. Les changements forment un cluster cohérent autour de `CycleLogger` et de la qualité de code :

- `CycleLogger.debug()` ajoutée : la classe avait `info()`, `error()`, `warning()` mais pas `debug()`. La PR #208 (logging debug Mongo) avait essayé d'appeler cette méthode sans qu'elle existe — les reviews avaient créé le ticket #210 le 12 juin, implémenté ici.
- Context manager `with open():` remplace `open().close()` dans `env.py` — ticket #123, bonne pratique Python garantissant la fermeture même en cas d'exception.
- Commentaires explicites Bandit B324 / B603 / Mypy dans `runner.py` et `env.py` — les outils de review CI ne reflagueront plus ces lignes comme problèmes non-résolus.
- Logs debug MongoDB : chaque mise à jour de coût API ou de mode facturation émet maintenant un `cycle_log.debug()` — traçabilité fine sans polluer le journal INFO principal.

| Fichier | Changement |
|---|---|
| `binance-bot/botlogging/cycle_logger.py` | Ajout `CycleLogger.debug()` |
| `binance-bot/core/env.py` | Context manager + commentaires Bandit |
| `binance-bot/orchestration/runner.py` | Commentaires Bandit B603, assert Mypy, logs debug Mongo |

- **Doc tech** : [docs/technique/pr-217-consolidation-rec-auto.md](../technique/pr-217-consolidation-rec-auto.md)

---

#### #219 — Consolidation [REC] AUTO — refonte architecture multi-module (07:45 UTC)

- **Branche** : `feat/consolidate-rec-20260613_091111`
- **PRs consolidées** : #206, #208
- **Issues fermées** : #138, #139 (déjà fermées par #217 — doublon de clôture)

**Récit**

La PR la plus structurante de la journée. Elle consolide deux PRs [REC] qui, ensemble, formalisent la refonte de `webhook_server.py` monolithique (~1500 lignes) en une architecture multi-module. L'agent `binance-doc-tech` documente la structure complète :

| Module | Fichier | Rôle |
|---|---|---|
| orchestration | `runner.py` | Cycle complet : lock → helpers → subprocess Claude → Mongo |
| orchestration | `stream_parser.py` | Parsing stream-json Claude CLI |
| orchestration | `watchdog.py` | Monitoring phases via heartbeats JSONL |
| core | `env.py`, `lock.py`, `telegram.py`, `timing.py`, `state_manager.py` | Infrastructure partagée |
| storage | `mongo.py` | Client MongoDB (lazy init) |
| commands | `status.py`, `perf.py`, `eval.py`, `cout.py`, `raisonnement.py` | Handlers Telegram |
| botlogging | `cycle_logger.py`, `stream_parser.py`, `watchdog.py` | Observabilité |

Deux décisions techniques méritent d'être retenues. D'abord, `_write_helpers_file()` utilise `tempfile.mkstemp()` (permissions 0o600) au lieu d'un chemin `/tmp/` prévisible — les secrets ne sont pas substitués à l'avance dans le fichier, mais lus depuis `os.environ` au runtime dans le fichier helpers. C'est la correction de la race condition TOCTOU Bandit B108 identifiée lors de la PR #187 (30 mai), consolidée dans l'architecture. Ensuite, le timeout watchdog utilise `threading.Timer` au lieu de `subprocess.timeout` directement, ce qui permet un cancel propre dans le bloc `finally`.

La configuration LLM est externalisée dans `binance-bot/config/llm.py` — le modèle Claude utilisé devient un paramètre de config, plus une constante hardcodée dans `runner.py`.

- **Doc tech** : [docs/technique/pr-219-consolidation-auto.md](../technique/pr-219-consolidation-auto.md)

---

#### #225 — Consolidation [REC] AUTO — fiabilité trading & state management (10:40 UTC)

- **Branche** : branche de consolidation auto
- **PRs consolidées** : #223, #224
- **Issues fermées** : #220 (Refactoring orchestration & runner), #221 (Fiabilité trading & state management)

**Récit**

La troisième consolidation de la journée, qui clôt les deux épics créées à 07:57 UTC — moins de 3h après les PR #217 et #219. Les épics #220 (25 sous-tickets) et #221 (20 sous-tickets) ont été générées automatiquement par les reviews des PR du matin, implémentées par `binance-dev-auto` dans les PRs #223 et #224, puis consolidées et mergées avant midi.

Les fichiers touchés couvrent : `binance-bot/commands/eval.py`, `binance-bot/commands/status.py`, `binance-bot/core/state_manager.py`, `binance-bot/storage/mongo.py`, `CLAUDE.md`.

Le nouveau workflow `.github/workflows/auto-dispatch-on-auto-label.yml` (livré dans ce batch) change le point de déclenchement de l'automation : dorénavant, le label `AUTO` posé sur une issue suffit à lancer `binance-dev-auto` — sans attendre un trigger post-review. Le workflow résout l'item dans le board GitHub Projects (GraphQL), le passe en "In progress", puis dispatche le workflow d'implémentation. L'ajout de ce workflow ferme le dernier maillon manuel de la chaîne.

---

### Issues fermées (73)

La journée a vu 73 issues clôturées, dont la grande majorité sont des sous-tickets `[REC]` de qualité résolus en cascade par les trois consolidations. Les clôtures marquantes :

| # | Titre | Motif |
|---|---|---|
| [#220](https://github.com/yousmaaza/agent-binance/issues/220) | [REC] Consolidation — Refactoring orchestration & runner | Completed via PR #225 |
| [#221](https://github.com/yousmaaza/agent-binance/issues/221) | [REC] Consolidation — Fiabilité trading & state management | Completed via PR #225 |
| [#222](https://github.com/yousmaaza/agent-binance/issues/222) | [REC] Consolidation — CycleLogger, daily-recap & outillage | Duplicate — couvert par #217 et #225 |
| [#210](https://github.com/yousmaaza/agent-binance/issues/210) | Ajouter la méthode `debug()` à `CycleLogger` | Completed — ticket du 12 juin fermé le lendemain |
| [#209](https://github.com/yousmaaza/agent-binance/issues/209) | Mypy: type guard sur `process.stdout` | Completed |
| [#167](https://github.com/yousmaaza/agent-binance/issues/167) | Refactor `main_loop()` avec dispatch table | Completed |
| [#188–#192](https://github.com/yousmaaza/agent-binance/issues/188) | Cluster qualité post-PR #187 (helpers, streaming, tests) | Completed batch |
| [#196–#197](https://github.com/yousmaaza/agent-binance/issues/196) | Heartbeats Phase 2 + adaptive sleep rate limits | Completed |
| [#25](https://github.com/yousmaaza/agent-binance/issues/25) | Bandit B324 `hashlib.sha1 usedforsecurity=False` | Completed (ticket ouvert depuis longtemps) |

Vingt sous-tickets de la liste complète ont été collectés par l'outil de recherche (sur 73 au total) — la majorité appartient aux clusters orchestration, state management, et CycleLogger.

---

### Nouveaux tickets créés (3, tous fermés le même jour)

| # | Titre | Créé à | Fermé à | Motif fermeture |
|---|---|---|---|---|
| [#220](https://github.com/yousmaaza/agent-binance/issues/220) | [REC] Consolidation — Refactoring orchestration & runner (25 sous-issues) | 07:57 UTC | 10:40 UTC | Completed |
| [#221](https://github.com/yousmaaza/agent-binance/issues/221) | [REC] Consolidation — Fiabilité trading & state management (20 sous-issues) | 07:57 UTC | 10:40 UTC | Completed |
| [#222](https://github.com/yousmaaza/agent-binance/issues/222) | [REC] Consolidation — CycleLogger, daily-recap & outillage (18 sous-issues) | 07:58 UTC | 10:42 UTC | Duplicate |

Ces trois épics ont été créées par les reviews des PR #217 et #219 (mergées à 07:42 et 07:45). Elles ont regroupé respectivement 25, 20 et 18 sous-tickets de dette technique accumulée depuis fin mai. L'épic #220 a été implémentée (PR #223), #221 aussi (PR #224), les deux consolidées dans PR #225 et mergées à 10:40. L'épic #222 a été close en duplicate car son contenu était déjà couvert par #217 et #225.

La boucle complète — merge → reviews → épics → implémentation → consolidation → merge — s'est refermée en moins de 3h.

---

### Matériel disponible pour illustrer

- `docs/technique/pr-219-consolidation-auto.md` : tableau complet de l'architecture multi-module (10 modules, rôles) — bon visuel pour illustrer la séparation des responsabilités avant/après.
- `.github/workflows/auto-dispatch-on-auto-label.yml` (nouveau) : 122 lignes de workflow GitHub Actions — le déclencheur final de l'automation label → board → dispatch. Bonne illustration du fonctionnement interne.
- `binance-bot/config/llm.py` (nouveau) : externalisation de la config modèle Claude — petit fichier, gros impact sur la maintenabilité.
- Les épics #220, #221, #222 dans GitHub Issues : chacune liste ses sous-tickets avec coches — bonne matière pour un article sur la structuration de la dette technique.
- Timeline du jour : PR #217 mergée 07:42 → épics créées 07:57 → PR #225 mergée 10:40. Écart total : 2h58.

### Idée d'angle Medium

**"La boucle qui se ferme en 3h : quand l'automatisation s'auto-alimente"**

Le 13 juin illustre ce que devient le pipeline quand toutes les pièces sont en place. Les PRs du matin déclenchent les reviews qui génèrent des épics, les épics déclenchent `binance-dev-auto` qui implémente, l'implémentation est consolidée et mergée — le tout sans intervention humaine, en moins de 3 heures. Article sur la distinction entre automation "assistée" (un humain décide de chaque étape) et automation "réflexive" (le pipeline déclench le pipeline). La nuance importante : l'humain merge encore les PRs de consolidation. C'est le seul frein conscient dans la chaîne. Pourquoi garder cette friction ? Et jusqu'où peut-on aller sans elle ?

**Angle secondaire — "Refactoring architectural via PR [REC] : comment un agent découpe 1500 lignes sans se perdre"**

La PR #219 n'a pas été planifiée par un humain — elle est sortie d'une review automatique qui a identifié que `webhook_server.py` monolithique était trop complexe. L'agent `binance-dev-auto` a produit une architecture à 10 modules, avec séparation claire des responsabilités, dans une PR de consolidation. Court article sur la question : peut-on déléguer les décisions architecturales à un agent de review ? Avec quelles limites ?

---

## 2026-06-12 — Récap quotidien

### PR mergées (0)

Aucune PR mergée sur `main` aujourd'hui.

---

### Issues fermées (3)

| # | Titre | Motif |
|---|---|---|
| [#25](https://github.com/yousmaaza/agent-binance/issues/25) | [REC] Corriger B324 HIGH — ajouter `usedforsecurity=False` sur `hashlib.sha1` | Completed — fix implémenté via `feat/issue-25-hashlib-usedforsecurity` |
| [#200](https://github.com/yousmaaza/agent-binance/issues/200) | [REC] Setup Graphify — knowledge graph MCP du codebase | Not planned — idée reportée sans suite |
| [#203](https://github.com/yousmaaza/agent-binance/issues/203) | [CONFIG] Évaluer hausse `max_open_positions` 3→4 — opportunité score 9/10 manquée le 2026-05-30 | Not planned — supersédé par l'analyse plus complète de #218 |

Le ticket #25 est celui qui a abouti : un seul paramètre ajouté (`usedforsecurity=False`) dans l'appel `hashlib.sha1()` qui calcule le fingerprint du `TRADE_PROMPT`. Le flag documente l'intention non-cryptographique du hash — il ne change pas le calcul — et fait disparaître le finding Bandit HIGH B324 qui masquait les vrais problèmes de sécurité dans les rapports CI.

Le ticket #203 est fermé non pas parce que le problème n'existe plus, mais parce qu'une analyse plus récente (#218) le couvre dans un contexte plus dégradé. La montée de `max_open_positions` à 4 reste sur la table, mais avec de nouvelles contraintes.

---

### Nouveaux tickets créés (6)

Deux origines : reviews automatiques des PR #208 / #213 / #214, et l'agent `analyse-config` qui tourne en cron à 20h UTC.

**Cluster CycleLogger — issues #209, #210, #211, #216** (depuis reviews PR #208 / #213)

| # | Titre | Origine |
|---|---|---|
| [#209](https://github.com/yousmaaza/agent-binance/issues/209) | Mypy: type guard sur `process.stdout` (`runner.py:224`) | Review PR #208 |
| [#210](https://github.com/yousmaaza/agent-binance/issues/210) | Ajouter la méthode `debug()` à `CycleLogger` | Review PR #208 |
| [#211](https://github.com/yousmaaza/agent-binance/issues/211) | Typer `CycleLogger` avec type hints complets | Review PR #208 |
| [#216](https://github.com/yousmaaza/agent-binance/issues/216) | Modèle de logging plus fluide dans `CycleLogger` | Review PR #213 |

Ces quatre tickets forment un seul cluster de dette technique sur `CycleLogger` : la classe expose `info()`, `warning()`, `error()`, `heartbeat()` mais pas `debug()`. La PR #208 (logging debug Mongo) avait essayé de l'appeler sans qu'elle existe. Les reviews ont révélé en cascade : méthode manquante, absence de type hints, et `process.stdout` non gardé contre `None` dans `runner.py`.

**Documentation — issue #215** (depuis review PR #214)

| # | Titre | Origine |
|---|---|---|
| [#215](https://github.com/yousmaaza/agent-binance/issues/215) | Ajouter docstring module en tête de `binance-bot/core/env.py` | Review PR #214 |

Le module `env.py` est le bootstrap du bot (chargement `.env`, setup loguru, chargement du prompt) mais n'a aucune docstring. Ticket minimaliste : 5 à 10 lignes à ajouter, aucune modification de code.

**Alerte config automatique — issue #218** (agent cron 20h UTC)

| # | Titre | Origine |
|---|---|---|
| [#218](https://github.com/yousmaaza/agent-binance/issues/218) | TYPE_B récurrent + drawdown -70 % : `max_single_position_pct` trop restrictif avec capital résiduel faible | Analyse-config automatique |

Le ticket le plus substantiel de la journée. L'agent `analyse-config` a détecté que les deux derniers cycles du jour s'étaient terminés en TYPE_B avec exactement le même calcul bloquant :

```
USDC libre    = 17.24
Budget/pos    = 17.24 × 0.40 = 6.90 USDC
6.90 < 11     → SKIP TYPE_B
```

Il propose de monter `max_single_position_pct` de 0.40 à 0.65 (ce qui donnerait 17.24 × 0.65 = 11.21 USDC, juste au-dessus du seuil), mais conditionne l'application à un rebond confirmé : BTC sentiment Bullish, top_score ≥ 6, portfolio > 50 USDC.

---

### Comportement du bot en production

Deux cycles aujourd'hui :

| Heure UTC | Score | Skip | Portfolio | Sentiment |
|---|---|---|---|---|
| 10:45 | 6/10 | TYPE_B — 6.90 USDC < seuil 11 (XPL, ATR élevé) | 118.85 USDC | Bullish |
| 12:14 | 4/10 | TYPE_B — 6.90 USDC < seuil 11 (disponible: 17.24) | 24.63 USDC | Neutral |

Le portfolio a chuté de 118.85 à 24.63 USDC entre les deux cycles, reflétant des positions ouvertes en mark-to-market négatif (3/4 slots occupés). Sur 7 jours, le drawdown atteint −70 % (81.58 → 24.63 USDC).

Le bot a correctement loggé les deux TYPE_B dans `state/cycle_log.jsonl`. L'agent cron a agrégé ces logs à 20:07 UTC et créé le ticket #218 avec un diagnostic structuré : calcul chiffré du blocage, recommandation conditionnelle, risques, et conditions d'application. Aucune intervention humaine entre le log et le ticket.

---

### Matériel disponible pour illustrer

- `state/cycle_log.jsonl` : lignes `20260612_103604` et `20260612_120500` — les deux TYPE_B avec `skip_detail` chiffré.
- Issue #218 complète : tableau des 4 cycles analysés, calcul `17.24 × 0.40 = 6.90`, recommandation + conditions + risques. Format structuré généré automatiquement à partir de données de production.
- Branche `feat/issue-25-hashlib-usedforsecurity` : diff minimal — 1 paramètre, 1 fichier, finding Bandit éliminé. Bon exemple d'un ticket `[REC]` de sécurité résolu en chirurgie.
- Issues #209–#211 comme illustration de la dette technique qui s'accumule quand on ajoute des fonctionnalités (PR #208 debug Mongo) sans compléter l'interface existante (méthode `debug()` manquante).

### Idée d'angle Medium

**"Le bot qui se diagnostique lui-même : de la log au ticket de configuration"**

La journée du 12 juin illustre une boucle fermée sur la configuration : cycles bloqués → logs TYPE_B → agent cron qui agrège les données → ticket structuré avec calcul, recommandation et conditions d'application → humain qui décide. Le bot ne corrige pas sa propre configuration (l'humain garde la main sur `config.json`), mais il produit un dossier d'aide à la décision complet, fondé sur des données réelles de production. Article sur la distinction entre autonomie d'exécution (ce que le bot fait seul) et autonomie de décision (ce que l'humain garde).

**Angle secondaire — "Le cluster de dette : quand une PR révèle trois tickets connexes"**
La PR #208 (logging debug Mongo) a déclenché reviews qui ont révélé que `CycleLogger` manquait de `debug()`, de type hints, et que `runner.py` avait un `process.stdout` potentiellement `None`. Trois tickets distincts (#209, #210, #211) nés d'une seule feature. Court article sur le pattern "dette visible" — les reviews automatiques ne bloquent pas, elles exposent la surface réelle du code. La question est : traiter immédiatement ou accumuler consciemment.

---

## 2026-06-03 — Récap quotidien

### PR mergées (1)

#### #201 — [M199] Enrichir CLAUDE.md avec principes généraux de développement (Think/Simplicity/Surgical)

- **Branche** : `feat/issue-199-enrichir-claude-md`
- **Mergée à** : 21:46 (Europe/Paris)
- **Issues fermées** : #199

**Récit**

Depuis la création du projet, `CLAUDE.md` accumulait des règles très concrètes — comment lancer le venv, comment structurer les commits, quels appels Telegram éviter, quand ne pas utiliser urllib. Des règles opérationnelles, précises, project-specific. Mais aucune règle sur la façon de *penser* avant d'écrire du code. Cette lacune laissait la porte ouverte aux comportements LLM classiques : sur-ingénierie par habitude, refactorisation non demandée du code adjacent, implémentation dans l'ambiguïté plutôt que la demande de clarification.

La PR #201 comble ce vide. Elle insère une section **"Principes généraux de développement"** dans `CLAUDE.md`, positionnée délibérément après `## Stack` (le contexte) et avant `## Règles de modification non négociables` (les contraintes opérationnelles) — pour établir les fondations culturelles avant les règles de procédure. La section regroupe trois principes :

1. **Réfléchir avant de coder** : énoncer les hypothèses explicitement, présenter les alternatives, ne pas implémenter dans l'ambiguïté, signaler la solution la plus simple quand elle existe.
2. **Minimalisme** : code minimum qui résout le problème, rien de spéculatif, pas d'abstraction pour un usage unique, pas de gestion d'erreur pour des scénarios impossibles dans ce contexte.
3. **Modifications chirurgicales** : toucher uniquement ce qui est demandé, conserver le style existant, mentionner (ne pas supprimer) le dead code repéré, chaque ligne modifiée doit être traçable directement à la demande de l'utilisateur.

Ce qui est notable : la PR ne touche aucun fichier de code. Pas de `webhook_server.py`, pas de `config.json`, pas de workflow YAML. Un seul fichier Markdown, 73 lignes ajoutées. C'est une modification qui agit entièrement sur le comportement futur de l'IA — en configurant ses principes de raisonnement plutôt que la logique de l'application.

**Changements techniques**

| Fichier | Changement |
|---|---|
| `CLAUDE.md` | Insertion de la section `## Principes généraux de développement` (73 lignes) entre `## Stack` et `## Règles de modification non négociables` |

- **Doc tech** : [docs/technique/pr-201-enrichir-claude-md.md](../technique/pr-201-enrichir-claude-md.md)

---

### Issues fermées (1)

| # | Titre |
|---|---|
| [#199](https://github.com/yousmaaza/agent-binance/issues/199) | [AMÉLIORATION] Enrichir CLAUDE.md avec principes généraux de développement (Think/Simplicity/Surgical) |

---

### Nouveaux tickets créés (0)

Aucun ticket créé aujourd'hui.

---

### Matériel disponible pour illustrer

- Diff PR #201 dans `CLAUDE.md` : avant/après de la section — illustre l'ajout d'un contrat comportemental LLM dans un fichier de configuration projet.
- Issue #199 complète : inclut le texte exact des règles à insérer, les critères d'acceptation, et la justification d'inspiration (dépôt `multica-ai/andrej-karpathy-skills`). Bonne illustration de la rigueur d'un ticket de documentation pure.
- `docs/technique/pr-201-enrichir-claude-md.md` : résumé structuré de l'impact de gouvernance — base pour un passage explicatif dans un article Medium.

### Idée d'angle Medium

**"CLAUDE.md comme contrat comportemental : configurer le raisonnement, pas seulement la stack"**

La plupart des projets LLM documentent *ce que l'IA doit faire* (appeler telle API, utiliser tel format). Le ticket #199 documente *comment l'IA doit penser* — énoncer les hypothèses, refuser l'ambiguïté, ne pas toucher le code adjacent. C'est une catégorie de configuration entièrement différente : non plus des règles métier, mais des règles épistémiques. Article sur la distinction entre les deux niveaux de `CLAUDE.md` dans ce projet — règles opérationnelles (procédures, chemins, conventions) vs règles culturelles (comportement, style, rigueur). La question sous-jacente : peut-on vraiment changer le comportement d'un LLM par des instructions persistantes dans un fichier de config, ou doit-on le faire à chaque session ?

**Angle secondaire — "L'exception qui confirme la règle"**
Ce ticket illustre une règle de CLAUDE.md elle-même : `CLAUDE.md` peut être modifié directement sur `main`, sans PR, sans branche. Pourtant, une PR a bien été ouverte (#201) et une branche créée. Pourquoi ? Parce que l'agent `binance-dev` suit toujours le workflow standard, et l'utilisateur a choisi de merger proprement plutôt que de contourner. Court billet sur la différence entre "autorisé à" et "systématiquement faire" — et sur la valeur des exceptions bien documentées dans un projet qui vit de ses conventions.

---

## 2026-05-31 — Récap quotidien

### PR mergées (1)

#### #194 — [M193] Phase 2 : sleep 15s post-batch 4h + gestion erreur 1D silencieuse

- **Branche** : `feat/issue-193-fix-1d-rate-limit`
- **Mergée à** : 16:11 (Europe/Paris)
- **Issues fermées** : #193

**Récit**

Le matin du 31 mai, le cycle `cycle_20260530_101921` révélait une erreur familière dans `logs/stdout/` : `{"error": "Analysis failed: Expecting value: line 1 column 1 (char 0)"}` sur les appels TradingView 1D de XRPUSDT. Ce n'était pas un bug de code — c'était une régression architecturale.

La PR #104 (24 mai) avait optimisé la Phase 2 en limitant les appels 1D aux seuls coins candidats BUY 4H. Mais cette PR avait créé un nouveau problème : le burst de 4 appels `coin_analysis 4H` en parallèle épuise le quota TradingView MCP juste avant que les appels 1D séquentiels ne démarrent. TradingView retourne alors un body vide, ce qui provoque un `JSONDecodeError` côté agent. La PR #106 (25 mai) avait déjà corrigé un problème similaire, mais à force d'optimisations successives, le burst 4H était devenu assez dense pour recréer le throttle.

Le fix de PR #194 est en trois couches. Première : un `time.sleep(15)` ajouté dans le prompt entre la fin du batch 4H et le début des appels 1D, laissant le quota TradingView se réinitialiser. Deuxième : les appels 1D passent en mode rigoureusement séquentiel (1 coin à la fois, `sleep 5s` entre chaque) au lieu de chercher à les grouper. Troisième : une gestion d'erreur silencieuse — si un appel 1D retourne `{"error": ...}`, l'agent assigne `signal_1d = "NEUTRAL"` et continue sans notification Telegram. Un flag `signal_1d_rate_limited` permet à la Phase 3 de détecter si tous les coins BUY 4H ont subi un rate limit, auquel cas le seuil de score passe automatiquement de 7 à 6 (`min_signal_score_degraded`).

Ce mode dégradé est la décision technique la plus intéressante : un coin STRONG_BUY 4H avec RSI/MACD/ADX favorables peut toujours atteindre 6/10 sans la confirmation 1D. Bloquer le cycle entier parce que TradingView est lent serait une sur-réaction — rater une opportunité réelle pour des données de confirmation manquantes.

**Changements techniques**

| Fichier | Changement |
|---|---|
| `prompts/trade_prompt.txt` | `sleep 15` post-batch 4H + appels 1D séquentiels avec `sleep 5` + try/except sur erreur 1D + `signal_1d_rate_limited` flag |
| `config.json` | Ajout de `min_signal_score_degraded: 6` pour le mode dégradé Phase 3 |

- **Doc tech** : [docs/technique/pr-194-phase-2-1d-rate-limit-handling.md](../technique/pr-194-phase-2-1d-rate-limit-handling.md)

---

### Issues fermées (1)

| # | Titre |
|---|---|
| [#193](https://github.com/yousmaaza/agent-binance/issues/193) | [FIX] Phase 2 — appels coin_analysis 1D séquentiels + sleep 15s pour éviter rate limit TradingView |

---

### Nouveaux tickets créés (3)

| # | Titre | Type |
|---|---|---|
| [#199](https://github.com/yousmaaza/agent-binance/issues/199) | [AMÉLIORATION] Enrichir CLAUDE.md avec principes généraux de développement (Think/Simplicity/Surgical) | documentation + enhancement |
| [#200](https://github.com/yousmaaza/agent-binance/issues/200) | [REC] Setup Graphify — knowledge graph MCP du codebase | enhancement + AUTO |
| [#203](https://github.com/yousmaaza/agent-binance/issues/203) | [CONFIG] Évaluer hausse max_open_positions 3→4 — opportunité score 9/10 manquée le 2026-05-30 | enhancement (analyse-config auto) |

Le ticket #199 est une initiative d'amélioration de `CLAUDE.md` : ajouter trois règles comportementales génériques (réflexion préalable, minimalisme, modifications chirurgicales) avant les règles projet-spécifiques. Cela normalise le comportement de l'IA dans les sessions futures, quel que soit le contexte.

Le ticket #203 est notable : il a été créé automatiquement à 22:09 par l'agent `analyse-config` (cron `0 20 UTC`) après avoir analysé 22 cycles sur 7 jours. L'agent a détecté qu'un cycle du 2026-05-30 à 21:23 avait un `top_score` de 9/10 et un sentiment Bullish, mais avait été bloqué par `max_open_positions=3` déjà atteint. Il propose de monter la limite à 4, avec des conditions précises pour l'appliquer (sentiment ≥ Bullish, score ≥ 8, portfolio ≥ 100 USDC) et une alternative conservatrice (position bonus conditionnelle à 0.5× sizing). C'est le premier ticket où le bot analyse ses propres cycles et génère une recommandation de configuration fondée sur des données.

---

### Matériel disponible pour illustrer

- Extrait de `logs/stdout/cycle_20260530_101921.log` : l'erreur `Expecting value: line 1 column 1` qui a déclenché le ticket #193 — illustration concrète du cycle comme oracle de régression.
- Diff `prompts/trade_prompt.txt` entre PR #104, #106 et #194 : la même erreur TradingView réapparaît deux fois sous deux formes légèrement différentes — bon exemple de la difficulté à anticiper les interactions entre optimisations.
- Issue #203 complète avec son tableau de 22 cycles et ses critères conditionnels — matériel brut d'un agent d'analyse qui raisonne sur ses propres données d'exécution.

### Idée d'angle Medium

**"La 3e occurrence d'un bug : quand le rate-limit devient un pattern architectural"**

La même erreur TradingView est apparue trois fois en 7 jours (PR #104, #106, #194), chaque fois déclenchée par une optimisation qui réintroduisait un burst d'appels. Article sur la différence entre corriger un bug et comprendre la contrainte sous-jacente — ici, TradingView MCP a un quota strict et toute stratégie d'appels parallèles le déclenche. La résolution finale (mode dégradé + seuil adaptatif) montre comment absorber une contrainte externe plutôt que de chercher à l'éviter.

**Angle secondaire — "Un agent qui analyse ses propres décisions"**
Le ticket #203 est généré par le bot à partir de 22 cycles de données. Il ne dit pas juste "augmente max_open_positions" — il qualifie les conditions d'application (sentiment, score, liquidité), propose une alternative conservatrice, et liste les risques. C'est la première fois dans ce projet qu'un agent produit une recommandation stratégique argumentée. Court article sur la différence entre logging (ce qui s'est passé) et auto-analyse (ce qu'on devrait changer).

---

## 2026-05-30 — Récap quotidien

### PR mergées (1)

#### #187 — [CONSOLIDÉ] Helpers partagés par cycle + sécurité + recommandations tech lead

- **Branche** : `feat/consolidate-helpers-sec-recs`
- **Mergée à** : 12:43 (Europe/Paris)
- **Issues fermées** : #175, #178, #179, #180, #181, #182, #183, #184, #185, #186 (10 au total)

**Récit**

La journée a commencé par un diagnostic de cycle à 04:05 UTC : le bot avait exclu Bitcoin à tort, à cause d'un rate limit Binance non géré. L'enquête a révélé la cause racine — l'agent réécrivait sa propre version allégée des helpers (`tg()`, `binance()`, `hb()`) dans chaque script de phase, en ignorant celle du prompt principal. Sans retry dans son `binance()` local, la moindre erreur API excluait le coin directement. Autre symptôme du même problème : `MONGODB_URI` était relu depuis `.env` via `source` shell (ce qui casse avec le `&` dans la chaîne de connexion), et des heredocs Python continuaient à s'infiltrer malgré l'interdiction dans CLAUDE.md.

La solution : externaliser les fonctions partagées dans un fichier temporaire généré par `runner.py` juste avant chaque cycle. L'agent importe ce fichier via `exec(open("__HELPERS_PATH__").read())` en tête de chaque script de phase — il ne peut plus "oublier" les retries ou inventer ses propres variantes.

Deux PR intermédiaires (#176 pour les helpers, #177 pour les permissions du fichier `/tmp`) ont été ouvertes en matinée. La review automatique du tech lead (CI) a produit 9 tickets `[REC]` en 3 minutes, dont un finding sécurité sérieux : le chemin `/tmp/cycle_XXXX_helpers.py` hardcodé exposait une race condition TOCTOU (Bandit B108). La PR de consolidation #187 a absorbé les deux PR initiales plus les 9 recommandations en un seul merge propre à 12:43.

**Changements techniques**

| Fichier | Changement |
|---|---|
| `binance-bot/orchestration/runner.py` | `_write_helpers_file()` via `tempfile.mkstemp()` (0o600, pas de TOCTOU) ; `_send_start_notification()` extraite ; constante `CLAUDE_PROCESS_TIMEOUT_S = 3600` ; `OSError` capturée si disque plein |
| `prompts/trade_prompt.txt` | Suppression de ~60 lignes de helpers redéfinis en dur ; remplacés par `exec(open("__HELPERS_PATH__").read())` en tête de chaque script |
| `binance-bot/botlogging/cycle_logger.py` | Ajout de `CycleLogger.warning()` — corrige 2 appels fantômes existants depuis PR #176 |
| `scripts/check_cycle_logger_methods.sh` | Script lint 25 lignes : vérifie que les appels `cycle_log.xxx()` utilisent des méthodes définies |

**Décision sécurité notable** : les secrets (`MONGO_URI`, `TELEGRAM_TOKEN`, etc.) ne sont plus injectés dans le fichier helpers par Python avant l'exécution — ils sont lus depuis `os.environ` au runtime dans le fichier lui-même. La PR #176 originale les bakeait via `repr()` dans un fichier `/tmp` world-readable (0o644). Corrigé par #177, consolidé dans #187.

- **Doc tech** : [docs/technique/pr-187-consolidate-helpers-security-recs.md](../technique/pr-187-consolidate-helpers-security-recs.md)

---

### Issues fermées (10)

Toutes fermées via PR #187 :

| # | Titre | Origine |
|---|---|---|
| [#175](https://github.com/yousmaaza/agent-binance/issues/175) | [FIX] Factoriser les helpers du prompt dans un fichier partagé par cycle | Bug signalé par l'utilisateur |
| [#178](https://github.com/yousmaaza/agent-binance/issues/178) | [REC] [SECURITY] Remplacer /tmp hardcoded par tempfile.mkstemp() | CI tech lead |
| [#179](https://github.com/yousmaaza/agent-binance/issues/179) | [REC] [REFACTOR] Réduire la complexité cyclomatique de run_trade_workflow | CI tech lead |
| [#180](https://github.com/yousmaaza/agent-binance/issues/180) | [REC] [LISIBILITÉ] Extraire le timeout du watchdog en constante | CI tech lead |
| [#181](https://github.com/yousmaaza/agent-binance/issues/181) | [REC] [ROBUSTESSE] Ajouter logging d'erreur dans _update_cost_in_mongo | CI tech lead |
| [#182](https://github.com/yousmaaza/agent-binance/issues/182) | [REC] [CLEANUP] Éliminer les lignes redondantes du prompt (PYTHON_BIN/BINANCE_CLI) | CI tech lead |
| [#183](https://github.com/yousmaaza/agent-binance/issues/183) | [REC] [FEATURE] Ajouter une méthode warning() à CycleLogger | CI tech lead |
| [#184](https://github.com/yousmaaza/agent-binance/issues/184) | [REC] [MAINTENANCE] Linter pour détecter les warning() fantômes | CI tech lead |
| [#185](https://github.com/yousmaaza/agent-binance/issues/185) | [REC] Supprimer imports TOKEN et CHAT_ID obsolètes dans runner.py | CI tech lead |
| [#186](https://github.com/yousmaaza/agent-binance/issues/186) | [REC] Tester scénario /tmp full pour robustesse des helpers | CI tech lead |

---

### Nouveaux tickets créés (19)

**10 créés et fermés dans la journée** — #175 et #178–#186 (voir ci-dessus).

**9 ouverts en fin de journée** :

| # | Titre | Type |
|---|---|---|
| [#193](https://github.com/yousmaaza/agent-binance/issues/193) | [FIX] Phase 2 — appels coin_analysis 1D séquentiels + sleep 15s pour éviter rate limits | Bug (utilisateur) |
| [#188](https://github.com/yousmaaza/agent-binance/issues/188) | [REC] Refactor template helpers vers fichier externe | CI post-PR #187 |
| [#189](https://github.com/yousmaaza/agent-binance/issues/189) | [REC] Add error handling pour streaming stdout | CI post-PR #187 |
| [#190](https://github.com/yousmaaza/agent-binance/issues/190) | [REC] Document helpers namespace isolation strategy | CI post-PR #187 |
| [#191](https://github.com/yousmaaza/agent-binance/issues/191) | [REC] Add synthetic test pour cycle_logger workflow | CI post-PR #187 |
| [#192](https://github.com/yousmaaza/agent-binance/issues/192) | [REC] Implement dry-run mode pour offline cycle testing | CI post-PR #187 |
| [#195](https://github.com/yousmaaza/agent-binance/issues/195) | [REC] Clarifier l'impact NEUTRAL Phase 3 quand 1D rate limit | CI post-PR #187 |
| [#196](https://github.com/yousmaaza/agent-binance/issues/196) | [REC] Ajouter heartbeat Phase 2 pour tracking rate limits | CI post-PR #187 |
| [#197](https://github.com/yousmaaza/agent-binance/issues/197) | [REC] Implémenter adaptive sleep intelligente pour rate limits | CI post-PR #187 |

Le ticket #193 (bug utilisateur) pointe un problème récurrent : les appels TradingView `coin_analysis 1D` en parallèle en Phase 2 déclenchent des rate limits API. Solution envisagée : passer en séquentiel avec `sleep 15s` entre chaque appel, et utiliser `signal_1d = "NEUTRAL"` si le timeout est atteint.

---

### Matériel disponible pour illustrer

- Diff de `runner.py` : passage de `open("/tmp/cycle_...")` vers `tempfile.mkstemp()` — bonne illustration d'un fix sécurité minimaliste (3 lignes changées, un finding Bandit résolu, une race condition éliminée).
- Screenshot du board GitHub : 9 tickets `[REC]` créés par `github-actions[bot]` en moins de 3 minutes après l'ouverture de PR #176 — illustration concrète de l'automatisation CI → backlog.
- Script `scripts/check_cycle_logger_methods.sh` (25 lignes) : lint artisanal sur mesure, sans framework de test.
- Log du cycle 04:05 UTC avec l'exclusion incorrecte de BTC due au rate limit sans retry — point d'entrée narratif naturel.

### Idée d'angle Medium

**"La boucle fermée : un bug à 4h du matin, 10 tickets fermés à midi"**

Le 30 mai condense tout le pipeline en une journée : cycle qui détecte un bug en prod → issue créée manuellement → 2 PR ouvertes → CI génère 9 tickets [REC] automatiquement (dont un finding sécurité sérieux) → PR de consolidation qui ferme les 10 issues d'un coup → bot prêt à redémarrer en 3h. Angle narratif : la trace complète de cause (rate limit BTC à 4h) → effet (10 commits, 3 PRs, 9 tickets auto) est entièrement visible dans le repo. C'est une démonstration de ce que "traçabilité complète" veut dire dans un projet géré par des agents.

**Angle secondaire — "La sécurité comme sous-produit de l'automatisation"**
La race condition TOCTOU n'aurait probablement pas été détectée en review humaine rapide. C'est Bandit lancé en CI qui l'a flaggée, traduite en ticket `[REC]` par l'agent tech lead, implémentée dans la PR de consolidation. Le pipeline de qualité a fait le travail sans friction humaine consciente.

---

## 2026-05-29 — Récap quotidien

### PR mergées (0)

Aucune PR mergée sur `main` aujourd'hui.

### Événements PR notables

#### PR #166 ouverte — [CONSOLIDATION] #145 #146 #147 #148 #149 + 4 bugfixes post-cycle
- **Ouverte à** : 11:55 (Europe/Paris) — toujours en review en fin de journée
- **Branche** : `feat/consolidation-145-146-147-148-149`
- **Quoi** : les 5 PR individuelles (#150 à #154), ouvertes hier, ont été fermées ce matin à 11:56 et remplacées par une PR unique qui consolide leurs changements. La raison : un conflit de merge était détecté entre #145 (écriture atomique dans `state_manager.py`) et #147 (unification du module `json` dans le même fichier) — résoudre le conflit une fois dans une branche dédiée est plus propre que de le faire lors de deux merges successifs.

  La PR couvre les 5 issues consolidées :

  | Issue | Contenu |
  |-------|---------|
  | #145 | Écriture atomique de `trade_history.json` via `os.replace()` + validation JSON au boot + backup automatique |
  | #146 | Garantir un `hb(N)` par phase dans le TRADE_PROMPT — Phase 7 complète les heartbeats manquants avec statut `"recovered"` |
  | #147 | Unification de tous les imports `json as _json / _hb_json / _pf_json` en un seul `import json` |
  | #148 | Instruction explicite en tête du prompt : utiliser `.venv/bin/python3` (évite la résolution vers anaconda sur Mac) |
  | #149 | Table de référence `binance-cli` dans le prompt — 10 commandes essentielles avec exemples JSON |

  Dans l'après-midi, suite aux bugs révélés par le cycle `cycle_20260529_162033`, la PR a été mise à jour pour inclure 4 bugfixes supplémentaires (#168, #169, #170, #171 — détaillés ci-dessous).

- **Pourquoi c'est intéressant pour Medium** : la PR #166 incarne deux patterns distincts réunis dans un seul artefact. (1) La consolidation de branches en conflit — décision technique de rassembler 5 features dans une seule PR pour absorber les conflits de merge en un seul endroit. (2) Le cycle de feedback en temps réel — une exécution du bot à 18h20 révèle des bugs qui intègrent directement la PR ouverte le matin. Le cycle `cycle_20260529_162033` a joué le rôle d'un test d'intégration grandeur nature.

### Issues fermées (0)

Aucune issue fermée aujourd'hui.

### Nouveaux tickets (6)

Deux vagues de création :

**Vague 1 — ~11:58 Paris (#167)** : review tech-lead automatique déclenchée à l'ouverture de PR #166.
- **#167** — [REC] Refactor `main_loop()` avec dispatch table pour handlers — `enhancement + tech-lead-review + AUTO`. La cascade `if/elif` qui gère 8+ commandes Telegram (complexité cyclomatique C = 17) doit être remplacée par un dictionnaire de handlers. Recommandation issue du reviewer automatique.

**Vague 2 — ~18:43-18:44 Paris (#168–#172)** : post-mortem automatique du cycle `cycle_20260529_162033` (exécuté à 18:20 Paris).
- **#168** — [BUG] `BINANCE_CLI` path non injecté dans `TRADE_PROMPT` — l'agent perd ~5 min par cycle à chercher le chemin absolu de `binance-cli` (`/Users/.../.nvm/.../bin/binance-cli`) car subprocess Python n'hérite pas du PATH nvm. Fix attendu : `shutil.which("binance-cli")` au démarrage de `webhook_server.py`, injectée via `__BINANCE_CLI_PATH__` dans le template.
- **#169** — [BUG] Table `binance-cli` : commande `24hr-stats` inexistante — la table de référence ajoutée par PR #149 documente une commande qui n'existe pas. La bonne commande est `ticker24hr`. L'agent l'a découvert en live lors du cycle.
- **#170** — [BUG] `binance-cli` retourne `'Request failed after 3 retries'` (non-JSON) — le helper `binance()` ne gère pas ce cas, provoque un crash sur `json.loads()`. Fix attendu : détection de la réponse non-JSON + retry x3 avec backoff.
- **#171** — [BUG] JSONL phases : doublons si un script de phase est re-exécuté — `hb(N)` peut être appelé plusieurs fois pour la même phase (observé 3 fois pour la phase 1 dans le cycle de référence). La vérification Phase 7 détecte les phases manquantes mais pas les doublons. Fix : `hb()` réécrit le fichier avec déduplication plutôt qu'appender.
- **#172** — [AMÉLIORATION] Maintenir une `usdc_whitelist` dans `config.json` — sur 20 coins candidats, 16 sont systématiquement éliminés TYPE_D (paire USDC introuvable sur Binance). ~30s et des appels binance-cli inutiles à chaque cycle. Whitelist proposée : `["BTC", "ETH", "SOL", "XRP", "SUI", "BNB", "AVAX", "DOT", "LINK", "ADA", "MATIC", "NEAR"]`.

Les tickets #168–#172 ont été créés directement depuis les logs `logs/stdout/cycle_20260529_162033.log`, ce qui en fait des retours d'expérience factuels, pas des spéculations.

### Matériel disponible pour l'article

- **PR #166 ouverte** : diff complet des 5 issues consolidées + 4 bugfixes post-cycle — branche `feat/consolidation-145-146-147-148-149`
- **Log cycle de référence** : `logs/stdout/cycle_20260529_162033.log` — contient les erreurs brutes qui ont généré les 5 tickets
- **Log JSONL** : `logs/cycle_20260529_162033_phases.jsonl` — phase 1 dupliquée 3 fois (illustration du bug #171)
- **Issues fraiches** : #168-172 — créées 23 min après le cycle, tracent la chaîne observation → ticket en temps réel

### Idée d'angle Medium

**Angle 1 — "Le cycle comme test d'intégration"**
Le cycle `cycle_20260529_162033` a tourné à 18:20 et révélé 4 bugs en 23 minutes : PATH manquant, commande inexistante, non-JSON non géré, doublons JSONL. Tous ont été transformés en tickets structurés et intégrés à la PR en cours d'ici 20h13. Article sur la valeur des logs de cycle comme oracle de qualité — pas des tests unitaires, mais l'environnement réel avec Binance, bcp de rate limits et un prompt qui s'exécute comme un programme.

**Angle 2 — "Consolider 5 branches en conflit sans perdre l'historique"**
Plutôt que de merger #145-149 dans l'ordre en résolvant les conflits un par un (risque d'erreur, perte de contexte), une PR de consolidation repart de `main` et intègre toutes les features dans un diff unique. Pattern utile pour les projets où plusieurs agents ouvrent des PRs en parallèle sur les mêmes fichiers — le conflit de merge est inévitable, la consolidation manuelle reste la solution la plus lisible.

---

## 2026-05-28 — Récap quotidien

### PR mergées (12)

#### #122 — [FEAT] Générer `state/cycle_log.jsonl` après chaque cycle
- **Branche** : `feat/issue-121-generer-state-cycle-log-jsonl`
- **Mergée à** : 17:43 (Europe/Paris)
- **Quoi** : ajout d'une Phase 8 dans le `TRADE_PROMPT`. À la fin de chaque cycle, l'agent écrit une ligne JSON dans `state/cycle_log.jsonl` (append-only, rotation à 90 lignes max), puis commit + push sur le repo via `git-perso`. Champs : `cycle_id`, `top_score`, `executed`, `skipped`, `skip_type`, `skip_detail`, `portfolio`, `sentiment`, `open_positions`. `binance-bot/core/env.py` crée le fichier vide au démarrage si absent.
- **Pourquoi c'est intéressant pour Medium** : donne au bot une trace légère et versionnée dans git, sans dépendre de MongoDB pour la santé quotidienne. On peut `grep` un cycle dans le repo sans ouvrir Atlas. Autre angle : le push git depuis un sous-processus Claude — le `bash -i -c "git-perso && ..."` pour charger l'alias zsh est le genre de détail qu'on ne trouve que dans les projets réels.
- **Doc tech** : [docs/technique/pr-122-cycle-log-jsonl.md](../technique/pr-122-cycle-log-jsonl.md)

#### #140 — feat(ci): post-review déclenche `binance-dev-auto` sur tickets [REC]
- **Branche** : `feat/post-review-trigger-binance-dev-auto`
- **Mergée à** : 17:22 (Europe/Paris)
- **Quoi** : ferme la boucle d'automatisation de la CI. Avant : les tickets `[REC]` créés par le tech-lead-reviewer après une review restaient en attente d'implémentation manuelle. Après : le prompt `ticket-manager` exécute `gh workflow run binance-dev-auto.yml -f issue_number=N` pour chaque ticket `[REC] + AUTO` créé, avec un `sleep 10` entre dispatches. Deux scripts bash utilitaires ajoutés : `dispatch_rec_tickets.sh` (rejouer le dispatch sur l'existant) et `label_rec_auto.sh` (migrer les tickets historiques sans label `AUTO`).
- **Pourquoi c'est intéressant pour Medium** : illustration directe du pattern "agent qui déclenche un agent". La review produit des tickets → les tickets déclenchent une implémentation → l'implémentation ouvre une PR. Zero clic humain entre la review et la branche de code. C'est la feature de la journée.
- **Doc tech** : [docs/technique/pr-140-post-review-trigger-binance-dev-auto.md](../technique/pr-140-post-review-trigger-binance-dev-auto.md)

#### #130 + #131 + #133 — Réparation + validation du pipeline CI automation
- **Mergées à** : 13:11 (#130), 13:11 (#131), 13:18 (#133) (Europe/Paris)
- **Quoi** :
  - **#130** : corrige le trigger du workflow `binance-dev-auto`. Le webhook `projects_v2_item` ne fonctionne que sur les organisations GitHub — sur un compte personnel il retournait `Unexpected value`. Migré vers `workflow_dispatch` avec inputs explicites (`issue_number`, `item_node_id`). Ajout d'une vérification du label `AUTO` avant de lancer l'agent.
  - **#131** : améliore `claude-post-review.yml` — création du label `tech-lead-review` (idempotent) avant l'agent, application automatique du label + passage du statut Backlog → In progress sur chaque ticket créé.
  - **#133** : ticket de validation bout-en-bout du pipeline : déclenchement via `gh workflow run`, vérification label AUTO, création branche, PR ouverte, ticket basculé "In review". ✅ Recette passée.
- **Pourquoi c'est intéressant pour Medium** : le détail `projects_v2_item` vs compte personnel est une vraie embûche GitHub Actions non documentée clairement. Bon exemple de débogage par contraintes de plateforme, pas par bug de code.
- **Doc tech** : [pr-130](../technique/pr-130-workflow-dispatch.md) — [pr-131](../technique/pr-131-post-review-auto-tag.md) — [pr-133](../technique/pr-133-test-workflow-binance-dev.md)

#### #134 + #135 — Qualité code : except typés et champ `trigger` dans les heartbeats
- **Mergées à** : 15:28 (#134), 15:30 (#135) (Europe/Paris)
- **Quoi** :
  - **#134** : remplace les `except Exception:` nus dans `binance-bot/core/lock.py`, `telegram.py` et `runner.py` par des types précis (`OSError`, `json.JSONDecodeError`). Ajout de logging sur les exceptions capturées.
  - **#135** : injecte un placeholder `__TRIGGER__` dans `runner.py` → disponible en variable `_trigger` dans le prompt → inclus dans chaque ligne JSONL `hb()` et dans le document MongoDB. Valeurs : `manual` (commande `/trade`) ou `auto` (scheduler 4h). Prépare le watchdog (issue #7) à distinguer les deux types de cycle.
- **Doc tech** : [pr-134](../technique/pr-134-qualifier-les-except-generiques.md) — [pr-135](../technique/pr-135-add-trigger-heartbeat.md)

#### #141 + #142 + #144 — Robustesse du prompt : skip_types, format date, variables Phase 7
- **Mergées à** : 17:32 (#141), 17:33 (#142), 17:47 (#144) (Europe/Paris)
- **Quoi** :
  - **#141** : ajoute une section "Cycles de trading : skip_type et skip_detail" dans `CLAUDE.md`. Tableau des 4 types (TYPE_A à TYPE_D), exemples de `skip_detail`, utilité pour le debug. Documentation pure, zéro code modifié.
  - **#142** : documente et justifie le format `%Y-%m-%dT%H:%M:%SZ` **avec secondes** dans Phase 8. Le format sans secondes (`%H:%M`) serait insuffisant car les 7 phases d'un cycle s'exécutent en < 60s — les timestamps seraient identiques.
  - **#144** : initialise explicitement `top_score`, `executed`, `skipped`, `skip_type`, `skip_detail`, `sentiment`, `portfolio_total`, `open_positions` en tête du prompt, avec fallbacks redondants en Phase 7. Évite les `UnboundLocalError` si une phase échoue partiellement avant la persistance Mongo. *(Note : PR #143 a précédé #144 dans la même journée — même issue #125, #144 est la version finale retenue.)*
- **Doc tech** : [pr-141](../technique/pr-141-documenter-skip-types.md) — [pr-142](../technique/pr-142-clarify-date-format.md) — [pr-144](../technique/pr-144-verify-variable-definitions.md)

#### #120 — docs: article 01 publié sur Medium
- **Mergée à** : 12:40 (Europe/Paris)
- **Quoi** : clôture du ticket de tracking #119. Le fichier `docs/medium-articles/01-setup-projet-prompt-mcp.md` passe en statut `published`. Article disponible sur Medium (URL dans l'issue).

### Issues fermées (22)

**Fermées par leurs PR respectives :**
- **#121** — [FEAT] Générer state/cycle_log.jsonl — fermée par #122
- **#125** — [REC] Vérifier définition des variables Phase 3/5/6 — fermée par #143 puis #144
- **#124** — [REC] Clarifier format date Phase 8 — fermée par #142
- **#128** — [REC] Documenter TYPE_A/B/C/D skip_type — fermée par #141
- **#132** — [REC] Test workflow binance-dev-auto — fermée par #133
- **#31** — [REC] Ajouter champ trigger dans heartbeat JSONL — fermée par #135
- **#27** — [REC] Remplacer bare except par except typés — fermée par #134

**Batch de triage ~15h (Paris) — tickets REC obsolètes :**
Les issues #44, #62, #67, #69–#78, #109, #110 ont été fermées manuellement. Ce sont des tickets `[REC]` anciens liés à une refactorisation en modules qui avait déjà été implémentée progressivement (#69 → `binance-bot/core/`, #70 → `core/env.py`, etc.). Nettoyage du board après validation que le code cible était déjà en place.

### Nouveaux tickets (28 créés)

Trois vagues de création aujourd'hui, toutes issues de reviews tech-lead :

**Vague 1 — ~12:47 Paris (#121, #123–#127, #128)** : suite directe de la PR #122 (cycle_log.jsonl). Tickets de robustesse et de suivi : rotation du fichier (#126), centraliser le chemin en constante (#127), context manager pour `open()` (#123).

**Vague 2 — ~15:17 Paris (#136–#139)** : issues Mypy/Bandit/logging sur `runner.py` et les fonctions Mongo :
- **#136** — Mypy : type guard sur `process.stdout` (runner.py:113)
- **#137** — Clarifier exceptions silencieuses dans `_update_cost_in_mongo`
- **#138** — Bandit B603 : documenter absence d'untrusted input dans subprocess
- **#139** — Ajouter logging DEBUG pour succès Mongo

**Vague 3 — ~18:08 et ~18:37 Paris (#145–#165)** : nouvelle review tech-lead automatique déclenchée par les merges de l'après-midi. Tickets de la seconde vague :
- **#145** — Protéger `state/trade_history.json` contre écritures corrompues (write atomique + validation au boot)
- **#146** — Garantir un `hb(N)` par phase dans le TRADE_PROMPT
- **#147** — Supprimer le conflit `json/_json` dans `prompts/trade_prompt.txt`
- **#148** — Imposer `.venv/bin/python3` dans le TRADE_PROMPT
- **#149** — Documenter les commandes `binance-cli` utiles dans le TRADE_PROMPT
- **#155–#165** — Suite de la revue : variable `e` inutilisée, `__import__`, cleanup backups, helper `_safe_read_json`, monitoring taille state…

Total en fin de journée : 23 tickets ouverts (28 créés − 5 fermés dans la journée).

### Matériel disponible pour l'article

- **Diff PR #140** : `git show bb84b9c --stat` — workflow + 2 scripts bash
- **Diff PR #122** : `git show b94e0ac --stat` — Phase 8 JSONL dans `prompts/trade_prompt.txt`
- **Doc tech #122** : `docs/technique/pr-122-cycle-log-jsonl.md` — schéma de la chaîne Phase 3→5→8 avec variables
- **Doc tech #140** : `docs/technique/pr-140-post-review-trigger-binance-dev-auto.md` — diagramme avant/après du flux review → implémentation
- **Fichier vivant** : `state/cycle_log.jsonl` — 2 lignes réelles de cycles du 28 mai (commits `363cac6`, `c7b5ee4`)
- **Scripts** : `dispatch_rec_tickets.sh`, `label_rec_auto.sh` — bon matériel pour illustrer la migration manuelle → auto

### Idée d'angle Medium

**Angle 1 — "De la review au code sans intervention humaine"**
La journée du 28 mai illustre un pipeline complet : une review tech-lead génère des tickets, les tickets déclenchent automatiquement `binance-dev`, qui ouvre une PR. PR #130 (fix trigger), PR #131 (auto-tag), PR #133 (test recette), PR #140 (bouclage de la boucle). Quatre PR dans la même journée pour construire une chaîne où le travail répétitif est entièrement éliminé. Article sur le design de pipelines "agent-to-agent" — avec les pièges réels (webhook `projects_v2_item` non supporté sur compte perso, race conditions entre dispatches, label `AUTO` comme garde-fou).

**Angle 2 — "Le cycle_log.jsonl : quand git devient la base de monitoring"**
Stocker les métriques de chaque cycle dans un fichier JSONL commité donne une chose qu'on n'a pas en MongoDB : l'historique est versionné, diff-able, grep-able localement. Article sur les patterns de traçabilité légère pour les projets LLM — MongoDB pour le détail, JSONL pour la vue d'ensemble, logs pour le debug. Trois niveaux de granularité, trois cas d'usage distincts.

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

### Issues fermées (2)
- **#105** — [OPT] Phase 1 filtre paires USDC non tradables + Phase 2 appels 1D séquentiels — fermée par PR #106 — [lien](https://github.com/yousmaaza/agent-binance/issues/105)
- **#119** — [ARTICLE] 01 — Setup d'un bot de trading piloté par Claude + MCP TradingView — fermée à 20:56 (issue de tracking article 01, premier article publié) — [lien](https://github.com/yousmaaza/agent-binance/issues/119)
- Aucune autre issue fermée aujourd'hui.

### Nouveaux tickets (10)

Tickets créés aujourd'hui — dont 9 `[REC]` auto-créés par `tech-lead-reviewer` (auteur : `github-actions[bot]`) suite à la review PR #107, et 1 ticket utilisateur :

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
