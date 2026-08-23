# PR #413 — Durcir le RSI en garde-fou d'éligibilité en mode dégradé

> **Mergée le** : 2026-08-23
> **Branche** : `feat/issue-406-mode-degrade-rsi`
> **Issues** : #406

## Contexte

Incident de régression sur le coin TRUMP (2026-08-22) : en mode dégradé (rate-limit TradingView 1D sur tous les coins BUY 4h), un coin suracheté (RSI 4h = 70.4, hors zone [30, 65]) avec score suffisant (4/10 ≥ 4/10 du seuil dégradé) a quand même été acheté. La raison : le RSI était traité uniquement comme un **bonus** de score (+1 si dans zone), pas comme un **garde-fou d'éligibilité**. Sans signal 1D (absent en mode dégradé), on aurait dû refuser d'acheter un actif suracheté.

La PR #406 pose le garde-fou RSI : en mode dégradé, le RSI devient une **condition d'éligibilité** (pas juste un bonus) — un coin avec RSI hors zone est exclu même s'il atteint le seuil abaissé de score (`min_signal_score_degraded`). RSI inconnu (`None`) est aussi traité comme inéligible : deux inconnues ne se compensent pas.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase3_scoring.py` | Modification | Ajout de la variable `rsi_in_zone` et du bloc `degraded_rsi_block` pour implémenter le garde-fou RSI en mode dégradé |
| `tests/test_phase3_scoring.py` | Ajout de tests | 4 nouveaux tests de couverture (`TestDegradedModeRsiGuard`) |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| Boucle de scoring (phase3_scoring.py, lignes 70–150) | Modifiée | Ajout d'une vérification `degraded_rsi_block` avant d'ajouter un coin aux `buy_candidates` — le coin est skippé avec `TYPE_A` si RSI est hors zone en mode dégradé |

## Décisions techniques notables

1. **Le garde-fou RSI ne s'applique que aux nouveaux achats** (nouveaux `buy_candidates`), pas au chemin `HOLD` d'un coin déjà en portefeuille. Raison : la décision de tenir une position est dissociée de la décision d'acheter ; le bloc RSI protège uniquement l'entrée.

2. **RSI inconnu (`None`) = inéligible en mode dégradé**. Raison : sans signal 1D et sans RSI, deux sources d'information sont absentes ; on ne peut pas cumuler deux inconnues. Le skip est explicite : `skip_detail = "RSI indisponible (mode dégradé)"`.

3. **Variable intermédiaire `rsi_in_zone`** (ligne 87) : extraction de la logique booléenne pour clarifier l'intentionnalité (RSI dans la zone saine = bonus, ET condition pour le garde-fou en mode dégradé).

4. **Hors mode dégradé** : le comportement RSI-bonus de la PR #380 est strictement inchangé. Le RSI reste un simple bonus de score, pas un garde-fou.

## Impact sur l'architecture

Changement isolé à la Phase 3 — impact stratégique minime :
- **Nouvelle logique de rejet** : coins survendus sont explicitement skippés avec `TYPE_A` (skip raison stratégique, pas technique)
- **Skip_detail explicite** : permet de tracer pourquoi un bon score a été rejeté en mode dégradé
- **Pas d'impact sur les phases adjacentes** : Phase 4 & 5 reçoivent les mêmes `buy_candidates` (simplement filtrés plus tôt)

## Références CLAUDE.md respectées

- **Minimalisme** : une seule modification, bien délimitée (3 lignes de code net + 13 lignes de logique bloc)
- **Chirurgicales** : la boucle de scoring reste lisible, une branche `elif` insérée avant les filtres existants (max positions, corrélation)
- **Tests exhaustifs** : 4 scénarios couvrent les cas clés (RSI haut bloquant, RSI sain permissif, RSI absent bloquant, mode normal inchangé)

## Tests

Suite complète du projet :
```bash
python -m unittest discover -s tests -p "test_*.py"
# → 156 tests, 0 échec, 0 erreur
```

Tests spécifiques ajoutés (`tests/test_phase3_scoring.py:TestDegradedModeRsiGuard`) :
- `test_degraded_high_rsi_is_skipped_even_above_threshold()` — Coin TRUMP avec RSI 70.4 > 65, score 4 = seuil dégradé → SKIP TYPE_A
- `test_degraded_healthy_rsi_stays_eligible()` — Coin avec RSI 45 ∈ [30, 65], score 4 → BUY (pas bloqué)
- `test_degraded_unknown_rsi_is_skipped()` — RSI `None` en mode dégradé → SKIP TYPE_A, skip_detail explicite
- `test_normal_mode_high_rsi_with_high_score_still_buys()` — Mode normal (pas rate-limit), RSI 70.4 hors zone mais score 6 → BUY (RSI reste bonus, pas garde-fou)

