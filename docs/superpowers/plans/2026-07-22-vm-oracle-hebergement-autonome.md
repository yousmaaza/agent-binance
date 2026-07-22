# Hébergement autonome sur VM Oracle Cloud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire tourner `binance-bot/webhook_server.py` (interactif + auto-scheduler) en continu sur une VM Oracle Cloud "Always Free" (ARM), de façon totalement indépendante du Mac, sans changer la logique de trading.

**Architecture:** Une VM Ampere A1 (ARM/Ubuntu) héberge le process unique via systemd. État (`state/`, `logs/`) sur disque local de la VM. Secrets dans un `.env` recréé sur la VM (jamais commité). Les deux serveurs MCP du projet (`tradingview` via `uvx`, `telegram-assistant` via un script Python local) tournent sur la VM exactement comme sur le Mac aujourd'hui.

**Tech Stack:** Python 3.11 (venv), systemd, Claude Code CLI, `uv`/`uvx`, Rust/cargo (`kraken-cli`), Oracle Cloud Ampere A1 (Ubuntu).

## Global Constraints

- Aucun port entrant, aucun tunnel — polling-only (CLAUDE.md)
- Tout Python via venv `.venv/` en 3.11, jamais de python global
- Aucun secret hardcodé — uniquement via `.env`, jamais commité
- `PROJECT_DIR` reste dynamique (`os.path.dirname(...)`), aucun chemin Mac en dur dans le code applicatif
- `kraken-cli` installé via `cargo install` (pas de binaire précompilé x86_64 à copier)
- systemd : `Restart=on-failure` + activé au boot (`systemctl enable`)
- Aucune modification de la logique de trading (phases, scoring, sizing, exécution) — migration d'hébergement uniquement
- Référence : spec `docs/superpowers/specs/2026-07-22-vm-oracle-hebergement-autonome-design.md`

---

## Note sur l'exécution de ce plan

Contrairement à un plan de code pur, plusieurs tâches ci-dessous nécessitent un accès réel à une VM (création via la console Oracle Cloud, accès SSH). Chaque tâche précise si elle est :
- **[Action utilisateur]** — doit être faite par l'utilisateur (compte Oracle, console web), résultat à rapporter avant de continuer.
- **[Via SSH]** — exécutable par l'agent une fois l'IP et l'accès SSH de la VM disponibles.
- **[Repo local]** — modification de fichiers dans le repo `agent-binance`, testable/committable normalement.

---

### Task 1: Provisionner l'instance Oracle Cloud

**Files:** Aucun (infrastructure)

**Interfaces:**
- Produces: adresse IP publique de la VM, clé SSH privée pour s'y connecter — nécessaires à toutes les tâches suivantes.

- [ ] **Step 1 [Action utilisateur] : Créer l'instance**

