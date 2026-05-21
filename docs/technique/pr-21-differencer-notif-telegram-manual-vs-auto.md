# PR #21 — [M2] Différencier notif Telegram manual vs auto au démarrage de cycle

> **Mergée le** : 2026-05-21
> **Branche** : `feat/issue-6-differencer-notif-telegram-manual-vs`
> **Issues** : #6

## Contexte

Avant cette PR, `run_trade_workflow()` envoyait une notification de démarrage identique quelle que soit l'origine du cycle :

```
🔄 Cycle YYYYMMDD_HHMMSS — analyse en cours...
⏰ Prochain cycle auto : …
```

Ce message HTML générique ne permettait pas de distinguer, côté Telegram, si le cycle avait été déclenché manuellement par l'utilisateur via `/trade` ou automatiquement par le scheduler 4h. Le ticket #6 demandait deux notifications distinctes et lisibles pour ces deux cas.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `scripts/webhook_server.py` | Modification (12 ajouts, 5 suppressions) | La notification de démarrage de cycle est désormais conditionnée au `trigger` |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| `run_trade_workflow()` | Modifiée (lignes 661–672) | Remplace la notification unique par un branchement `if trigger == "auto" / else` avec deux messages et `parse_mode=None` |

### Détail des changements

**Avant** :
```python
send_telegram(
    f"🔄 <b>Cycle {cycle_id}</b> — analyse en cours...\n"
    f"⏰ Prochain cycle auto : {fmt_next()}",
    parse_mode="HTML"
)
```

**Après** :
```python
if trigger == "auto":
    send_telegram(
        f"🤖 Cycle auto 4h démarré ({fmt_local(started_at)})\n"
        f"⏰ Prochain cycle auto : {fmt_next()}",
        parse_mode=None
    )
else:
    send_telegram(
        f"🔧 Cycle manuel {cycle_id} démarré\n"
        f"⏰ Prochain cycle auto : {fmt_next()}",
        parse_mode=None
    )
```

## Décisions techniques notables

- **`parse_mode=None` au lieu de `parse_mode="HTML"`** : les nouveaux messages sont du texte brut — aucun tag HTML nécessaire. Passer `None` évite que Telegram parse accidentellement des caractères spéciaux comme balises HTML (ex : `<`, `>` dans le `cycle_id` ou les horaires).
- **`started_at` comme proxy du slot déclencheur** : pour le cycle auto, l'heure affichée via `fmt_local(started_at)` est le moment réel du démarrage, pas l'heure exacte du slot UTC. Ce choix est sémantiquement correct — le cycle démarre dans les secondes qui suivent le slot, et l'utilisateur n'a pas besoin de distinguer "l'heure du slot" de "l'heure réelle de démarrage".
- **Pas de modification de signature** : `run_trade_workflow(trigger="manual")` reste inchangée. Les deux appelants dans `main_loop` (`trigger="manual"` via `/trade`, `trigger="auto"` via l'auto-scheduler) fonctionnent sans modification.

## Impact sur l'architecture

Changement isolé dans `run_trade_workflow()`. Aucun nouvel état, aucune dépendance ajoutée, aucun changement de flux. La séquence `lock → subprocess Claude → capture logs → unlock` est inchangée. Seule la notification de démarrage envoyée via `send_telegram()` (appel à `tg_post()` → `curl`) diffère selon le `trigger`.

## Références CLAUDE.md respectées

- **Règle 1 — Telegram via `curl`** : `send_telegram()` appelle `tg_post()` qui shell out vers `curl` — aucun `urllib` introduit.
- **Règle 5 — UTC interne / local à l'affichage** : le cycle auto utilise `fmt_local(started_at)` pour afficher l'heure locale dans la notification, tandis que `started_at` est en UTC en interne.
