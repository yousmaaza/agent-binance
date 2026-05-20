# Instructions Claude pour ce projet

Bot de trading Binance piloté par Telegram. Architecture polling-only : aucun port entrant, aucun tunnel.

## Stack

- `scripts/webhook_server.py` : process Python unique qui poll Telegram en long-polling (timeout 30s) ET déclenche un sous-processus Claude (`claude --print --dangerously-skip-permissions <prompt>`) à chaque commande `/trade` ou tous les 4h via l'auto-scheduler.
- Le sous-processus Claude reçoit `TRADE_PROMPT` (variable à la racine de `webhook_server.py`) qui décrit 7 phases d'exécution.
- État persistant dans `state/` (JSON files). Logs dans `logs/`. MongoDB Atlas pour la collection `cycles`.

## Règles de modification non négociables

### 1. Tous les appels Telegram passent par `curl` via subprocess, jamais `urllib`

`urllib.request` échoue avec `[Errno 8] nodename nor servname provided` en contexte nohup sur le Mac de l'utilisateur (résolution DNS IPv6 mais pas de connectivité IPv6). `curl` fonctionne dans tous les contextes. La fonction `tg_post()` de `webhook_server.py` utilise déjà curl — quand tu ajoutes du code Telegram dans le `TRADE_PROMPT` (qui s'exécute dans le sous-processus Claude), utilise le helper `tg()` défini en tête du prompt, qui shell out vers curl.

### 2. Aucun secret hardcodé — tout vient de `.env`

`webhook_server.py` charge `.env` au démarrage via `_load_env()`. Les secrets attendus :
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (obligatoires)
- `MONGODB_URI`, `MONGODB_DB` (optionnels — si absents, le bot tourne mais `/raisonnement` et la Phase 7 retournent un warning)

Si tu ajoutes une nouvelle dépendance externe avec credentials, ajoute la clé dans `.env`, `.env.example`, et **jamais** en dur dans le code. Les anciens scripts shell (`bot_daemon.sh`, `start_webhook.sh`, `run_trade.sh`) sont legacy v1 mais ont aussi été migrés vers `.env`.

### 3. `PROJECT_DIR` est dynamique

```python
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

Jamais de chemin Mac hardcodé. Le projet doit pouvoir tourner sur un VPS Linux sans modification.

### 4. Stdout et stderr du sous-processus Claude sont **toujours** sauvegardés

À chaque cycle, `run_trade_workflow()` génère un `cycle_id = YYYYMMDD_HHMMSS` (UTC) et écrit :
- `logs/stdout/cycle_{cycle_id}.log` : sortie brute Claude
- `logs/stderr/cycle_{cycle_id}.log` : erreurs Claude

Même en cas d'exit code non-zéro. Ne supprime jamais cette capture — c'est la seule façon de debugger un cycle qui plante avant la Phase 7 (qui écrit en Mongo).

### 5. Convention horaire : interne UTC, affichage local

- Toute logique interne (`next_4h_slot`, comparaisons, timestamps Mongo) en UTC
- Tout affichage utilisateur (notifications Telegram) en heure locale via `fmt_local()` / `fmt_next()`
- Les slots auto sont alignés sur les clôtures TradingView 4h : 00:05, 04:05, ..., 20:05 **UTC**

### 6. Auto-scheduler dans la main loop, pas via cron/systemd

L'auto-scheduler vit dans `main_loop()` de `webhook_server.py` — il déclenche `run_trade_workflow(trigger="auto")` au prochain slot 4h. Ne le déplace pas vers cron : la loop de polling Telegram est déjà toujours active, donc autant en profiter pour scheduler.

## Workflow type d'une modification

1. **Modifier `scripts/webhook_server.py`** ou `config.json`
2. **Test syntaxe Python** : `python3 -c "import ast; ast.parse(open('scripts/webhook_server.py').read())"`
3. **Redémarrer le bot** :
   ```bash
   pkill -f webhook_server.py
   nohup python3 -u scripts/webhook_server.py >> state/daemon.log 2>&1 &
   ```
4. **Vérifier le startup** : `tail -10 state/daemon.log` doit montrer "🚀 Bot v2 démarré" et la ligne "Prochain cycle auto"
5. **Test fonctionnel** : envoyer `/status` depuis Telegram → réponse en < 5s

Pas besoin de tests unitaires pour ce projet — c'est un bot mono-fichier piloté par interactions Telegram. Le test, c'est la commande qui arrive et la notification qui repart.

## Debug d'un cycle qui plante

1. `tail -20 state/daemon.log` → erreur côté webhook_server
2. `ls -lt logs/stderr/ | head -5` → identifier le dernier cycle qui a échoué
3. `cat logs/stderr/cycle_YYYYMMDD_HHMMSS.log` → erreur Claude/MCP/Binance
4. Si Mongo configuré : interroger la collection `cycles` filtrée par `status: "error"`
5. Si le lock est resté coincé (`agent_lock.json` avec `running: true`) : envoyer `/reset` depuis Telegram

## Quand modifier le `TRADE_PROMPT`

Le `_TRADE_PROMPT_TEMPLATE` (dans `webhook_server.py`) est injecté dans le sous-processus Claude. Trois substitutions automatiques :
- `__BOT_TOKEN__` → `TELEGRAM_TOKEN`
- `__CHAT_ID__` → `TELEGRAM_CHAT_ID`
- `__PROJECT_DIR__` → chemin absolu du projet
- `__CYCLE_ID__` → remplacé **à chaque cycle** dans `run_trade_workflow` (pas au démarrage)

Si tu ajoutes une nouvelle variable substituée, suit le même pattern : `__TOKEN_NAME__` dans le template, `.replace("__TOKEN_NAME__", value)` côté Python.

Le prompt demande à Claude d'exécuter du code Python qui appelle `binance-cli` via subprocess. Ne mets jamais `binance-cli` directement dans `webhook_server.py` — c'est l'agent qui orchestre, pas le serveur.

## Ne pas faire

- ❌ Démarrer un nouveau tunnel Cloudflare ou ngrok : le réseau corporate de l'utilisateur bloque QUIC (UDP 7844), TCP 7844, et les DNS trycloudflare.com. Polling-only.
- ❌ Re-introduire `urllib.request` pour Telegram (cf. règle 1)
- ❌ Ajouter des dépendances lourdes (scipy, pandas) : le bot doit rester un script Python standalone. Math stats sont déjà implémentées à la main dans `run_perf()`.
- ❌ Créer des fichiers `.md` documentaires sauf si l'utilisateur le demande explicitement.
- ❌ Modifier `state/trade_history.json` manuellement sans backup — c'est la source de vérité pour `/perf`.

## Notes contextuelles

- L'utilisateur est francophone. Toutes les notifications Telegram et les `explanation_fr` doivent être en français vulgarisé (sans jargon crypto).
- Le bot est destiné à tourner sur le Mac de l'utilisateur. Un plan de déploiement VPS Hetzner existait précédemment mais n'est pas implémenté — ne pas y revenir sans demande explicite.
- L'environnement Python du Mac est `anaconda3` (Python 3.11). `pymongo` et `loguru` sont déjà installés globalement.