Dans la console Oracle Cloud (https://cloud.oracle.com) :
- Compute → Create Instance
- Nom : `agent-binance-vm`
- Image : Ubuntu 24.04 (dernière LTS disponible dans le catalogue Oracle)
- Shape : `VM.Standard.A1.Flex` (Ampere, ARM) — allouer 2 OCPU / 12 Go RAM (dans le pool always-free de 4 OCPU/24 Go)
- Réseau : VCN par défaut, IP publique activée
- Clé SSH : générer une nouvelle paire ou uploader une clé publique existante — **conserver la clé privée**, elle sera nécessaire pour toutes les tâches suivantes

- [ ] **Step 2 [Action utilisateur] : Vérifier l'accès SSH**

```bash
ssh -i <chemin_clé_privée> ubuntu@<IP_PUBLIQUE_VM> "echo OK"
```

Expected: `OK` affiché. Si erreur `Connection refused`, vérifier la security list Oracle (port 22 doit être ouvert en entrée — c'est la seule exception au principe "aucun port entrant", strictement nécessaire pour l'administration).

- [ ] **Step 3 : Rapporter l'IP et confirmer l'accès SSH avant de continuer sur la Task 2.**

---

### Task 2: Préparer l'environnement système de base

**Files:** Aucun (infrastructure)

**Interfaces:**
- Consumes: accès SSH de la Task 1
- Produces: Python 3.11, `git`, `uv` installés sur la VM

- [ ] **Step 1 [Via SSH] : Mettre à jour le système et installer les paquets de base**

```bash
ssh -i <clé> ubuntu@<IP> "sudo apt-get update && sudo apt-get install -y software-properties-common git curl build-essential"
```

Expected: exit code 0, pas d'erreur `E:`.

- [ ] **Step 2 [Via SSH] : Installer Python 3.11**

```bash
ssh -i <clé> ubuntu@<IP> "sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv"
```

- [ ] **Step 3 [Via SSH] : Vérifier la version**

```bash
ssh -i <clé> ubuntu@<IP> "python3.11 --version"
```

Expected: `Python 3.11.x`

- [ ] **Step 4 [Via SSH] : Installer `uv`/`uvx` (nécessaire pour le serveur MCP `tradingview`)**

```bash
ssh -i <clé> ubuntu@<IP> "curl -LsSf https://astral.sh/uv/install.sh | sh"
```

- [ ] **Step 5 [Via SSH] : Vérifier**

```bash
ssh -i <clé> ubuntu@<IP> "source ~/.local/bin/env && uvx --version"
```

Expected: un numéro de version `uvx`, pas de `command not found`.

---

### Task 3: Cloner le repo et créer le venv sur la VM

**Files:**
- Repo distant : `yousmaaza/agent-binance`

**Interfaces:**
- Consumes: `git`, Python 3.11 de la Task 2
- Produces: `~/agent-binance/.venv` — chemin réutilisé par la Task 6 (systemd) et la Task 8 (kraken-cli)

- [ ] **Step 1 [Via SSH] : Cloner le repo**

```bash
ssh -i <clé> ubuntu@<IP> "git clone https://github.com/yousmaaza/agent-binance.git ~/agent-binance"
```

Note : utiliser une URL HTTPS avec un Personal Access Token (PAT) si le clone nécessite une authentification (le repo est privé) — ne jamais coller le PAT dans un fichier committé, uniquement en argument de commande ponctuel ou via `git credential`.

- [ ] **Step 2 [Via SSH] : Créer le venv et installer les dépendances**

```bash
ssh -i <clé> ubuntu@<IP> "cd ~/agent-binance && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"
```

- [ ] **Step 3 [Via SSH] : Vérifier**

```bash
ssh -i <clé> ubuntu@<IP> "cd ~/agent-binance && .venv/bin/python --version && .venv/bin/python -c 'import pymongo, loguru; print(\"OK\")'"
```

Expected: `Python 3.11.x` puis `OK`.

- [ ] **Step 4 [Via SSH] : Vérifier que `PROJECT_DIR` se résout correctement dans ce nouvel emplacement**

```bash
ssh -i <clé> ubuntu@<IP> "cd ~/agent-binance && .venv/bin/python -c \"import sys; sys.path.insert(0,'binance-bot'); from core.env import PROJECT_DIR; print(PROJECT_DIR)\""
```

Expected: `/home/ubuntu/agent-binance` (confirme que `PROJECT_DIR` est bien dynamique, pas de chemin Mac résiduel).

---

### Task 4: Installer Claude Code CLI et vérifier le support ARM64

**Files:** Aucun (infrastructure)

**Interfaces:**
- Consumes: VM Ubuntu ARM de la Task 1
- Produces: binaire `claude` fonctionnel — nécessaire à la Task 7 (auth) et à toutes les exécutions de cycle

- [ ] **Step 1 [Via SSH] : Installer le CLI**

```bash
ssh -i <clé> ubuntu@<IP> "curl -fsSL https://claude.ai/install.sh | bash"
```

(Si cette méthode d'installation a changé, utiliser la méthode documentée officiellement au moment de l'exécution — l'important est de confirmer qu'un binaire Linux ARM64 existe.)

- [ ] **Step 2 [Via SSH] : Vérifier**

```bash
ssh -i <clé> ubuntu@<IP> "claude --version"
```

Expected: un numéro de version affiché, sans erreur `Exec format error` (qui indiquerait une incompatibilité d'architecture — dans ce cas, **arrêter le plan ici** et remonter le blocage : il faudrait reconsidérer une VM x86_64 à la place d'ARM, ce qui sort du pool always-free généreux et change le calcul économique).

---

### Task 5: Installer kraken-cli via cargo

**Files:** Aucun (infrastructure)

**Interfaces:**
- Consumes: `build-essential` (Task 2), venv non requis (binaire Rust indépendant)
- Produces: `~/.cargo/bin/kraken` — chemin attendu par `binance-bot/core/trade_helpers.py` (`KRAKEN_CLI` déjà résolu dynamiquement, aucune modification de code nécessaire si le binaire atterrit au même chemin relatif `~/.cargo/bin/kraken`)

- [ ] **Step 1 [Via SSH] : Installer Rust/cargo**

```bash
ssh -i <clé> ubuntu@<IP> "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"
```

- [ ] **Step 2 [Via SSH] : Installer kraken-cli**

```bash
ssh -i <clé> ubuntu@<IP> "source ~/.cargo/env && cargo install kraken-cli"
```

(Remplacer `kraken-cli` par le nom exact du crate/repo source utilisé sur le Mac — vérifier `cargo install --list` ou l'historique d'installation sur le Mac avant cette étape si le nom du package diffère.)

- [ ] **Step 3 [Via SSH] : Vérifier**

```bash
ssh -i <clé> ubuntu@<IP> "~/.cargo/bin/kraken --version"
```

Expected: un numéro de version, sans erreur de compilation liée à l'architecture ARM. **Si la compilation échoue pour une raison liée à l'architecture**, documenter l'erreur précise et arrêter le plan ici (retour à l'utilisateur avant de continuer).

