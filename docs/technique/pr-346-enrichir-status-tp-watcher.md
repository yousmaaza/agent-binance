# PR #346 — Enrichir /status avec les infos du TP Watcher

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-345-status-tp-watcher`
> **Issue** : #345

## Contexte

Amélioration de PR #323 : la section TP Watcher affichait uniquement le statut global et l'heure du dernier tick. Cependant, l'utilisateur avait besoin de :
1. Un indicateur clair de la **santé** du watcher (OK / Lent / Inactif) basé sur l'âge du `last_tick`
2. Le **nombre de ventes TP exécutées** dans les 24 dernières heures (métrique clé de performance)
3. Une gestion **robuste** si `tp_watcher_state.json` est absent ou corrompu (pas de crash, message clair)

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/commands/status.py` | Modification | +71 lignes : 3 nouvelles fonctions + refonte complète de `_format_watcher_section()` |

### Nouvelles fonctions

| Fonction | Ligne | Rôle |
|---|---|---|
| `_parse_last_tick(raw: str) -> datetime \| None` | 121-130 | Parse le timestamp ISO 8601 du dernier tick (gère le Z redondant `+00:00Z`), retourne `datetime` aware UTC ou `None` |
| `_tp_watcher_health(last_tick_dt: datetime) -> str` | 133-141 | Classe le watcher en 3 états selon l'âge du tick : `✅ OK` (<5 min), `⚠️ Lent` (5-10 min), `🔴 Inactif` (>10 min) |
| `_count_tp_watcher_sales_24h() -> int` | 144-169 | Compte les ventes TP depuis `trade_history.json` : filtre `close_reason` contient `"tp_watcher"` + `exit_date` dans les 24h UTC |

### Fonctions modifiées

| Fonction | Changement | Détail |
|---|---|---|
| `_format_watcher_section()` | Refonte complète | Affiche 4 infos : santé (emoji + label), heure dernier tick (locale), positions surveillées, ventes TP (24h) ; gestion gracieuse si state absent/corrompu (→ "⚠️ État inconnu") |

## Décisions techniques notables

- **Robustesse** : `_format_watcher_section()` ne lève jamais d'exception (try/except imbriqué) — si `tp_watcher_state.json` absent, affiche `"⚠️ État inconnu"` sans crash
- **Parsing timestamp** : `_parse_last_tick()` nettoie le Z redondant dans `+00:00Z` (format inhabituel du watcher) avant `fromisoformat()` — sinon `ValueError`
- **UTC strictement interne** : `_tp_watcher_health()` compare en UTC, `_count_tp_watcher_sales_24h()` filtre par UTC - 24h sans ambiguïté
- **Affichage local** : `fmt_local()` convertit le tick UTC en heure locale de l'utilisateur pour `/status` (déjà existant via `core.timing`)
- **Aucune nouvelle dépendance** : uniquement `datetime` stdlib, pas de kraken-lib

## Rendu `/status` enrichi

```
🤖 TP Watcher : ✅ OK
  Dernier tick : 04/07 10:32 (heure locale)
  Positions surveillées : 3
  Ventes TP (24h) : 2
```

En cas de dégradation :
```
🤖 TP Watcher : ⚠️ Lent
  Dernier tick : 04/07 09:15
  Positions surveillées : 3
  Ventes TP (24h) : 2
```

Si state indisponible :
```
🤖 TP Watcher : ⚠️ État inconnu
```

## État persistant

`state/tp_watcher_state.json` (format de PR #321) :
```json
{
  "last_tick": "2026-07-04T10:32:15+00:00Z",
  "status": "ok",
  "last_error": null,
  "positions_checked": 3
}
```

Format du champ `last_tick` : `ISO 8601 + Z redondant` — non standard mais géré par `_parse_last_tick()`.

## Impact sur l'architecture

Changement isolé, **pas d'impact architectural** :
- Aucune nouvelle dépendance externe
- Aucune modification des phases du cycle
- Aucune modification du watcher lui-même (PR #321)
- Enrichissement purement côté **commande `/status`** (handler Telegram)

Flux de données inchangé depuis PR #323 :
```
TP Watcher (core/tp_watcher.py)
       │
       └──► state/tp_watcher_state.json
                   ▲
                   │
/status handler (commands/status.py)
       │
       ├──► _parse_last_tick() → _tp_watcher_health()
       │
       └──► _count_tp_watcher_sales_24h()
                   │
                   ▼ (lire trade_history.json)
                   
Telegram notification
```

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : `_count_tp_watcher_sales_24h()` utilise `f"{PROJECT_DIR}/state/trade_history.json"`
- **Règle 6 (UTC interne / local affichage)** : logique de `_tp_watcher_health()` en UTC, `fmt_local()` pour affichage
- **Règle 5 (logs capturés)** : aucun log additionnel (fonctions silencieuses sur exception)
- **Minimalisme (CLAUDE.md principes)** : 3 petites fonctions (<30 lignes chacune), pas de gestion d'erreur pour scénarios impossibles

## Validation test plan

- ✅ Section TP Watcher visible dans `/status` avec 4 infos (santé, dernier tick, positions, ventes 24h)
- ✅ Renommer temporairement `state/tp_watcher_state.json` → `/status` affiche "⚠️ État inconnu" sans crash
- ✅ Syntaxe Python correcte (`ast.parse()` passe)
- ✅ Heure dernier tick affichée en **heure locale** (format hh:mm via `fmt_local()`)
