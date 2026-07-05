# PR #353 — Enrichir /perf avec KPIs P&L, cycles, positions et watcher

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-349-perf-kpis`
> **Issues** : #349

## Contexte

Restructuration de la commande `/perf` pour afficher quatre blocs de KPIs (Key Performance Indicators) distincts : P&L réalisé, Cycles, Positions, et TP Watcher. Avant cette PR, la commande renvoyait un rapport très basique. Dorénavant, elle fournit une vue d'ensemble complète des performances du bot, avec historique P&L (total/7j/30j), taux de gain, répartition des cycles par type de skip (TYPE_A/B/C/D), comptage des positions ouvertes/fermées, et metriques du watcher TP.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/commands/perf.py` | Réécriture complète | Réorganisation en 4 blocs de KPIs avec fallbacks Mongo/JSONL |
| `binance-bot/commands/status.py` | Modification mineure | Suppression du calcul redondant de `_count_tp_watcher_sales_24h()` et du watcher health (déplacé en local) |
| `binance-bot/core/timing.py` | Ajout de fonction | Nouvelle fonction `parse_dt()` pour parser les timestamps ISO 8601 avec gestion robuste du fuseau horaire |

### Fonctions ajoutées / modifiées / supprimées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `_bloc_pnl()` | perf.py | Ajoutée | Calcule et formate le bloc 1 (P&L réalisé) avec stats sur 7j, 30j, win rate, meilleur/pire trade, top 3 coins par P&L, durée moyenne de détention |
| `_bloc_cycles()` | perf.py | Ajoutée | Calcule et formate le bloc 2 (Cycles) : total, avec BUY, répartition TYPE_A/B/C/D, durée moyenne, erreurs/quota Claude. Source Mongo en priorité, fallback `cycle_log.jsonl` transparent |
| `_load_cycles_jsonl()` | perf.py | Ajoutée | Charge le fichier `state/cycle_log.jsonl` (fallback si Mongo non disponible) |
| `_format_cycle_lines()` | perf.py | Ajoutée | Helper pour formater uniformément les lignes de Bloc 2 (réutilisé pour Mongo et JSONL) |
| `_bloc_positions()` | perf.py | Ajoutée | Calcule et formate le bloc 3 (Positions) : ouvertes/fermées, décomposition par SL / TP Watcher / Profit Phase 0, série consécutive en cours (Win/Loss streak) |
| `_bloc_watcher()` | perf.py | Ajoutée | Calcule et formate le bloc 4 (TP Watcher) : total_ticks, total_sales, ventes 24h/7j, USDC réalisés. Fallback "État inconnu" si `tp_watcher_state.json` absent |
| `run_perf()` | perf.py | Modifiée | Orchestration des 4 blocs + troncature message si > 4000 chars Telegram |
| `parse_dt()` | timing.py | Ajoutée | Parse un timestamp ISO 8601 en datetime aware UTC, avec gestion du suffixe redondant `+00:00Z` (passif ← Phase 8 write_cycle_log) |
| `_count_tp_watcher_sales_24h()` | status.py | Supprimée | Logique déplacée vers `_bloc_watcher()` de perf.py (plus approprié) |

## Décisions techniques notables

- **Fallback Mongo → JSONL** : Bloc 2 (Cycles) tente Mongo d'abord (pour accès à `duration_s` et `error_type`), puis bascule sur `cycle_log.jsonl` si Mongo non configuré ou erreur. Transparence totale : l'utilisateur n'a pas à savoir quelle source est utilisée.
  
- **parse_dt() robuste** : La fonction `parse_dt()` en timing.py gère les variations de format ISO 8601, en particulier le suffixe redondant `+00:00Z` généré par Phase 8. Cela évite les exceptions lors du parsing des champs `exit_date` dans trade_history.json.

- **Filtrage close_reason hétérogène** : Bloc 3 détecte les positions fermées par SL avec trois variantes (`"sl_hit"`, `"stop_hit"`, `"sl"`), car l'historique contient des données de plusieurs sources (anciennes + nouvelles phases). Un commentaire note que la normalisation source est hors scope.

- **Fallback TP Watcher gracieux** : Bloc 4 accepte que `tp_watcher_state.json` soit absent (cas où le watcher n'a jamais tourné) et affiche "⚠️ État inconnu" au lieu de crash.

- **Format HTML Telegram** : Tous les blocs utilisent `<code>` pour les chiffres, `<b>` pour les titres, et des émojis (📈, 🔄, 📊, 🤖) pour la lisibilité visuelle.

## Impact sur l'architecture

- **Pas d'impact architectural direct** : La PR n'ajoute aucun nouveau composant externe, ne modifie pas l'orchestration des cycles, et ne change pas l'état persistant (elle lit uniquement).

- **Amélioration de l'observabilité** : La commande `/perf` devient l'instrument de monitoring principal du bot, fournissant une vue unifiée des performances sans intervention de l'utilisateur (contrairement à `/status` qui lit Kraken en temps réel).

## Références CLAUDE.md respectées

- **Minimalisme** : Chaque fonction a une responsabilité unique (un bloc) ; le code fait le strict nécessaire (pas d'abstraction prématurée).
  
- **Modifications chirurgicales** : Seul `perf.py` a été réécrit ; `status.py` n'a eu qu'une suppression mineure (fonction redondante) ; `timing.py` a eu un ajout isolé.

- **Pas de secrets hardcodés** : Toutes les données viennent de fichiers state/ ou MongoDB, jamais de constantes du code.

- **Pas de gestion d'erreur excessive** : Les fallbacks (Mongo → JSONL, absence tp_watcher_state.json) restent simples et directs.

- **Pas de dépendances lourdes** : Utilisation uniquement de `json`, `datetime`, `typing` (stdlib), et de l'import local `core.timing.parse_dt`.

## Notes de test

- **Smoke test inclus** : La PR mentionne que Bloc 2 remonte 227 cycles depuis Mongo (test local), Bloc 3 détecte 3 ouvertes / 33 fermées / série 6W, message total ~1096 chars (bien sous la limite 4096).

- **Duration non rétroactif** : Le champ `duration_s` a été ajouté par #347 mais ne figure que sur les nouveaux cycles Mongo ; les cycles anciens n'en ont pas. Bloc 2 gère ce cas gracieusement.

- **Inconsistance close_reason** : Repérée mais non résolue (source dans le sous-processus Claude, hors scope). Bloc 3 en tient compte pour le comptage.