- [ ] **Step 4 [Via SSH] : Test fonctionnel minimal (lecture seule, sans clé API nécessaire pour un ticker public)**

```bash
ssh -i <clé> ubuntu@<IP> "~/.cargo/bin/kraken ticker XBTUSDC -o json"
```

Expected: un JSON avec les données de ticker XBT/USDC, pas de timeout ni d'erreur réseau.

---

### Task 6: Recréer `.env` sur la VM

**Files:**
- Créer sur la VM (hors repo) : `~/agent-binance/.env`
- Référence : `.env.example` du repo pour la liste des clés attendues

**Interfaces:**
- Consumes: aucune
- Produces: variables d'environnement lues par `webhook_server.py` au démarrage (`_load_env()`)

- [ ] **Step 1 [Via SSH] : Vérifier la liste des clés attendues**

```bash
ssh -i <clé> ubuntu@<IP> "cat ~/agent-binance/.env.example"
```

- [ ] **Step 2 [Action utilisateur] : Créer le fichier `.env` sur la VM avec les mêmes valeurs que sur le Mac**

Ne jamais transmettre les secrets en clair dans un canal non chiffré autre que SSH (ex: pas de copier-coller dans un ticket ou un message Telegram). Utiliser `scp` depuis le Mac (chiffré) ou saisie manuelle via `ssh` + éditeur :

```bash
scp -i <clé> /Users/yousrimaazaoui/Documents/projets/perso/agent-binance/.env ubuntu@<IP>:~/agent-binance/.env
```

- [ ] **Step 3 [Via SSH] : Vérifier que le fichier est bien chargé (sans afficher les valeurs)**

```bash
ssh -i <clé> ubuntu@<IP> "cd ~/agent-binance && .venv/bin/python -c \"
import sys; sys.path.insert(0,'binance-bot')
from core.env import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
print('TELEGRAM_TOKEN set:', bool(TELEGRAM_TOKEN))
print('TELEGRAM_CHAT_ID set:', bool(TELEGRAM_CHAT_ID))
\""
```

