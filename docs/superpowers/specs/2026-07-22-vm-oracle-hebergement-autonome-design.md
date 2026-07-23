# Hébergement autonome du bot sur VM Oracle Cloud (Always Free)

## Contexte et problème

Le bot (`binance-bot/webhook_server.py`) tourne aujourd'hui exclusivement sur le Mac de l'utilisateur, lancé en `nohup`. Il dépend donc de la machine allumée : si le Mac est éteint ou en veille, ni les cycles de trading automatiques (toutes les 4h) ni les commandes Telegram interactives (`/trade`, `/status`, `/perf`, `/reset`) ne fonctionnent.

Un plan de déploiement VPS Hetzner avait été évoqué avant ce projet mais jamais implémenté (cf. `CLAUDE.md`). Cette évolution le remplace par une VM toujours active, suite à une demande explicite de l'utilisateur.

**Pivot (2026-07-23)** : l'option initialement retenue (VM Oracle Cloud "Always Free", Ampere A1 ARM) a été abandonnée en pratique après plusieurs erreurs `Out of capacity` bloquantes sur les shapes ARM et AMD gratuits d'Oracle, dans la seule région disponible pour ce compte (`EU-PARIS-1-AD-1`) — un problème connu et récurrent sur ce tier gratuit, pas un choix de conception à remettre en cause. Bascule sur une **VPS Hostinger payante** (x86_64, quelques euros/mois), qui simplifie même l'exécution (plus de question de compatibilité ARM, retour à un Ubuntu/`apt` standard). Le reste de l'analyse ci-dessous (architecture, MCP, quota Claude Pro, fiabilité) reste valide à l'identique — seul le choix du fournisseur de VM change.

## Objectif

Faire tourner le bot de façon totalement autonome, sans dépendre du Mac — interactif ET cycles automatiques inclus. Le Mac arrête de faire tourner une instance en production ; il reste l'environnement de développement (branches, PR, `binance-dev`).

## Approches envisagées

### Option écartée : routine cloud planifiée Claude Code
Investiguée en premier car sans serveur à gérer. Écartée après vérification concrète : les routines cloud (CCR) tournent dans un environnement Anthropic isolé qui ne peut attacher que des connecteurs MCP claude.ai enregistrés (Exa, Notion, Google Calendar, Gmail, Google Drive) — ni `tradingview` ni `telegram-assistant` (serveurs MCP locaux du projet, définis dans `.mcp.json`) n'y sont accessibles. Sans TradingView, les Phases 1-2 (analyse marché) ne peuvent pas fonctionner. Pas de mécanisme identifié non plus pour injecter les secrets (`.env`) dans cet environnement.

### Option retenue : VM Oracle Cloud "Always Free" (Ampere A1, ARM)
Une VM Linux classique lève tous les blocages de l'option précédente : c'est un environnement où le CLI `claude` tourne normalement, avec accès à `.mcp.json` comme sur le Mac aujourd'hui. Gratuite en permanence (pool always-free : jusqu'à 4 OCPU / 24 Go RAM ARM), largement suffisante pour ce usage (process léger, actif par intermittence).

## Architecture

Une seule instance vivante, sur la VM :

