# PR #374 — [M4] Tests d'intégration : phases 4 et 5 (sizing + exécution)

> **Mergée le** : 2026-07-26
> **Branche** : `feat/issue-367-tests-integration-phases-4-5`
> **Issues** : #367

## Contexte

Complète la suite de tests d'intégration lancée en PR #373 (phases 0 et 1) et PR #372 (harness + conventions). Ajoute la couverture pour les phases critiques 4 (dimensionnement des ordres) et 5 (exécution BUY MARKET + pose du stop-loss), qui orchestrent le passage d'ordres concrets via Kraken CLI et la gestion du risque.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `tests/test_phase4_sizing.py` | Ajout (160 lignes) | 6 tests unitaires pour le dimensionnement des ordres : calcul du stop (ATR), calcul du TP (reward/risk), filtres min_order/ordermin/costmin, arrondi lot_decimals |
| `tests/test_phase5_execution.py` | Ajout (203 lignes) | 5 tests unitaires pour l'exécution : skip TYPE_C (drift prix + solde insuffisant), BUY MARKET nominal + SL réussi, clôture immédiate au TP recalculé, protection failure alert |

### Fonctions testées

| Fonction / Module | Action | Description |
|---|---|---|
| `phase4_sizing.py` | Testé | Dimensionne chaque candidat BUY : calcul prix_stop (ATR multiplier), prix_tp (reward/risk ratio), montant_ordre (risk fixe), applique filtres ordermin/costmin de Kraken, arrondit quantité au pas lot_decimals, retourne ordres prêts à exécuter |
| `phase5_execution.py` | Testé | Exécute chaque ordre : vérifie drift prix (< price_deviation_max_pct), vérifie solde USDC disponible, passe BUY MARKET, récupère prix_réel post-fill, calcule TP recalculé, pose SL stop-loss, détecte clôture immédiate si prix ≥ TP, enregistre position dans trade_history, notifie Telegram |
| `core.trade_helpers.tg()` | Mocké | Aucun appel Telegram réel en test |
| `kraken-cli` | Redirigé | Appels vers `tests/fixtures/fake_kraken.py` (stub JSON) via `KRAKEN_CLI_PATH=<fake>` |
| `trade_history.json` | Mocké | Opérations de lecture/écriture interceptées ; fichier réel jamais touché |

## Décisions techniques notables

- **Réutilisation du harness** : les deux fichiers `test_phase4_sizing.py` et `test_phase5_execution.py` réutilisent intégralement le harness partagé `tests/fixtures/test_harness.py` (helpers `new_cycle_id`, `write_kraken_scenario`, `set_fake_kraken_env`, `exec_phase_script`, `fake_open_factory`, etc.) — zéro duplication de code de test, maintien du pattern établi en PR #372 et #373.

- **Scénarios JSON piloté pour phase 4** : le test configure `pairs_data` passé au scénario Kraken pour tester les filtres ordermin/costmin de paires réelles, plutôt que d'appeler le vrai `kraken pairs` ; contrôle prévisible du cas limite (quantité < ordermin).

- **Phase 5 : clôture immédiate au TP recalculé** : vérifie le comportement spécifié en PR #369 (refactor Phase 5) : si le prix post-fill remonte déjà au-dessus du TP recalculé (via `stop_distance_pct` et `reward_risk_ratio`), le cycle place un SELL MARKET immédiat et définit `close_reason: "market_above_tp_at_fill"` — cas d'arrivée trop rapide au profit cible.

- **Protection failure detection** : test du scénario où le BUY MARKET s'exécute mais la pose du stop-loss échoue (par exemple, solde insuffisant pour créer l'ordre ou appel réseau échoué) — vérifie `protection_failed=True` dans le rapport + notification Telegram d'alerte SL échoué.

- **Pas de simulateur de fill multi-appels** : le stub `fake_kraken.py` ne supporte pas la séquence "order → query-orders remplit progressivement" (pour retry de fill partiel) — ce cas n'est pas testé ici car non requis par le ticket #367 (5 cas listés pour phase 5) ; reste un pièges futur si rétry de fill partiel est implémenté.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale — ajout de tests sans modification du code applicatif. Complète la suite de tests démarrée en PR #372/373 ; la structure `tests/` évolue :
- Phase 0 & 1 ✅ (PR #373)
- Phase 3 ✅ (PR #372, `test_phase3_scoring.py` existant)
- **Phase 4 & 5 ✅ NEW** (PR #374)
- Phase 2, 6, 7, 8 : couverture future

## Références CLAUDE.md respectées

- **Minimalisme** : tests unitaires purs, aucun code applicatif ajouté. `tests/` évolue, `binance-bot/` inchangé.
- **Modification chirurgicale** : deux fichiers de test uniquement, réutilisent le harness sans duplication.
- **Convention horaire** : les scénarios JSON utilisent UTC pour timestamps ; les tests ne se fient pas à l'heure locale.
- **Pas de dépendances lourdes** : `unittest` stdlib, pas de `pytest` ni `mock` (utilise `unittest.mock` intégré).
- **Isolation des secrets** : `tests/fixtures/fake_kraken.py` remplace `kraken-cli`, aucun appel réseau réel.

## Résultat

- Suite de tests augmentée : 47 → 58 tests (11 nouveaux)
- CI `tests.yml` : `python -m unittest discover tests/ -v` passe à 58 tests, OK ✅
- Linting : `ruff check tests/test_phase4_sizing.py tests/test_phase5_execution.py` propre ✅
- Tests fonctionnels du bot avant merge : utilisateur doit envoyer `/status` depuis Telegram après restart (valide Phase 5 "en vrai" avant production)

---

**Clôt** : #367
