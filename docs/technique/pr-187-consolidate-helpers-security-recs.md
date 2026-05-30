# PR #187 — [CONSOLIDÉ] Helpers partagés par cycle + sécurité + recommandations tech lead

> **Mergée le** : 2026-05-30
> **Branche** : `feat/consolidate-helpers-sec-recs`
> **Issues** : #175, #178, #179, #180, #181, #182, #183, #184, #185, #186

## Contexte

Consolidation de deux initiatives :
1. **PR #176-177 (helpers partagés)** : extraire les fonctions `tg()`, `binance()`, `hb()`, `_save_trade_history_atomic()` dans un fichier temporaire injecté dans chaque phase du prompt, plutôt que de les redéfinir en dur.
2. **Recommandations tech lead #178-#186** : corriger des problèmes de sécurité (hardcodage `/tmp`), refactoriser pour la robustesse, et ajouter des contrôles de lint.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/botlogging/cycle_logger.py` | Modification | Ajout méthode `warning()` (3 lignes) pour supporter les logs d'avertissement structurés par cycle |
| `binance-bot/orchestration/runner.py` | Modification majeure | Refactorisation complète : extraction helpers en fichier temp via `tempfile.mkstemp()`, séparation `_send_start_notification()`, timeout nommé, gestion d'erreurs robuste |
| `prompts/trade_prompt.txt` | Simplification | Suppression des ~60 lignes de code hardcodé au début (redéfinitions `tg()`, `binance()`, etc.) ; import via `exec()` depuis `__HELPERS_PATH__` |
| `scripts/check_cycle_logger_methods.sh` | Ajout (25 lignes) | Lint script : vérifie que tous les appels `cycle_log.xxx()` utilisent des méthodes définies dans `CycleLogger` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_write_helpers_file()` | **Ajoutée** | Génère le contenu des helpers (tg, binance, hb, etc.) et l'écrit dans un fichier temporaire via `tempfile.mkstemp()`. Permissions 0o600 garanties. Secrets lus depuis `os.environ` au runtime (aucun hardcodage). |
| `_send_start_notification()` | **Ajoutée** | Extrait la logique de notification au démarrage d'un cycle. Affiche le modèle Claude utilisé et l'heure du prochain cycle auto. Réutilisée par les cycles manuels et auto. |
| `run_trade_workflow()` | **Modifiée** | Crée le fichier helpers via `tempfile.mkstemp()`, injecte son chemin dans le prompt via `__HELPERS_PATH__`, et le supprime en `finally`. Gestion explicite de `OSError` si le disque est plein. |
| `CycleLogger.warning()` | **Ajoutée** | Nouvelle méthode pour logger les avertissements au niveau cycle. Corrige 2 appels `cycle_log.warning()` préexistants. |

## Décisions techniques notables

- **`tempfile.mkstemp()` pour la sécurité** : remplace le hardcodage `/tmp/cycle_XXXX_helpers.py` par une création sécurisée via `tempfile.mkstemp()`. Résout Bandit B108 (hardcoded temp path). Le chemin est transmis au prompt via `__HELPERS_PATH__` et suppressible proprement en `finally`.

- **Pas de secrets baked dans le fichier helpers** : `MONGO_URI`, `MONGO_DB`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` sont lus depuis `os.environ` au runtime dans le fichier helpers, jamais substitués par Python avant l'exécution. Sécurité renforcée.

- **Constante `CLAUDE_PROCESS_TIMEOUT_S`** : remplace le magic number 3600 par une constante nommée, facilitant la maintenance et la compréhension de la limite d'exécution du cycle (1h).

- **Extraction `_send_start_notification()`** : réduction de la complexité de `run_trade_workflow()`, amélioration de la testabilité. La logique de notification devient réutilisable et facile à modifier.

- **Cleanup systématique du fichier helpers** : la clause `finally` du workflow garantit la suppression du fichier temporaire, même en cas d'erreur. Pas de fuite de fichier sur le disque.

## Impact sur l'architecture

L'architecture reste **inchangée** : aucun changement de flux ou d'interfaces.

**Impacts de maintenance** :
- Le `trade_prompt.txt` est simplifié (~60 lignes supprimées), plus maintenable.
- Les appels `cycle_log.xxx()` sont maintenant vérifiés par un script lint (`check_cycle_logger_methods.sh`) — prévient les regressions.
- Le fichier helpers n'est plus dupliqué en dur : une seule source de vérité pour `tg()`, `binance()`, `hb()`, etc.

**Impact de sécurité** :
- Chemin tempfile utilisé au lieu de hardcodé `/tmp/` → Bandit B108 résolu.
- Secrets lus depuis `os.environ` au runtime → jamais baked dans les fichiers générés.
- Permissions 0o600 garanties par `mkstemp()` → lecture-écriture propriétaire uniquement.

## Références CLAUDE.md respectées

- **Règle 1 — Telegram via curl** : le helper `tg()` continue d'utiliser `subprocess.run(["curl", ...])`, jamais urllib. ✓
- **Règle 2 — Secrets via .env** : `MONGO_URI`, `MONGO_DB`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` sont lus depuis `os.environ` au runtime, jamais hardcodés. ✓
- **Règle 3 — PROJECT_DIR dynamique** : `tempfile.mkstemp()` fonctionne sur Mac et VPS, pas de chemin Mac hardcodé. ✓
- **Règle 4 — Stdout/stderr sauvegardés** : inchangé, les logs du sous-processus Claude sont toujours capturés dans `logs/stdout/` et `logs/stderr/`. ✓
- **Règle 5 — UTC interne/local affichage** : inchangé, les heartbeats utilisent toujours UTC en interne. ✓

## Notes de déploiement

1. Vérifier la syntaxe Python :
   ```bash
   python -c "import ast; ast.parse(open('binance-bot/orchestration/runner.py').read())"
   ```

2. Exécuter le lint script :
   ```bash
   bash scripts/check_cycle_logger_methods.sh
   ```

3. **Pas de migration d'état** : aucun changement dans `state/`, `config.json`, ou `CLAUDE.md`. Les cycles existants continuent de fonctionner.

4. Redémarrer le bot après deployment :
   ```bash
   pkill -f webhook_server.py
   nohup .venv/bin/python -u scripts/webhook_server.py >> state/daemon.log 2>&1 &
   ```

5. Vérifier le startup : `tail -10 state/daemon.log` doit montrer "🚀 Bot v2 démarré" et "Prochain cycle auto".

6. Test fonctionnel : envoyer `/trade` depuis Telegram → le cycle doit se lancer, créer un fichier helpers temp via `mkstemp()`, et le supprimer proprement après.
