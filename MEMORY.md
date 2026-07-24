# Mémoire du projet

Journal des décisions, incidents et contexte non triviaux — complète `CLAUDE.md` (qui contient les règles) sans le dupliquer. Contrairement à `CLAUDE.md`, ce fichier n'est pas forcément chargé automatiquement par tous les agents/outils : à consulter en cas de doute sur l'historique d'une décision, ou avant de re-proposer quelque chose qui a peut-être déjà été essayé.

## 2026-07-24 — Bascule production sur VPS (Hostinger)

Le bot tourne désormais en continu sur une VPS Hostinger dédiée (via systemd), plus sur le Mac de l'utilisateur — qui reste l'environnement de développement uniquement. Guide de déploiement reproductible : `deploy/README.md`.

**Contexte** : l'objectif était l'autonomie totale du bot (indépendant d'une machine perso allumée). Une VM Oracle Cloud "Always Free" (Ampere A1, ARM) a été tentée en premier — abandonnée après plusieurs erreurs `Out of capacity` bloquantes et récurrentes sur les shapes gratuits (ARM *et* AMD) dans la seule région disponible pour ce compte. Bascule sur une VPS Hostinger payante (x86_64) pour débloquer — ce qui a aussi supprimé toute question de compatibilité ARM.

**Pièges découverts pendant le déploiement** (à ne pas re-découvrir si on migre encore d'hébergeur un jour) :
- `claude --dangerously-skip-permissions` refuse de s'exécuter en root/sudo — le service tourne sous un utilisateur non-root dédié, créé spécifiquement pour ça.
- `kraken-cli` stocke ses credentials API dans un fichier **séparé** du `.env` du projet (`~/.config/kraken/config.toml` sur Linux, `~/Library/Application Support/kraken/config.toml` sur macOS) — à copier/maintenir indépendamment.
- Sans `git config user.name`/`user.email` configuré pour l'utilisateur système qui exécute le bot, les commits automatiques de Phase 8 (`chore: cycle log ...`) échouent **silencieusement** — pas d'erreur visible dans les notifications Telegram, juste un `git status` qui reste sale indéfiniment.
- Le service systemd doit définir explicitement `Environment="PATH=..."` — les services n'héritent pas du `.bashrc` de l'utilisateur, donc `subprocess.Popen(["claude", ...])` ne trouve pas le binaire sinon.

**Point de vigilance en cours** : le CLI Claude sur la VPS est authentifié via le même abonnement Pro/Max que l'usage interactif de l'utilisateur (le bot ignore intentionnellement `ANTHROPIC_API_KEY`, voir `.env.example` — aucun fallback pay-per-use). Risque de quota partagé non quantifié entre les cycles automatiques (6/jour) et l'usage personnel de l'utilisateur ailleurs. À surveiller dans `logs/stderr/cycle_*.log` (chercher `rate limit`/`usage limit`/`quota`) si des cycles commencent à échouer sans raison apparente.

MongoDB Atlas Network Access a été restreint le même jour : suppression d'une entrée `0.0.0.0/0` restée active depuis la configuration initiale du cluster (flaggée "Security risk" par Atlas lui-même) — seules les IP effectivement utilisées (VPS de prod + IP de dev) sont whitelistées désormais.
