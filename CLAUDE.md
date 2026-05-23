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

### 7. Python via venv `.venv` (3.11) et profil shell `git-perso` obligatoires

**Tout** appel à `python`, `pip`, ou installation de package se fait depuis le venv local du projet en Python 3.11. **Tout** appel à `git` ou `gh` qui touche au remote se fait après avoir chargé le profil perso via `git-perso`.

**Création initiale du venv** (si `.venv/` absent) :
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

**Activation à chaque session de travail** :
```bash
source .venv/bin/activate
git-perso   # alias shell : charge l'identité git perso + index pip
python --version   # doit afficher Python 3.11.x
```

- Le venv `.venv/` est **gitignoré** — chaque machine recrée le sien.
- `git-perso` est un alias/script perso installé globalement sur le shell de l'utilisateur (zsh). Il configure `user.email`, `user.name`, le `signingkey` et l'index pip pour que les `git commit`, `git push`, `pip install` partent avec la bonne identité et les bons repos. Sans lui, les commits peuvent être attribués au mauvais compte ou un `pip install` peut résoudre des packages depuis un index pro.
- Toute commande dans la doc qui dit `python3 -c "..."` doit en pratique être lancée **après** `source .venv/bin/activate` (le binaire `python` du venv pointe alors vers le 3.11 attendu).
- Le `nohup python3 -u scripts/webhook_server.py ...` du daemon doit pointer vers `.venv/bin/python` (chemin absolu) si lancé en dehors d'un shell où le venv est activé.

## Workflow type d'une modification

0. **Activer le venv + profil perso** (une fois par session shell) :
   ```bash
   source .venv/bin/activate && git-perso
   ```
1. **Modifier `scripts/webhook_server.py`** ou `config.json`
2. **Test syntaxe Python** : `python -c "import ast; ast.parse(open('scripts/webhook_server.py').read())"` (le `python` du venv = 3.11)
3. **Redémarrer le bot** :
   ```bash
   pkill -f webhook_server.py
   nohup .venv/bin/python -u scripts/webhook_server.py >> state/daemon.log 2>&1 &
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

### 8. Toute modification du code passe par l'agent `binance-dev` (workflow ticket → branche → PR)

**Aucune modification de code ne se fait directement sur `main`.** Sans exception, même pour un hotfix d'une ligne.

Workflow obligatoire :
1. Créer (ou identifier) l'issue GitHub correspondante sur le repo `yousmaaza/agent-binance`
2. L'ajouter au board "Binance Bot Agent" (project #4) et la basculer en "In progress"
3. Invoquer l'agent `binance-dev` pour implémenter sur une branche `feat/issue-<N>-<slug>`
4. `binance-dev` crée la PR et bascule le ticket en "In review" — c'est l'utilisateur qui merge

Les seules exceptions autorisées à une modification directe sur `main` :
- Mise à jour de `CLAUDE.md` lui-même (méta-règles, pas de code)
- Fichiers de configuration non-code (`config.json`) sur instruction explicite de l'utilisateur

❌ Commits directs sur `main`, `git add .`, `git push` sans branche et sans PR : **interdits**.

## Ne pas faire

- ❌ Démarrer un nouveau tunnel Cloudflare ou ngrok : le réseau corporate de l'utilisateur bloque QUIC (UDP 7844), TCP 7844, et les DNS trycloudflare.com. Polling-only.
- ❌ Re-introduire `urllib.request` pour Telegram (cf. règle 1)
- ❌ Ajouter des dépendances lourdes (scipy, pandas) : le bot doit rester un script Python standalone. Math stats sont déjà implémentées à la main dans `run_perf()`.
- ❌ Créer des fichiers `.md` documentaires sauf si l'utilisateur le demande explicitement.
- ❌ Modifier `state/trade_history.json` manuellement sans backup — c'est la source de vérité pour `/perf`.

## Notes contextuelles

- L'utilisateur est francophone. Toutes les notifications Telegram et les `explanation_fr` doivent être en français vulgarisé (sans jargon crypto).
- Le bot est destiné à tourner sur le Mac de l'utilisateur. Un plan de déploiement VPS Hetzner existait précédemment mais n'est pas implémenté — ne pas y revenir sans demande explicite.
- L'environnement Python du projet est un venv `.venv/` (Python 3.11) à la racine. Les dépendances viennent de `requirements.txt` (runtime) et `requirements-dev.txt` (review). Ne plus utiliser le Python global `anaconda3` — il peut diverger en version.
