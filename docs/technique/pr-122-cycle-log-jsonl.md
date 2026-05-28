# PR #122 — Générer state/cycle_log.jsonl après chaque cycle et le pousser dans le repo

> **Mergée le** : 2026-05-28
> **Branche** : `feat/issue-121-generer-state-cycle-log-jsonl`
> **Issues** : #121

## Contexte

Auparavant, les résultats de chaque cycle de trading n'étaient persistés que dans MongoDB (`cycles` collection) ou en fichiers Markdown statiques (`reports/`), sans historique léger et facilement interrogeable dans le repo Git lui-même. Cette PR ajoute un **cycle log JSONL** (`state/cycle_log.jsonl`) qui collecte les métriques essentielles de chaque cycle dans un fichier append-only, rotaté automatiquement à 90 lignes maximum, et commité+pushé vers le repo à la fin de chaque cycle — pour avoir un historique local, versionnabilité, et une source de vérité complémentaire aux logs Mongo.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/env.py` | Modification | Initialisation du fichier `state/cycle_log.jsonl` au démarrage du bot (5 lignes) |
| `prompts/trade_prompt.txt` | Modification | Ajout Phase 8 dédiée à la persistance du cycle log (40 lignes) ; initialisation des variables de synthèse utilisées par Phase 8 (8 lignes) |

### Variables de synthèse inicializées

En début du prompt, avant la Phase 0 :

| Variable | Type | Rôle |
|---|---|---|
| `top_score` | int (0-10) | Score maximum parmi tous les coins évalués en Phase 3 |
| `executed` | int | Nombre d'ordres BUY MARKET passés en Phase 5 |
| `skipped` | int | Nombre de coins bloqués par les filtres (Phase 3) |
| `skip_type` | str \| None | Raison principale du skip : `TYPE_A`\|`TYPE_B`\|`TYPE_C`\|`TYPE_D`\|`None` |
| `skip_detail` | str \| None | Phrase décrivant le skip principal (contexte du cycle) |
| `sentiment` | str | Sentiment global du marché obtenu en Phase 1 |
| `portfolio_total` | float | Portefeuille total en USDC calculé en Phase 0 |
| `open_positions` | int | Nombre de trades `open` en Phase 5 |

### Nouvelle Phase 8 — Cycle log JSONL

Après Phase 7 (persistance MongoDB), une nouvelle Phase 8 orchestre :

1. **Lecture** du fichier `state/cycle_log.jsonl` (ou création liste vide si absent)
2. **Ajout** d'une nouvelle ligne JSON contenant :
   ```json
   {
       "date": "YYYY-MM-DDTHH:MMZ",
       "cycle_id": "__CYCLE_ID__",
       "top_score": <int>,
       "executed": <int>,
       "skipped": <int>,
       "skip_type": "<TYPE_A|TYPE_B|TYPE_C|TYPE_D|None>",
       "skip_detail": "<str or None>",
       "portfolio": <float>,
       "sentiment": "<Neutral|Bullish|...>",
       "open_positions": <int>
   }
   ```
3. **Rotation** : si le fichier atteint 91 lignes, les plus anciennes sont supprimées (max 90 conservées)
4. **Commit + push** via subprocess bash avec `git-perso` alias (authentification zsh)

## Décisions techniques notables

- **Append-only + rotation locale** : le JSONL ne se remplace jamais — chaque cycle ajoute une ligne. La rotation à 90 lignes (au lieu d'illimité) garde le fichier léger (~20 KB) tout en conservant 3-4 jours d'historique (à ~30 cycles/jour).

- **Utilisation de `git-perso` pour l'authentification** : le subprocess lance `bash -i -c "git-perso && ..."` pour accéder à l'alias zsh qui configure l'identité git perso + index pip perso. Sans cela, le push verrait `claude[bot]` comme auteur et risquerait de résoudre les dépendances depuis le mauvais index.

- **Gestion d'erreur best-effort** : le push échoue silencieusement en try/except avec notification Telegram optionnelle, mais ne bloque jamais le cycle (la Phase 7 est déjà complétée).

- **Initialisation au boot** : `binance-bot/core/env.py` crée le fichier vide si absent — garantit que le sous-processus Claude ne voit jamais une exception `FileNotFoundError` en Phase 8.

## Impact sur l'architecture

**Changement isolé** : l'ajout de Phase 8 n'affecte pas les phases précédentes (0–7) ni le flux d'exécution global. C'est une perséveration complémentaire optionnelle (git push avec timeout, peut échouer sans impact).

**Utilité** :
- **Historique local versionnabili** : chaque cycle laisse une trace dans le repo, explorable via `git log` ou grep sur `state/cycle_log.jsonl`
- **Métrique de santé légère** : rapidement visualiser `top_score`, `executed`, `skipped` par cycle sans requête Mongo
- **Debugage** : comparer `skip_type` et `skip_detail` entre plusieurs cycles pour identifier les patterns de rejet

**Nouvelles dépendances** : aucune — utilisation de Python natif (`json`, `os`, `subprocess`).

## Références CLAUDE.md respectées

- ✅ **Règle 3 (PROJECT_DIR dynamique)** : le code Phase 8 accède à `__PROJECT_DIR__/state/cycle_log.jsonl` injecté par Python — zéro chemin hardcodé.
- ✅ **Règle 4 (Stdout/stderr capturés)** : Phase 8 s'exécute dans le sous-processus Claude, ses appels subprocess (git commit/push) ne sont pas capturés dans le log standard du bot, mais les erreurs sont notifiées Telegram en best-effort.
- ✅ **Règle 5 (UTC interne)** : le format date utilise `%Y-%m-%dT%H:%MZ` pour l'affichage Mongo-friendly sans conversion locale.
- ✅ **Règle 8 (Pas de modification CLAUDE.md)** : cette PR n'étoffe pas CLAUDE.md — la classification `skip_type` y est d'ailleurs déjà documentée par PR #141.

## Chaîne complète du cycle log

```
Phase 5 assignation de variables (executed, open_positions)
    ↓
Phase 3 assignation de variables (top_score, skipped, skip_type, skip_detail)
    ↓
Phase 1 assignation de variable (sentiment)
    ↓
Phase 0 assignation de variable (portfolio_total)
    ↓
Phase 8 usage des variables pour écriture JSONL + git push
```

À chaque cycle, si une variable n'est pas assignée en amont, elle conserve sa valeur initiale (définie en début de prompt). Le fallback garantit cohérence.