Expected: `TELEGRAM_TOKEN set: True` et `TELEGRAM_CHAT_ID set: True`.

---

### Task 7: Corriger le chemin `telegram-assistant` dans `.mcp.json` et migrer le script

**Files:**
- Modify: `.mcp.json:6` (chemin du script `telegram-assistant`)
- Copier sur la VM : le contenu de `~/.claude/mcp-servers/telegram-assistant-mcp/` (Mac) vers un emplacement équivalent sur la VM

**Interfaces:**
- Consumes: aucune
- Produces: `.mcp.json` portable (plus de chemin Mac en dur)

- [ ] **Step 1 [Repo local] : Lire le `.mcp.json` actuel**

```bash
cat /Users/yousrimaazaoui/Documents/projets/perso/agent-binance/.mcp.json
```

Confirmer la ligne : `"args": ["/Users/yousrimaazaoui/.claude/mcp-servers/telegram-assistant-mcp/mcp_telegram_tool.py"]`

- [ ] **Step 2 [Repo local] : Remplacer le chemin en dur par une expression portable**

Modifier `.mcp.json` pour utiliser `$HOME` (résolu par le shell qui lance le process MCP) au lieu du chemin Mac explicite :

```json
{
  "mcpServers": {
    "telegram-assistant": {
      "command": "python3",
      "args": ["$HOME/.claude/mcp-servers/telegram-assistant-mcp/mcp_telegram_tool.py"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "${TELEGRAM_BOT_TOKEN}",
        "TELEGRAM_CHAT_ID": "${TELEGRAM_CHAT_ID}"
      }
    },
    "tradingview": {
      "command": "uvx",
      "args": ["--from", "tradingview-mcp-server", "tradingview-mcp"]
    }
  }
}
```

Si `$HOME` n'est pas résolu par le mécanisme de lancement MCP de Claude Code (à vérifier — certains lanceurs MCP n'interpolent pas les variables shell dans `args`), garder un chemin absolu mais le rendre spécifique à chaque machine via un fichier non commité (ex: `.mcp.local.json` en override) plutôt qu'un chemin Mac en dur dans le fichier versionné.

- [ ] **Step 3 [Repo local] : Committer**

```bash
cd /Users/yousrimaazaoui/Documents/projets/perso/agent-binance
git add .mcp.json
git commit -m "fix: rendre le chemin telegram-assistant MCP portable (\$HOME au lieu d'un chemin Mac en dur)"
git push origin main
```

- [ ] **Step 4 [Via SSH] : Copier le script MCP vers la VM**

```bash
scp -i <clé> -r /Users/yousrimaazaoui/.claude/mcp-servers/telegram-assistant-mcp ubuntu@<IP>:~/.claude/mcp-servers/
```

- [ ] **Step 5 [Via SSH] : Pull la modification `.mcp.json` sur la VM**

```bash
ssh -i <clé> ubuntu@<IP> "cd ~/agent-binance && git pull origin main"
```

---

### Task 8: Authentifier le CLI Claude avec l'abonnement Pro

**Files:** Aucun (infrastructure)

**Interfaces:**
- Consumes: CLI installé (Task 4)
- Produces: session Claude Code authentifiée sur la VM

- [ ] **Step 1 [Via SSH, interactif] : Lancer le login**

```bash
ssh -i <clé> ubuntu@<IP> "claude login"
```

Suivre le flux OAuth affiché (généralement une URL à ouvrir dans un navigateur local — copier l'URL affichée dans le terminal SSH et l'ouvrir manuellement sur le Mac ou tout navigateur, puis coller le code renvoyé si demandé).

- [ ] **Step 2 [Via SSH] : Vérifier l'authentification**

```bash
ssh -i <clé> ubuntu@<IP> "claude --print 'dis juste OK'"
```