- `binance-bot/webhook_server.py` tourne en continu via **systemd** (pas `nohup`) : long-polling Telegram (interactif) + auto-scheduler interne 4h (règle CLAUDE.md #7, logique inchangée — seule sa localisation change).
- **État sur disque local de la VM** : `state/`, `logs/` vivent normalement sur la VM, comme aujourd'hui sur le Mac. Pas de synchronisation d'état inter-machines à construire (contrairement à l'option cloud routine écartée) — un seul process, une seule source de vérité.
- Le commit/push git de `state/trade_history.json` et `state/cycle_log.jsonl` (fix #360, PR #361) continue de servir de backup/historique versionné, mais n'est plus un mécanisme de persistance vital entre exécutions.
- Le Mac ne fait plus tourner de bot en production. Workflow ticket → branche → PR → merge inchangé ; seule la étape de déploiement change (déployer sur la VM après merge au lieu de `pkill` + relancer localement).

## Provisioning / migration — checklist VM

1. **Instance Oracle** : Ampere A1 (ARM/aarch64), Ubuntu, dans le pool always-free (2 OCPU / 12 Go suffisent). Sécurité réseau : aucun port entrant à ouvrir à part SSH — cohérent avec le principe polling-only du projet (`CLAUDE.md` : "aucun port entrant, aucun tunnel").
2. **Environnement** :
   - Python 3.11 + venv `.venv/` (règle CLAUDE.md #1 : jamais de python global)
   - `git`
   - `uv`/`uvx` (nécessaire pour le serveur MCP `tradingview`, lancé via `uvx --from tradingview-mcp-server tradingview-mcp` — aucune autre config requise, portable tel quel)
   - Claude Code CLI (support Linux ARM64 à vérifier au moment de l'installation)
   - `kraken-cli` via `cargo install` (compilation native ARM à confirmer — pas de raison structurelle que ça échoue, mais non testé)
3. **Clone du repo** `yousmaaza/agent-binance` + `.env` recréé manuellement sur la VM (jamais commité), mêmes clés que sur le Mac (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `MONGODB_URI`, `MONGODB_DB`, clés API Kraken).
4. **`.mcp.json`** : le serveur `telegram-assistant` référence aujourd'hui un chemin absolu Mac (`/Users/yousrimaazaoui/.claude/mcp-servers/telegram-assistant-mcp/mcp_telegram_tool.py`). Le script doit être copié sur la VM et le chemin corrigé pour pointer vers son nouvel emplacement.
5. **Auth Claude CLI** : login avec le compte Pro existant de l'utilisateur (copie des identifiants ou nouveau login OAuth sur la VM — à tester).
6. **systemd service** pour `webhook_server.py` : `Restart=on-failure`, activé au boot (`systemctl enable`) pour survivre à un reboot/maintenance de la VM.

## Point d'incertitude — quota Claude Pro partagé

Le CLI `claude` est aujourd'hui authentifié via l'abonnement Pro de l'utilisateur (pas de clé API). Les logs de coût (MongoDB, mode `abonnement`) montrent un coût équivalent d'environ 1,2 à 2,7 USD par cycle. Faire tourner les cycles automatiques (6/jour) sur la même VM sous le même abonnement Pro signifie que cet usage compte sur le **même quota** que l'usage interactif de l'utilisateur — avec un risque non quantifié de heurter une limite hebdomadaire partagée.

**Décision** : déployer et observer empiriquement pendant une semaine plutôt que de chercher une garantie a priori. Si les cycles automatiques commencent à être rate-limités, isoler une clé API (`ANTHROPIC_API_KEY`) pour la VM uniquement, en gardant l'abonnement Pro pour l'usage interactif du Mac en dev.

## Fiabilité / supervision

- **systemd** gère le redémarrage du process (crash) et du service au boot (reboot de la VM).
- **Pas de heartbeat custom ajouté** : chaque cycle (toutes les 4h) envoie déjà une notification Telegram par phase. Un silence de plus de 4-5h est un signal naturel de problème, sans code de supervision supplémentaire.
- **Risque résiduel accepté** : si la VM entière tombe (pas juste le process), rien n'alerte activement au-delà de ce silence. Pas de monitoring externe ajouté pour l'instant (cohérent avec le principe de minimalisme du projet). Option non retenue mais mentionnée : alarme Oracle Cloud (gratuite) sur arrêt d'instance, à ajouter plus tard si besoin.

## Tests et bascule

1. Provisionner et configurer la VM (section provisioning) sans encore couper le Mac.
2. Tests de validation sur la VM, bot du Mac arrêté pendant le test pour éviter tout doublon de cycle :
   - `/status`, `/perf` répondent en moins de 5s depuis Telegram
   - Un cycle manuel `/trade` complet s'exécute sans erreur (Phases 0-8, y compris les appels MCP `tradingview` et `telegram-assistant`)
   - Reboot de la VM → le bot redémarre seul (`systemctl enable` + auto-scheduler reprend son prochain slot)
3. Semaine d'observation : usage du quota Pro (point d'incertitude ci-dessus), stabilité ARM de `kraken-cli`.
4. Bascule définitive une fois validé : le Mac ne relance plus jamais le bot en prod. `CLAUDE.md` mis à jour en conséquence (chemins, workflow de déploiement).
5. Rollback si besoin (quota Pro épuisé trop vite, instabilité ARM) : reprise temporaire sur le Mac le temps de résoudre — aucune logique métier n'est modifiée par cette évolution, uniquement l'hébergement, donc le rollback ne casse rien côté code.

## Hors périmètre

- Aucun changement de la logique de trading (phases, scoring, sizing, exécution) — cette évolution est purement une migration d'hébergement.
- Pas de passage à un webhook Telegram réel (le long-polling est conservé, cohérent avec le principe polling-only).
- Pas de monitoring externe actif à ce stade (voir section Fiabilité).
