# PR #48 — [M1] Suivre le cout API par cycle et exposer via /cout

> **Mergée le** : 2026-05-22
> **Branche** : `feat/issue-47-suivre-le-cout-api-par-cycle-et-exposer`
> **Issues** : #47

## Contexte

Chaque cycle de trading déclenche un sous-processus `claude --print` qui consomme des tokens Anthropic. Sans suivi, il était impossible de quantifier le coût API réel du bot dans le temps. Cette PR ajoute l'extraction automatique du coût par cycle depuis le log stdout, sa persistance dans MongoDB, et une commande `/cout` pour consulter les métriques cumulées.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification | Ajout de l'import `re`, extraction post-cycle du coût API, mise à jour Mongo, nouvelle fonction `handle_cout()`, routage de la commande `/cout` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `run_trade_workflow()` | Modifiée | Après la fin du sous-processus, parse `logs/stdout/cycle_<id>.log` via regex pour extraire `cost=$X.XX` depuis la ligne `🏁 done`, puis fait un `update_one` Mongo pour ajouter `api_cost_usd` au document du cycle (qu'il soit en succès ou en erreur) |
| `handle_cout()` | Ajoutée | Handler `/cout` : pipeline d'agrégation MongoDB pour total, moyenne, dernier cycle et top 5 des cycles les plus chers ; envoi via `send_telegram()` |
| `main_loop()` | Modifiée | Routage de `/cout` → `handle_cout()` dans un thread daemon ; mise à jour du message de bienvenue et du message d'aide par défaut pour inclure `/cout` |

## Décisions techniques notables

- **Extraction par regex sur le log stdout** (`re.search(r'cost=\$([0-9]+\.[0-9]+)', _line)`) plutôt que de capturer la valeur lors de la création du document Mongo : la ligne `🏁 done | cost=$X.XX` est émise par la CLI Claude elle-même dans le stream-json — elle n'est pas accessible avant la fin du subprocess.
- **`update_one` post-subprocess** plutôt que d'inclure le coût dans le document initial : pour les cycles en succès, la Phase 7 (subprocess) crée le document Mongo en premier ; le `update_one` parent ajoute ensuite `api_cost_usd` sans conflit (l'upsert de Phase 7 est terminé avant que le parent reprenne le contrôle).
- **Bloc d'extraction placé avant le test `exit_code != 0`** : garantit que le coût est disponible et persisté que le cycle ait réussi ou échoué, sans dupliquer le code dans les deux branches.
- **Pipeline d'agrégation MongoDB minimal** (pas de pandas/scipy) : cohérent avec la contrainte de dépendances légères — les opérations `$sum`, `$avg`, `find().sort().limit()` sont natives MongoDB.
- **Silencieux en cas d'absence de MongoDB** : si `MONGODB_URI` est absent ou invalide, `get_mongo()` retourne `None` et `/cout` répond avec le warning standard — aucune régression pour les déploiements sans Mongo.

## Impact sur l'architecture

La PR enrichit le document Mongo `cycles` d'un nouveau champ `api_cost_usd` (float, optionnel — présent uniquement si la regex a matché dans le log stdout). Le flux `run_trade_workflow()` acquiert une étape supplémentaire entre la fin du subprocess et la gestion de l'exit code. La commande `/cout` s'ajoute à la liste des handlers Telegram et suit exactement le même pattern que `/raisonnement` (thread daemon, accès Mongo, `send_telegram`).

## Références CLAUDE.md respectées

- **Règle 1 (Telegram via curl)** : `handle_cout()` utilise `send_telegram()` qui appelle `tg_post()` (curl) — aucun appel `urllib`.
- **Règle 2 (pas de secrets hardcodés)** : aucune nouvelle clé d'environnement nécessaire — réutilise `MONGODB_URI`/`MONGODB_DB` existants.
- **Règle 4 (stdout/stderr toujours capturés)** : l'extraction du coût lit le log stdout après sa capture complète, sans modifier le mécanisme de capture existant.
- **Règle 5 (UTC interne)** : `api_cost_usd` est un flottant — pas de timestamp manipulé dans cette PR.
- **Pas de dépendances lourdes** : `import re` est stdlib ; le pipeline Mongo évite toute dépendance externe supplémentaire.