Expected: `OK` (ou équivalent) renvoyé sans erreur d'authentification.

- [ ] **Step 3 : Noter la date/heure de ce test — sert de point de départ pour la semaine d'observation du quota Pro (Task 11).**

---

### Task 9: Créer le service systemd

**Files:**
- Create: `deploy/webhook-bot.service`

**Interfaces:**
- Consumes: chemin du venv (`~/agent-binance/.venv`, Task 3), `.env` (Task 6)
- Produces: service systemd `webhook-bot` — démarré/vérifié en Task 10

- [ ] **Step 1 [Repo local] : Créer le fichier unit dans le repo**

```ini
# deploy/webhook-bot.service
# Installer avec : sudo cp deploy/webhook-bot.service /etc/systemd/system/
# puis : sudo systemctl daemon-reload && sudo systemctl enable --now webhook-bot
[Unit]
Description=Binance trading bot (Telegram polling + auto-scheduler)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/agent-binance
ExecStart=/home/ubuntu/agent-binance/.venv/bin/python -u binance-bot/webhook_server.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/home/ubuntu/agent-binance/state/daemon.log
StandardError=append:/home/ubuntu/agent-binance/state/daemon.log

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2 [Repo local] : Committer**

```bash
cd /Users/yousrimaazaoui/Documents/projets/perso/agent-binance
mkdir -p deploy
# (créer le fichier ci-dessus dans deploy/webhook-bot.service)
git add deploy/webhook-bot.service
git commit -m "chore: ajouter le service systemd pour le déploiement VM"
git push origin main
```

- [ ] **Step 3 [Via SSH] : Pull et installer sur la VM**

```bash
ssh -i <clé> ubuntu@<IP> "cd ~/agent-binance && git pull origin main && sudo cp deploy/webhook-bot.service /etc/systemd/system/ && sudo systemctl daemon-reload"
```

---

### Task 10: Démarrer le service et valider le fonctionnement

**Files:** Aucun (infrastructure — validation)

**Interfaces:**
- Consumes: service systemd (Task 9), toutes les dépendances des Tasks 2-8

- [ ] **Step 1 [Via SSH] : Activer et démarrer**

```bash
ssh -i <clé> ubuntu@<IP> "sudo systemctl enable --now webhook-bot"
```

- [ ] **Step 2 [Via SSH] : Vérifier le statut**

```bash
ssh -i <clé> ubuntu@<IP> "sudo systemctl status webhook-bot --no-pager"
```

Expected: `Active: active (running)`.

- [ ] **Step 3 [Via SSH] : Vérifier les logs de démarrage**

```bash
ssh -i <clé> ubuntu@<IP> "tail -20 ~/agent-binance/state/daemon.log"
```

Expected : lignes `Bot v2 démarre en mode polling` et `Prochain cycle auto : ...` — identiques à ce qu'on voit sur le Mac aujourd'hui.

- [ ] **Step 4 : Test fonctionnel depuis Telegram**

Envoyer `/status` depuis Telegram. Expected : réponse en moins de 5s, contenu cohérent (portfolio, positions ouvertes).

- [ ] **Step 5 : Test d'un cycle manuel complet**

Envoyer `/trade` depuis Telegram. Suivre `tail -f ~/agent-binance/logs/stdout/cycle_*.log` via SSH. Expected : les 8 phases s'exécutent sans erreur, y compris les appels MCP `tradingview` (Phase 1-2) et le message final de synthèse reçu sur Telegram.

- [ ] **Step 6 : Test de reboot**

```bash
ssh -i <clé> ubuntu@<IP> "sudo reboot"
```

Attendre ~1 min, puis :

```bash
ssh -i <clé> ubuntu@<IP> "sudo systemctl status webhook-bot --no-pager"
```

Expected : `Active: active (running)` — confirme que `systemctl enable` fonctionne et que le bot survit à un redémarrage de la VM.

---

### Task 11: Semaine d'observation (pas de code — checklist de suivi)

**Files:** Aucun

- [ ] **Step 1 : Suivre quotidiennement pendant 7 jours si les cycles automatiques (`trigger=auto`) s'exécutent sans erreur d'authentification/quota**

```bash
ssh -i <clé> ubuntu@<IP> "grep -c 'Terminé exit=0' ~/agent-binance/state/daemon.log"
```

Comparer au nombre de cycles auto attendus sur la période (6/jour × 7 jours = 42, en tenant compte des cycles manuels en plus).

- [ ] **Step 2 : Vérifier qu'aucune erreur `rate limit` / `usage limit` n'apparaît**

```bash
ssh -i <clé> ubuntu@<IP> "grep -i 'rate limit\|usage limit\|quota' ~/agent-binance/logs/stderr/cycle_*.log"
```

Expected : aucun résultat. Si des erreurs apparaissent, remonter à l'utilisateur — décision à prendre : isoler une clé API (`ANTHROPIC_API_KEY`) pour la VM.

- [ ] **Step 3 : Vérifier la stabilité de `kraken-cli` sur ARM (pas d'erreurs de segfault ou de crash inattendu)**

```bash
ssh -i <clé> ubuntu@<IP> "grep -i 'segfault\|core dumped\|Illegal instruction' ~/agent-binance/logs/stderr/cycle_*.log"
```

Expected : aucun résultat.

- [ ] **Step 4 : Rapporter les résultats de la semaine d'observation avant de passer à la Task 12 (bascule finale).**

---

### Task 12: Bascule finale — arrêter le Mac, mettre à jour `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (sections Stack, Workflow, Notes contextuelles)

