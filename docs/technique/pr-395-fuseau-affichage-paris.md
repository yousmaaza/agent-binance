# PR #395 — Fuseau d'affichage explicite (heure locale réellement Paris)

> **Mergée le** : 2026-08-22
> **Branche** : `feat/issue-393-display-timezone`
> **Issues** : #393

## Contexte

Avant cette PR, `fmt_local()` utilisait `datetime.astimezone()` sans argument, qui convertissait au fuseau **de la machine hôte**. Sur une VPS en `Etc/UTC` (fuseau par défaut), toutes les notifications Telegram affichaient l'heure UTC en disant « heure locale » — trompeur pour l'utilisateur en France (Europe/Paris).

Le ticket #393 demandait de rendre le fuseau d'affichage explicite et configurable.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/timing.py` | Modification | `fmt_local()` lit `display_timezone` depuis config.json et convertit via `zoneinfo.ZoneInfo` au lieu de `astimezone()` sans argument |
| `config.json` | Modification | Ajout de la clé `"display_timezone": "Europe/Paris"` en début du fichier |
| `tests/test_timing.py` | Ajouté | 4 nouveaux tests unitaires validant été/hiver et replis en cas de clé manquante/fuseau invalide |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `fmt_local(dt_utc: datetime) -> str` | Modifiée | Convertit un datetime UTC via `ZoneInfo(APP_CONFIG["display_timezone"])` au lieu de `astimezone()`. Repli sur `astimezone()` si clé absente ou `ZoneInfoNotFoundError` |

## Décisions techniques notables

- **`zoneinfo.ZoneInfo`** : module stdlib Python 3.11, gère automatiquement les transitions heure d'été/hiver — aucune dépendance externe.
- **Repli gracieux** : si `display_timezone` est absent ou contient un fuseau inconnu, utilise `astimezone()` sans argument (comportement antérieur) pour éviter un crash.
- **Configuration centralisée** : la clé vit dans `config.json` (qui a déjà `APP_CONFIG`) plutôt que `.env`, pour uniformité avec les autres paramètres métier (risk, sizing).
- **`fmt_next()` inchangé** : délègue entièrement à `fmt_local()`, donc bénéficie automatiquement de la correction sans modification.

## Impact sur l'architecture

Changement **isolé sur la couche affichage** :
- Les slots UTC (`next_4h_slot()`, `next_1h_slot()`) restent en UTC.
- Les timestamps internes (Mongo, JSONL, heartbeat) restent en UTC.
- Seules les notifications Telegram visibles par l'utilisateur sont converties en `display_timezone`.
- **Pas d'impact architectural** — un raffinement de `fmt_local()`, utilisée via `fmt_next()` dans la notification du prochain cycle auto.

## Références CLAUDE.md respectées

- **Règle 6 — Convention horaire** : `fmt_local()` affiche maintenant explicitement en heure locale (via `display_timezone`), distinction claire UTC/local.
- **Aucun secret hardcodé** : `display_timezone` est dans `config.json` (métier, pas secret), accessible via `APP_CONFIG.get()`.
- **Portabilité Mac → VPS** : sur VPS en `Etc/UTC`, on configure `display_timezone: "Europe/Paris"` une fois dans `config.json` — les notifications affichent Paris indépendamment du fuseau système.

---

## Tests

Suite de tests `tests/test_timing.py` (4 cas) :
1. **Été UTC → Paris CEST** : `2026-07-01 10:00 UTC` → `"01/07 12:00 (heure locale)"` (UTC+2)
2. **Hiver UTC → Paris CET** : `2026-01-01 10:00 UTC` → `"01/01 11:00 (heure locale)"` (UTC+1)
3. **Clé absente** : repli sur `astimezone()`, pas de crash
4. **Fuseau invalide** : catch `ZoneInfoNotFoundError`, repli sur `astimezone()`

Suite complète `python -m unittest discover tests/ -v` : **114 tests, OK**.

