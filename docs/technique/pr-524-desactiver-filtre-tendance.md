# PR #524 — [STRAT] Désactiver le filtre de tendance de fond (EMA100 1d)

> **Mergée le** : 2026-11-15
> **Branche** : `feat/issue-523-desactiver-filtre-tendance`
> **Issue** : #523

## Contexte

Depuis le 31/10/2026, 90 cycles consécutifs sans aucun ordre exécuté. Les scores 4h générés par TradingView sont majoritairement NEUTRAL, et le **filtre de tendance de fond** (`trend_filter_enabled = true`) bloque tout achat tant que BTC reste **sous son EMA100 1d**. L'utilisateur a décidé de désactiver ce verrou pour observer le bot en action sur une période (4-6 semaines), puis réévaluer sur données réelles.

**Ce n'est pas une optimisation mesurée** : les simulations (`stop_trend_replay.py`) montrent que la stratégie n'est gagnante ni avec ni sans le filtre.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Configuration | `trend_filter_enabled` : `true` → `false` |
| `docs/strategie.html` | Documentation | Tableau config + section 15/11 ajoutée |
| `docs/strategie.md` | Documentation | Régénération depuis strategie.html |
| `tests/test_stop_trend_521.py` | Test | Alignement du test de config |

### Fonctions touchées

Aucune fonction Python n'a été modifiée. La Phase 3 (`phase3_scoring.py`) reste inchangée — elle **vérifie seulement** le flag `trend_filter_enabled` qui était déjà présent depuis la PR #521 (octobre 2026).

| Fonction | Action | Impact |
|---|---|---|
| Aucune modification de code | — | Changement de configuration isolé |

## Décisions techniques notables

- **Configuration uniquement** : le filtre de tendance était déjà implémenté en Phase 3 (PR #521) derrière un interrupteur. Désactiver c'est mettre l'interrupteur à `false`, sans toucher au code.
- **Aucun revert de code** : le code reste disponible pour un retour arrière facile (`trend_filter_enabled: true` dans config.json).
- **Période d'observation** : l'utilisateur surveille les résultats sur ~30 trades ou 4 semaines avant de décider d'un retour arrière ou d'une amélioration mesurée.

## Impact sur l'architecture

**Aucun impact architectural.** C'est une modification de configuration runtime.

- La Phase 3 continue de vérifier le flag `trend_filter_enabled` comme avant.
- Kraken CLI n'est plus appelé pour fetcher les bougies 1d du couple et de BTC (économie mineure d'appels API).
- Les tests unitaires de Phase 3 continuent de fonctionner (le test `test_config_json_new_rules` a juste été aligné sur la nouvelle valeur par défaut).

## Références CLAUDE.md respectées

- **Règle 8** (*Toute modification de la stratégie met à jour `docs/strategie.html`*) : une nouvelle section "15/11" a été ajoutée au document avec mesures, pistes écartées et notes de suivi.
- **Minimalisme** : seul le changement minimal a été effectué (pas de refactor, pas de suppression de code).
- **Chirurgicalité** : modification isolée à `config.json` et documentation, aucun code applicatif.

## Notes de suivi

- **Remesure prévue** : après ~30 trades clôturés ou 4 semaines, réévaluer le PnL net, le taux de gain et les achats effectués pendant les phases BTC sous-EMA100.
- **Retour arrière** : simple, repasser `trend_filter_enabled` à `true` et redéployer.
- **Autres paramètres** : aucun autre changement de config ou de stratégie dans cette PR.

---

**Code applicatif** : aucun changement.
**Documentation mise à jour** : `docs/strategie.html` et `docs/strategie.md` (régénéré).
