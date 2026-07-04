# PR #323 — Enrichir /status avec état TP Watcher et prix courant vs TP

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-322-status-tp-watcher-state`
> **Issue** : #322

## Contexte

Le thread TP Watcher (PR #321) surveille automatiquement les take profits depuis 2 minutes et vend les positions au TP sans intervention. Cependant, son état interne n'était pas exposé à l'utilisateur. La commande `/status` affichait les positions du portefeuille Kraken, mais sans :
1. Le prix courant depuis Kraken (uniquement le prix d'entrée et les niveaux SL/TP)
2. Le PnL % et la distance au TP en temps réel
3. L'état du TP Watcher lui-même (en cours, erreur récente, etc.)

Cette PR enrichit `/status` pour offrir une visibilité complète sur les positions actives et la santé du watcher.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/commands/status.py` | Modification | +64 lignes : ajout fonctions `_fetch_current_price()` et `_format_watcher_section()` ; refonte `_format_trades_section()` |
| `binance-bot/core/tp_watcher.py` | Modification | +34 lignes : ajout fonction `_write_watcher_state()` pour écriture atomique de l'état ; logging supplémentaire |

### Nouvelles fonctions

| Fonction | Fichier | Rôle |
|---|---|---|
| `_fetch_current_price(coin: str) -> float \| None` | commands/status.py:78 | Appelle `kraken-cli ticker {coin}USDC` et retourne le prix courant ou `None` si Kraken indisponible |
| `_format_watcher_section() -> list[str]` | commands/status.py:120 | Lit `state/tp_watcher_state.json` et retourne une section formatée avec emoji d'état (✅⚠️❌), heure dernier tick, et nb positions surveillées |
| `_write_watcher_state(status, last_error, positions_checked)` | core/tp_watcher.py:18 | Écrit atomiquement `state/tp_watcher_state.json` avec timestamp UTC + status + erreur optionnelle + compteur positions (via tempfile + os.replace) |

### Fonctions modifiées

| Fonction | Changement | Détail |
|---|---|---|
| `_format_trades_section()` | Enrichie | Appelle `_fetch_current_price()` pour chaque position ouverte, calcule PnL % et distance au TP, affiche prix courant + metrics |
| `_tp_watcher_tick()` | Logging + état | Appelle `_write_watcher_state()` à chaque tick avec status (`ok`, `warning`, `error`), et valide `exceptions` non gérées avec logging.warning |
| `run_status()` | Enchainement | Appelle la nouvelle `_format_watcher_section()` en dernier avant retour |

## Rendu `/status` enrichi

Avant (sans TP Watcher) :
```
🎯 XRP @ 1.1317 | Stop: 0.98 | TP: 1.2902
⏰ Prochain cycle auto : 04/07 14:05 UTC
```

Après (avec TP Watcher) :
```
🎯 XRP @ 1.1317 | Stop: 0.98 | TP: 1.2902 | Actuel: 1.15 (+1.6% | +12.2% → TP)

🤖 TP Watcher : ✅ Dernier tick 04/07 10:32 — 1 pos. surveillée(s)
```

En cas d'erreur watcher :
```
🤖 TP Watcher : ⚠️ Dernier tick 04/07 10:32 — 1 pos. surveillée(s)
  ⚠️ Dernière erreur : Ticker BTC indisponible : timeout
```

## État persistant nouveau

`state/tp_watcher_state.json` (créé/mis à jour par `_write_watcher_state()` tous les 120 secondes) :
```json
{
  "last_tick": "2026-07-04T10:32:15Z",
  "status": "ok",
  "last_error": null,
  "positions_checked": 1
}
```

Champs :
- `last_tick` : ISO 8601 UTC + Z (utilisé par `_format_watcher_section()` pour affichage local)
- `status` : `"ok"` (succès), `"warning"` (erreur ticker), `"error"` (erreur vente)
- `last_error` : message d'erreur texte ou `null`
- `positions_checked` : entier, nombre de positions traitées dans le tick

## Décisions techniques notables

- **Atomicité** : `_write_watcher_state()` écrit dans un tempfile puis `os.replace()` (pas de corruption partielle en cas d'arrêt brutal)
- **Isolation** : `_fetch_current_price()` captche les exceptions kraken-cli — `/status` ne crash jamais si le ticker est indisponible (`Actuel: n/d`)
- **Absence de dépendance Kraken** : les deux nouvelles fonctions utilisent uniquement `subprocess.run()` + `json.loads()` (pas d'import kraken-lib)
- **Pas de state global** : `_format_watcher_section()` lit le JSON à chaque appel (rafraîchit l'affichage)

## Impact sur l'architecture

**Composants nouvellement impliqués** :
- **Lecture-écriture `state/tp_watcher_state.json`** : nouveau fichier JSON persisté par le watcher, lu par `/status`
- **Appels Kraken dans `/status`** : chaque `/status` now triggered 1 call `kraken-cli ticker` par position ouverte (latence +1-2s attendue, mais acceptable pour une commande manuelle)

**Pas d'impact sur les phases du cycle** : les changements concernent uniquement les handlers commandes Telegram, pas l'orchestration du trading.

**Flux de données** :
```
TP Watcher (core/tp_watcher.py)
       │
       ├──► _write_watcher_state()
       │       │
       │       ▼
       │   state/tp_watcher_state.json
       │
/status handler (commands/status.py)
       │
       ├──► _fetch_current_price() → kraken-cli ticker
       │
       ├──► _format_watcher_section()
       │       │
       │       ▼ (lire tp_watcher_state.json)
       │
       ▼ Telegram notification
```

## Références CLAUDE.md respectées

- **Règle 1 (Python 3.11 + venv)** : aucune nouvelle dépendance ; code 100% stdlib (`json`, `subprocess`, `datetime`)
- **Règle 3 (secrets via .env)** : aucun secret nouveau, `KRAKEN_CLI_PATH` déjà chargé via `core/env.py`
- **Règle 4 (Telegram via curl)** : aucun changement Telegram ; toujours via `send_telegram()` qui wraps `tg_post(curl)`
- **Règle 5 (logs capturés)** : cycles de trading non affectés ; seuls les logs du watcher sont augmentés (`logger.debug()` + `logger.warning()`)
- **Règle 6 (UTC interne)** : timestamps `tp_watcher_state.json` en UTC ISO 8601 ; affichage local via `datetime.fromisoformat()` + `astimezone()`

## Tests

Selon le test plan du body PR :
- ✅ Bot démarré, attendre 2 min → `/status` affiche section TP Watcher avec ✅
- ✅ `state/tp_watcher_state.json` créé avec bons champs
- ✅ Si Kraken indisponible → `Actuel: n/d`, pas de crash
- ✅ Si `tp_watcher_state.json` absent → "Non démarré"
