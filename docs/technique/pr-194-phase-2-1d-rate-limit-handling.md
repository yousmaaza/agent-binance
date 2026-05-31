# PR #194 — Phase 2 : sleep 15s post-batch 4h + gestion erreur 1D silencieuse

> **Mergée le** : 2026-05-31
> **Branche** : `feat/issue-193-fix-1d-rate-limit`
> **Issues** : #193

## Contexte

Depuis la PR #104 (optimisation Phase 2 avec appels 1D filtrés), le bot lance un burst de 4 appels `coin_analysis` 4h en parallèle suivi immédiatement de 1-5 appels 1D séquentiels. Ce pattern viole l'** rate limit TradingView MCP** : après un burst parallèle, le quota se vide avant que les appels 1D (qui contiennent une information critique pour confirmer les signaux BUY) ne soient traités. Résultat : erreurs JSON ou réponses `{"error": ...}` sur les appels 1D, forçant le cycle à passer en mode dégradé avec seuil abaissé (`min_signal_score_degraded = 6` au lieu de 7).

Cette PR ajoute un délai de **récupération du rate limit** et améliore la **résilience en cas d'erreur 1D** pour absorber les dépassements transitoires sans bloquer le cycle.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Modification | Ajout des délais de récupération (15s post-batch 4h, 5s inter-appels 1D) + gestion d'erreur 1D silencieuse (Phase 2) |
| `config.json` | Modification | Ajout paramètre `min_signal_score_degraded` (6) pour le mode dégradé 1D |
| `state/cycle_log.jsonl` | Modification (logs) | Nouveaux cycles incluant les tentatives 1D avec rate limits |

### Sections modifiées du trade_prompt

| Fonction / Phase | Action | Description |
|---|---|---|
| Phase 2 — Étape B (couplage 1D) | Modifiée | **Avant (PR #104)** : appels 1D lancés immédiatement après le burst 4h, sans délai, sans gestion d'erreur. **Après (PR #194)** : attendre `time.sleep(15)` avant le PREMIER appel 1D du groupe pour laisser le rate limit se réinitialiser ; lancer ensuite les appels 1D en séquentiel avec `time.sleep(5)` entre chaque ; capturer les erreurs JSON/exception, assigner `signal_1d = "NEUTRAL"` et marquer `signal_1d_rate_limited = True` pour que Phase 3 adapte le seuil |

### Variables / fonctionnalités ajoutées

| Variable | Fichier | Rôle |
|---|---|---|
| `min_signal_score_degraded` | `config.json` | Seuil alternatif (6/10) appliqué en Phase 3 si tous les coins BUY 4h ont eu une erreur 1D — abaisse la barre sans pénaliser le cycle |
| `signal_1d_rate_limited` | TRADE_PROMPT | Flag par coin pour signaler qu'un appel 1D a échoué en rate limit ; utilisé en Phase 3 pour détecter si le cycle est en mode dégradé (tous les coins BUY 4h ont ce flag → `effective_min_score = min_signal_score_degraded`) |

## Décisions techniques notables

- **Délai 15s post-batch 4h** : TradingView MCP réinitialise un nouveau quota toutes les ~10-15s ; empiriquement, 15s absorbe le burst et prépare les 1D. Pas de garantie ferme, mais dégrade les erreurs à une fraction de cycle au lieu de 100%.
- **Délai 5s inter-appels 1D** : Les appels 1D maintiennent un débit bas après le batch, évitant les pics secondaires. Coût : +5s par coin analysé en 1D (acceptable pour un cycle 4h).
- **Gestion silencieuse de l'erreur 1D** : Une erreur rate limit TradingView (données manquantes) n'est pas un signal bearish. Assigner `signal_1d = "NEUTRAL"` (0 pts, aucun malus) permet au cycle de scorer sur le 4h dominant + les 6 autres critères (RSI, MACD, ADX, breakout, sentiment, momentum). Un coin STRONG_BUY 4h peut toujours atteindre 6/10 sans confirmation 1D.
- **Mode dégradé** : Si TOUS les coins BUY/STRONG_BUY 4h ont `signal_1d_rate_limited = True`, le cycle détecte le mode dégradé et abaisse automatiquement `effective_min_score = 6`. Cela évite un faux positif du cycle complet faute de données.
- **Pas de notification Telegram pour les erreurs 1D** : Les messages Telegram ne mentionnent pas les rate limits 1D transitoires (bruit utilisateur). Seul le flag `signal_1d_rate_limited` et la note "mode dégradé" en Phase 3 informent implicitement.

## Impact sur l'architecture

**Changement isolé**, pas d'impact sur l'architecture globale :
- Phase 2 structure identique, juste avec des `time.sleep()` ajoutés et un try/except autour des appels 1D
- Phase 3 scoring identique, avec un mécanisme adaptatif du seuil (pas un changement d'algorithme, juste un fallback)
- Aucun nouveau composant externe ou flux de donnée
- État persistant : `signal_1d_rate_limited` est local au cycle (pas de Mongo, pas de `trade_history.json`)

## Références CLAUDE.md respectées

- **Règle 5 (Convention horaire)** : Les délais de `time.sleep()` sont en secondes (absolues), non dépendantes du fuseau horaire.
- **Règle 6 (Auto-scheduler dans main_loop)** : Les délais s'exécutent dans le sous-processus Claude du cycle, n'affectent pas le scheduling.
- **Pas de modification de CLAUDE.md** : Les changements ne contredisent aucune contrainte existante.

---

## Test & validation

Les tests manuels effectués par l'utilisateur ont confirmé :
- Cycles avec 5+ candidats BUY 4h s'exécutent sans `JSONDecodeError` sur les appels 1D
- Mode dégradé détecté correctement en Phase 3 (seuil 6 appliqué)
- Tokens `__CYCLE_ID__`, `__PROJECT_DIR__`, `__HELPERS_PATH__` inchangés (12 occurrences dans le prompt)
- Redémarrage du bot valide via `/status` réponse < 5s