**Interfaces:**
- Consumes: validation de la Task 11

- [ ] **Step 1 [Action utilisateur] : Arrêter définitivement le process sur le Mac**

```bash
pkill -f webhook_server.py
```

Ne pas relancer — la VM est désormais l'unique instance en production.

- [ ] **Step 2 [Repo local] : Mettre à jour `CLAUDE.md`**

Modifier la section "Stack" pour indiquer que le process live tourne sur la VM Oracle (via systemd), pas sur le Mac (`nohup`). Modifier "Notes contextuelles" pour remplacer la mention "le bot est destiné à tourner sur le Mac... plan VPS Hetzner non implémenté" par la description de l'architecture VM Oracle effectivement déployée. Ajouter dans le "Workflow type d'une modification" une étape de déploiement post-merge :

```markdown
6. **Déployer sur la VM** (après merge d'une PR sur main) :
   ```bash
   ssh -i <clé> ubuntu@<IP_VM> "cd ~/agent-binance && git pull origin main && sudo systemctl restart webhook-bot"
   ```
```

- [ ] **Step 3 [Repo local] : Committer**

```bash
cd /Users/yousrimaazaoui/Documents/projets/perso/agent-binance
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — bot en production sur VM Oracle, Mac = dev uniquement"
git push origin main
```

---

## Self-Review

- **Spec coverage** : architecture (Task 3, 9, 10), provisioning checklist de la spec (Tasks 1-8), point d'incertitude quota Pro (Task 8 note + Task 11), fiabilité/supervision (Task 9 systemd, Task 10 test reboot), tests et bascule (Task 10, 11, 12), rollback implicite (aucune tâche ne supprime la capacité de relancer sur le Mac tant que la Task 12 n'est pas exécutée — le rollback consiste simplement à ne pas faire cette dernière tâche / relancer `nohup` sur le Mac si besoin).
- **Placeholders** : `<clé>` et `<IP>` sont des espaces réservés volontaires (valeurs réelles connues uniquement après la Task 1) — pas des `TODO` de contenu manquant, chaque commande est complète et exécutable une fois ces deux valeurs connues.
- **Cohérence** : chemin `~/agent-binance` utilisé de façon cohérente à partir de la Task 3 ; `~/.cargo/bin/kraken` cohérent entre Task 5 et la résolution dynamique existante côté code.
