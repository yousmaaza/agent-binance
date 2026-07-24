# Setup du bot sur une VPS

Guide pour déployer `webhook_server.py` (interactif Telegram + auto-scheduler 4h) sur une VPS Linux x86_64, de façon autonome (aucune dépendance au Mac). Déploiement actuel : VPS Hostinger (Ubuntu 24.04). Ce guide reste valable pour toute VPS Linux équivalente.

## Prérequis

- VPS Linux x86_64, avec un accès root initial (pour créer l'utilisateur applicatif)
- Ubuntu 22.04+ ou 24.04 recommandé (`apt`)
- Accès en écriture au repo GitHub `yousmaaza/agent-binance` (pour créer une deploy key)
- Le `.env` du projet et le fichier de credentials Kraken (`config.toml`) déjà en place sur le Mac (ou toute machine de référence), à copier vers la VPS

## ⚠️ Piège n°1 : ne jamais installer en root

`claude --dangerously-skip-permissions` **refuse de s'exécuter en root/sudo** ("cannot be used with root/sudo privileges for security reasons") — or c'est exactement comme ça que `webhook_server.py` invoque le CLI Claude à chaque cycle. Tout ce qui suit (venv, CLI Claude, kraken-cli, service systemd) doit tourner sous un **utilisateur dédié non-root**. Root ne sert qu'à l'installation initiale des paquets système et à la gestion du service systemd.

## Étape 1 — Paquets système (en root)

```bash
apt-get update
apt-get install -y software-properties-common git curl build-essential
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update
apt-get install -y python3.11 python3.11-venv
```

Vérifier : `python3.11 --version` → `Python 3.11.x`.

## Étape 2 — Créer l'utilisateur applicatif (en root)

```bash
useradd -m -s /bin/bash botuser
mkdir -p /home/botuser/.ssh
cp ~/.ssh/authorized_keys /home/botuser/.ssh/authorized_keys   # réutilise ta clé SSH existante
chown -R botuser:botuser /home/botuser/.ssh
chmod 700 /home/botuser/.ssh
chmod 600 /home/botuser/.ssh/authorized_keys
```

Vérifier l'accès : `ssh -i <clé> botuser@<IP> whoami` → `botuser`.

Tout ce qui suit se fait **en tant que `botuser`**, via SSH (`ssh -i <clé> botuser@<IP> "<commande>"`).

## Étape 3 — Deploy key GitHub

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy_key -N '' -C 'agent-binance-vps-deploy'
cat ~/.ssh/github_deploy_key.pub
```

Ajouter la clé publique affichée sur `https://github.com/yousmaaza/agent-binance/settings/keys` → **Add deploy key** → **cocher "Allow write access"** (le bot doit pouvoir pousser `trade_history.json`/`cycle_log.jsonl` à chaque cycle).

```bash
cat > ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_deploy_key
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -o StrictHostKeyChecking=accept-new -T git@github.com   # accepte le host key, confirme l'auth
```

## Étape 4 — Cloner le repo et configurer git

```bash
git clone git@github.com:yousmaaza/agent-binance.git ~/agent-binance
cd ~/agent-binance
```

### ⚠️ Piège n°2 : identité git obligatoire

Sans `user.name`/`user.email` configurés, les commits automatiques de Phase 8 (`chore: cycle log ...`) échouent **silencieusement** (le bot continue de tourner, mais l'état ne se synchronise plus jamais sur GitHub). Configurer avant tout premier cycle :

```bash
git config user.name 'Yousri Maazaoui'
git config user.email 'dataforscience@gmail.com'
```

## Étape 5 — Environnement Python

```bash
cd ~/agent-binance
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Vérifier : `.venv/bin/python -c "import sys; sys.path.insert(0,'binance-bot'); from core.env import PROJECT_DIR; print(PROJECT_DIR)"` doit afficher le chemin réel (`/home/botuser/agent-binance`), confirmant que `PROJECT_DIR` est bien dynamique.

## Étape 6 — Claude Code CLI

```bash
curl -fsSL https://claude.ai/install.sh | bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

Authentification (abonnement Pro — **pas** de clé API, le bot ignore volontairement `ANTHROPIC_API_KEY`, voir `.env.example`). Nécessite un terminal interactif réel :

```bash
export PATH=$HOME/.local/bin:$PATH
claude auth login
```

Vérifier : `claude auth status` → `"loggedIn": true, "subscriptionType": "pro"`.

## Étape 7 — `uv`/`uvx` (serveur MCP tradingview)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Étape 8 — kraken-cli

`kraken-cli` n'est pas sur crates.io — c'est un binaire précompilé distribué via les releases GitHub `krakenfx/kraken-cli` (cargo-dist) :

```bash
curl -sL -o /tmp/kraken-installer.sh https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-installer.sh
sh /tmp/kraken-installer.sh
```

### ⚠️ Piège n°3 : l'authentification Kraken est un store séparé du `.env`

`kraken-cli` gère ses credentials API dans **son propre fichier de config**, indépendant du `.env` du projet :
- macOS : `~/Library/Application Support/kraken/config.toml`
- Linux : `~/.config/kraken/config.toml`

Copier ce fichier depuis la machine de référence (jamais en clair dans une commande/chat) :

```bash
scp -i <clé> "/Users/<user>/Library/Application Support/kraken/config.toml" botuser@<IP>:~/.config/kraken/config.toml
ssh -i <clé> botuser@<IP> "chmod 600 ~/.config/kraken/config.toml && ~/.cargo/bin/kraken auth test"
```

Expected : `Status: Authentication successful`.

## Étape 9 — `.env` du projet

```bash
scp -i <clé> /chemin/vers/.env botuser@<IP>:~/agent-binance/.env
ssh -i <clé> botuser@<IP> "chmod 600 ~/agent-binance/.env"
```

Vérifier (sans afficher les valeurs) :

```bash
cd ~/agent-binance && .venv/bin/python -c "
import sys; sys.path.insert(0,'binance-bot')
from core.env import TOKEN, CHAT_ID, MONGO_URI
print('TOKEN set:', bool(TOKEN))
print('CHAT_ID set:', bool(CHAT_ID))
print('MONGO_URI set:', bool(MONGO_URI))
"
```

Note : les variables exportées par `core/env.py` sont nommées `TOKEN`/`CHAT_ID` (pas `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID`, malgré les noms des clés dans `.env`).

## Étape 10 — Serveur MCP `telegram-assistant`

Le second serveur MCP du projet (`.mcp.json`) est un script Python local, à copier à l'identique :

```bash
ssh -i <clé> botuser@<IP> "mkdir -p ~/.claude/mcp-servers/telegram-assistant-mcp"
scp -i <clé> ~/.claude/mcp-servers/telegram-assistant-mcp/mcp_telegram_tool.py botuser@<IP>:~/.claude/mcp-servers/telegram-assistant-mcp/
```

`.mcp.json` référence ce script via `$HOME/.claude/mcp-servers/telegram-assistant-mcp/mcp_telegram_tool.py` — portable d'une machine à l'autre tant que le script est placé au même chemin relatif.

## Étape 11 — Service systemd (en root)

Le fichier `deploy/webhook-bot.service` de ce repo est prêt à l'emploi. Adapter `User=`, `WorkingDirectory=` et les chemins `Environment=`/`ExecStart=`/`StandardOutput=`/`StandardError=` si l'utilisateur ou le chemin du clone diffèrent de `botuser`/`/home/botuser/agent-binance`.

```bash
cp ~botuser/agent-binance/deploy/webhook-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now webhook-bot
systemctl status webhook-bot --no-pager   # attendu : Active: active (running)
```

Le service inclut déjà `Restart=on-failure` et `Environment="PATH=..."` couvrant `~/.local/bin` (Claude CLI) et `~/.cargo/bin` (kraken-cli) — nécessaire car les services systemd n'héritent pas du `.bashrc` de l'utilisateur.

## Étape 12 — Validation

1. `tail -20 ~botuser/agent-binance/state/daemon.log` → doit montrer `Bot v2 démarre en mode polling` et `Prochain cycle auto : ...`
2. Envoyer `/status` depuis Telegram → réponse en moins de 5s
3. Envoyer `/trade` depuis Telegram → cycle complet (Phases 0-8) sans erreur, y compris les appels MCP `tradingview` et le commit/push git final
4. Redémarrer la VM (`reboot`) et vérifier que le service repart seul (`systemctl status webhook-bot`)

## ⚠️ Point de vigilance permanent : quota Claude Pro partagé

Le CLI `claude` est authentifié via l'abonnement Pro de l'utilisateur (pas de clé API — volontairement, le bot l'ignore). Si le bot tourne en continu sur une VPS **et** que l'utilisateur utilise Claude Code en parallèle sur une autre machine, les deux usages partagent le même quota. Surveiller les logs (`logs/stderr/cycle_*.log`) pour des erreurs `rate limit`/`usage limit`/`quota` — si ça arrive, il faudrait isoler une clé API dédiée à la VPS (changement de code non trivial, le bot l'ignore actuellement par design).

## Déployer une mise à jour (après merge d'une PR sur `main`)

```bash
ssh -i <clé> botuser@<IP> "cd ~/agent-binance && git pull origin main"
ssh -i <clé> root@<IP> "systemctl restart webhook-bot"
```

## Débogage rapide

| Symptôme | Vérification |
|---|---|
| Service inactif | `systemctl status webhook-bot --no-pager` (root) |
| Erreur au démarrage | `tail -50 ~botuser/agent-binance/state/daemon.log` |
| Cycle qui plante | `cat ~botuser/agent-binance/logs/stderr/cycle_<ID>.log` |
| `git commit` silencieusement sans effet | vérifier `git config user.name`/`user.email` sous `botuser` |
| `/status` ou `/trade` erreur liée à `balance`/`auth` | `~/.cargo/bin/kraken auth test` — probablement le `config.toml` Kraken manquant ou mal copié |
| Process qui refuse de démarrer avec une erreur `root/sudo` | le service tourne sous le mauvais utilisateur — vérifier `User=` dans `webhook-bot.service`, ne doit jamais être `root` |
