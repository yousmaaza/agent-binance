# PR #98 — Fallback API : reprendre la session Claude via --resume

> **Mergée le** : 2026-05-23
> **Branche** : `feat/issue-97-fallback-resume-session`
> **Issues** : #97

## Contexte

Quand un cycle de trading épuise le quota de l'abonnement Claude, le bot bascule sur l'API en fallback (via `ANTHROPIC_API_KEY`). Auparavant, chaque fallback relançait le cycle **du début** avec le même prompt, doublant le coût API (~10$) et le temps (~5 min) et risquant des décisions divergentes.

La solution : capturer le `session_id` Claude dès que la session démarre, puis relancer le cycle en fallback avec `--resume <session_id>`. La conversation reprend où elle s'était arrêtée, réduisant le coût et le temps d'un facteur 5-10x.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/orchestration/runner.py` | Modification | Orchestration du fallback avec session resumption |
| `binance-bot/orchestration/stream_parser.py` | Modification | Extraction du session_id depuis l'événement `system/init` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_run_claude()` | Modifiée | Nouveau paramètre `session_capture: dict \| None` pour capturer le session_id ; callback interne `_on_session` remplit le dict dès l'événement init |
| `run_trade_workflow()` | Modifiée | Crée un dict `captured` pour la session, passe au premier `_run_claude()`, utilise le session_id en fallback pour les flags `--resume` |
| `parse_stream_event()` | Modifiée | Nouveau paramètre `session_cb: callable` appelé avec le `session_id` dès l'événement `system/init` |

## Décisions techniques notables

- **Callback dans `parse_stream_event()`** plutôt que parsing ultérieur du fichier log : l'événement `system/init` arrive dès le démarrage de la session (avant toute analyse), donc la capture est immédiate et fiable — utile pour le fallback qui doit relancer promptement.
- **Dict mutable `captured`** plutôt que variable module-level : évite les effets de bord entre cycles concurrents (bien que le lock empêche actuellement les cycles parallèles) et rend la session-capture explicitement liée au cycle.
- **Flags `--resume` en fallback uniquement** : le premier cycle normal ne passe pas de flag resume (sinon Claude renouerait avec une session expirée/inexistante). Sur fallback, seul si le session_id a été capturé — sinon, relance complet.
- **Notification Telegram avec différenciation** : message précise `reprise session XXXX` si resume appliqué, ou `redémarrage complet (session non capturée)` sinon → clarté pour l'utilisateur.

## Impact sur l'architecture

Élargissement du flux fallback API (existant) avec session resumption :

```
Fallback API (avant) :
├─ Détecte erreur ressource
├─ Relance complète : prompt → Claude via API
└─ Coût + temps ×5

Fallback API (après) :
├─ Détecte erreur ressource
├─ Si session_id capturé : relance via --resume (même session, contexte préservé)
│  └─ Coût + temps ÷5-10x (reprend après l'interruption)
└─ Sinon : relance complet (fallback sur fallback)
```

Pas d'impact sur les autres composants :
- Mongo, Telegram, watchdog, cost-tracking : unchanged
- Logging du session_id enrichit les logs (utile pour debug)
- L'absence d'API_KEY (env local) implique pas de fallback → pas de comportement changé en mode abonnement pur

## Références CLAUDE.md respectées

- **Règle 4 (Stdout/stderr toujours sauvegardés)** : les logs des deux runs (abonnement + fallback) sont concaténés dans les mêmes fichiers `cycle_*.log`, permettant le debug complet du fallback.
- **Pas de secrets hardcodés** : le session_id est un identifiant de session (non-secret), capturé depuis le stream JSON de Claude CLI — pas d'exposition de credentials.
- **Subprocess Claude intouché** : aucune modification à la manière dont le subprocess est lancé ou terminé — juste paramétrage différent des flags.

## Notes pour le mainteneur

- Le flag `--resume` existe dans Claude CLI (`claude --help` le documente), mais son comportement cross-auth (session créée en abonnement → resumée en API) n'a pas été exhaustivement testé ici.
  - Si ça échoue, le subprocess retournera exit code non-zéro → cycle marqué error dans Mongo, l'utilisateur voit le message d'erreur complet dans les logs.
  - Pas de corruption d'état possible : l'architecture préserve les deux tentatives (abonnement + fallback) dans les mêmes fichiers de log.
- Le session_id est aussi loggé dans `logs/stdout/cycle_*.log` via le formatage existant (ligne `[HH:MM:SS] 🚀 init | ... | session=XXXXXXXX`) → utile pour retrouver une session si fallback non capturée.
