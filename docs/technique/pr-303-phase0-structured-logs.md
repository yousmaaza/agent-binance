# PR #303 — Ajouter logs structurés pour traçabilité (Phase 0)

> **Mergée le** : 2026-07-03  
> **Branche** : `feat/issue-301-phase0-structured-logs`  
> **Issues** : #301

## Contexte

La Phase 0 du cycle de trading orchestre deux tâches critiques : le rattrapage des protections failées (`phase0_oco_retry.py`) et la mise à jour des trailing stops (`phase0_trailing_stop.py`). Ces deux modules évoluent constamment pour gérer les cas limites (retry OCO, fermeture de secours, mise à jour des stops). Cependant, il manquait une traçabilité structurée des décisions et des actions prises pendant ces phases — les logs étaient fragmentés entre notifications Telegram (pour l'utilisateur) et stdout du processus Claude (pour debug), sans point d'appui unifié.

Cette PR ajoute un système de logs structurés JSON (JSONL) permettant de tracer chaque événement Phase 0 (scan, tentative, succès, erreur) avec horodatage, cycle_id, et contexte métier — brique critique pour :
- **Audit** : comprendre pourquoi un trade a fermé, pourquoi un SL n'a pas pu être placé
- **Debugging** : reproduire un problème Phase 0 en rejouant la séquence d'événements
- **Optimisation** : mesurer la fréquence des skips, retries, fallbacks (données pour améliorer l'algo)

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/trade_helpers.py` | Ajout helper | Nouvelle fonction `log_phase0_event()` réutilisable par tous les scripts Phase 0 |
| `binance-bot/core/phases/phase0_oco_retry.py` | Instrumentation | 8 points d'appel à `log_phase0_event()` pour tracer retries, fermetures de secours, succès/échecs |
| `binance-bot/core/phases/phase0_trailing_stop.py` | Instrumentation | 5 points d'appel à `log_phase0_event()` pour tracer fetch prix, skips, updates, erreurs |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `log_phase0_event(cycle_id, phase, coin, action, details)` | Ajoutée | Helper d'écriture JSONL atomique dans `logs/phase0_events.jsonl` — enveloppe chaque événement avec timestamp ISO (UTC), cycle_id, phase (phase0_oco_retry / phase0_trailing_stop), coin affecté, action métier (protection_recovery_start, ts_update_success, etc.), et dict `details` libre ; silencieuse en cas d'erreur |
| `phase0_oco_retry.py:main loop` | Modifiée | Import `log_phase0_event`, ajout 8 appels à des points clés : démarrage protection recovery → SL skip (déjà actif) → force close > TP → retry exhaustion → fallback success/failed → SL retry success/failed |
| `phase0_trailing_stop.py:main loop` | Modifiée | Import `log_phase0_event`, ajout 5 appels : price fetch error → ts update skip (conditions non remplies) → SL cancel error → ts update failed → ts update success |

## Structures de logs (JSONL)

Chaque ligne du fichier `logs/phase0_events.jsonl` est un événement JSON indépendant :

```json
{
  "timestamp": "2026-07-03T12:34:56.789123Z",
  "cycle_id": "20260703_123456",
  "phase": "phase0_oco_retry|phase0_trailing_stop",
  "coin": "BTC",
  "action": "protection_recovery_start|sl_already_active_skip|...",
  "details": {
    "oco_retry_count": 0,
    "entry_price": 65200.5,
    "stop_price": 64000.0,
    "tp_price": 67000.0,
    "reason": "...",
    ...
  }
}
```

### Actions loggées — `phase0_oco_retry.py`

- **`protection_recovery_start`** : Lance la boucle de rattrapage pour une position `protection_failed=true` — contexte : retry count actuel, prix entry, stop, TP
- **`sl_already_active_skip`** : SL déjà ouvert (idempotence) — contexte : `sl_txid`, statut trouvé
- **`force_close_above_tp`** : Prix marché > TP, fermeture immédiate en market — contexte : prix actuel, TP
- **`force_close_success`** : Fermeture market réussie — contexte : exit_price, pnl_usdc, pnl_pct
- **`force_close_failed`** : Fermeture market échouée — contexte : erreur retournée
- **`retry_exhausted_fallback`** : Épuisement des retries (max_oco_retry atteint) — contexte : retry count, max, prix
- **`exhausted_fallback_success`** : Fermeture de secours réussie après épuisement — contexte : exit_price, pnl
- **`exhausted_fallback_failed`** : Fermeture de secours échouée — contexte : erreur
- **`sl_retry_success`** : Nouveau SL placé lors d'un retry — contexte : attempt #, max, txid, prix SL
- **`sl_retry_failed`** : Placement SL échoué lors d'un retry — contexte : attempt #, raison

### Actions loggées — `phase0_trailing_stop.py`

- **`price_fetch_error`** : Impossible de récupérer le prix actuel (exception) — contexte : erreur
- **`ts_update_skip`** : Skip de la mise à jour (conditions non remplies : progression insuffisante, stop trop haut) — contexte : raison, prix actuel, stops
- **`sl_cancel_error`** : Impossible d'annuler l'ancien SL — contexte : sl_txid, erreur
- **`ts_update_failed`** : Placement du nouveau SL échoué — contexte : erreur, prix tentés
- **`ts_update_success`** : Mise à jour trailing stop réussie — contexte : ancien/nouveau stop, ancien/nouveau TP, prix, nouveau sl_txid

## Décisions techniques notables

- **Format JSONL vs MongoDB** : Choix de persister les logs Phase 0 en JSONL local (`logs/phase0_events.jsonl`) plutôt que MongoDB :
  - **Avantage** : Indépendance de MongoDB (l'utilisateur peut désactiver Mongo), temps réel (pas de latence réseau), rotation manuelle simple (append-only)
  - **Raison** : Phase 0 s'exécute en parallèle du reste du cycle ; les décisions Phase 0 affectent les positions _avant_ que Phase 7 n'écrive en Mongo → JSONL local garantit une trace atomique et complète
  
- **Silencieuse en cas d'erreur** : `log_phase0_event()` ignore les exceptions lors de l'écriture (`try/except Exception: pass`) pour éviter de faire échouer une action métier (ex: SL placement) à cause d'une erreur de logging. La trace peut être perdue (rare), mais l'action métier continue.

- **Timestamp ISO avec microsecondes** : Format `%Y-%m-%dT%H:%M:%S.%fZ` garantit la chrono-unicité entre 7+ appels log dans une même seconde (règle CLAUDE.md #6).

- **Détails flexibles** : Chaque action peut ajouter un dict `details` libre — évite d'ajouter des paramètres à la fonction et permet l'évolution sans casser l'interface.

## Impact sur l'architecture

Changement **isolé, pas d'impact architectural** :
- Aucune nouvelle dépendance (json, os, datetime, tempfile déjà importés)
- Aucune modification de la logique métier (phase0_oco_retry, phase0_trailing_stop)
- Aucune nouvelle variable d'état global
- Aucun changement de flux de données (logs uniquement)
- Format d'écriture identique aux autres JSONL du projet (atomic, append-only)

Les logs sont **purement additifs** — un développeur qui ne lit pas `logs/phase0_events.jsonl` ne remarque aucune différence.

## Références CLAUDE.md respectées

- **Règle 3 — Modifications chirurgicales** : Uniquement les imports, appels log_phase0_event, et la nouvelle fonction. Zéro modification de la logique existante.
- **Règle 5 — Capture stdout/stderr** : Logs Phase 0 complémentent les fichiers `logs/stdout/cycle_*.log` et `logs/stderr/cycle_*.log` existants — ne les remplacent pas.
- **Règle 6 — Convention horaire UTC** : Tous les timestamps des logs Phase 0 sont en UTC (`.isoformat()` via `datetime.now(timezone.utc)`).
- **Règle 1 — Python 3.11 / venv** : Aucune nouvelle dépendance ; utilise uniquement stdlib (json, datetime, os).

## Utilité

Cette traçabilité structurée servira la future itération d'audit Phase 0 (issue #300, non inclus ici) qui affichera un résumé des événements Phase 0 dans le rapport Telegram final — la brique de logging est prête, l'agrégation viendra après.

---

**Fichiers ajoutés/modifiés** :
- `binance-bot/core/trade_helpers.py` : +21 lignes (fonction helper)
- `binance-bot/core/phases/phase0_oco_retry.py` : +52 lignes (imports + 8 log calls + détails)
- `binance-bot/core/phases/phase0_trailing_stop.py` : +34 lignes (imports + 5 log calls + détails)

**Total** : 107 lignes ajoutées | 2 lignes modifiées | 0 supprimées
