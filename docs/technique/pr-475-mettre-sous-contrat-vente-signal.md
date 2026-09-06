# PR #475 — Mettre sous contrat la vente sur signal (score ≤ 3)

> **Mergée le** : 2026-09-06
> **Branche** : `feat/issue-472-phase3-signal-sell`
> **Issues** : #472

## Contexte

Jusqu'à #475, la **vente des coins avec score ≤ 3** (sell_candidates produits par phase3_scoring.py) était un bloc de code semi-improvisé dans le prompt Claude de Phase 3. Cela causait quatre défauts majeurs :
1. **Pas de contrat prompt ↔ script** : chaque cycle rejouait la logique, sans trace fiable du succès/échec
2. **Jamais de protection si la vente échouait** : position pouvait rester nue après annulation du stop
3. **Pas de traçabilité du remplissage partiel** : reliquats ignorés ou compris comme clôturés
4. **Quantité non fiable** : incident XRP du 18/08 : EOrder:Insufficient funds car quantité brute sans ajustement au solde réel

Pour chacun, une solution existait ailleurs dans le projet — juste pas centralisée dans une seule phase. La PR exécute cette centralisation.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase3_signal_sell.py` | Ajouté (213 lignes) | Nouveau script Python qui orchestre l'exécution des ventes sur signal |
| `binance-bot/core/maker_exit_watcher.py` | Modifié (7 lignes ajoutées, 4 modifiées) | Paramètre `context` ajouté à `_repose_stop_and_alert()` pour personnaliser les messages d'alerte |
| `prompts/phases/phase3_scoring.txt` | Modifié (19 lignes ajoutées, 1 ligne supprimée) | Remplace consigne minimale par appel explicite au script de vente sur signal |
| `tests/test_phase3_signal_sell.py` | Ajouté (318 lignes) | Suite de tests complète couvrant tous les cas d'usage du nouveau script |
| `tests/test_prompt_script_contract.py` | Modifié (1 ligne ajoutée) | Enregistre `phase3_signal_sell` dans le registre des contrats prompt/script |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `phase3_signal_sell()` (script entier) | Ajoutée | Orchestre l'exécution des ventes sur signal (`sell_candidates` score ≤ 3) : annulation du stop → vente marché → query fill (3 tentatives) → clôture ou reprotection |
| `_repose_stop_and_alert(pending, history, qty, reason, context)` | Modifiée | Paramètre `context` ajouté pour nommer le mécanisme appelant (par défaut "sortie maker", maintenant aussi "vente sur signal") dans les notifications Telegram, afin de ne pas induire l'utilisateur en erreur sur l'origine du problème |

## Décisions techniques notables

- **Contrat fixe via /tmp** : le script et le prompt s'échangent les données via `/tmp/cycle_{CYCLE_ID}_phase3_signal_sell_*.json` — même approche qu'autres phases, selon le modèle `phase0_profit.py` / `phase0_snapshot.txt` établi en #270. Stockage temporaire volontaire en attente de migration `/tmp` → `state/` (#392, #403).

- **Jamais de prix fabriqué** : quand le fill reste introuvable après 3 tentatives, le trade n'est **pas** clôturé — principes de #469 (« marquer, jamais réécrire ») et de traçabilité. La position est reprotégée immédiatement ; si la vente a eu lieu, le repose échouera (solde insuffisant) et rendra le problème visible.

- **Jamais de position nue** : la fonction `_repose_stop_and_alert()` (importée de `core/maker_exit_watcher.py`, déjà en production) est réutilisée chaque fois qu'une vente échoue **après** l'annulation du stop. Elle est idempotente et éprouvée (#390, #462).

- **Quantité = min(trade_history, solde réel)** : correction de l'incident XRP du 18/08. Tronquée au `lot_decimals` de la paire (même approche que `phase5_execution.py`), pour éviter les EOrder:Insufficient funds. Un reliquat plus petit que le pas de la paire n'est de toute façon ni vendable ni protégeable — absorbé silencieusement.

- **Remplissage partiel = position non clôturée** : le reliquat reste une position ouverte, suivi et protégé au prochain cycle, plutôt que d'être compté comme une clôture totale et masquer un problème #472 review.

- **Paramètre context** : raison de la modification à `_repose_stop_and_alert()`. Avant, tout appel disait « position NON protégée après échec sortie maker » — trompeur quand l'appelant est la vente sur signal. Maintenant, l'appelant passe son propre libellé (« vente sur signal ») ; la sortie maker reste au défaut « sortie maker ».

- **Logs heartbeat par phase** : le script écrit sur stdout `PHASE3_SIGNAL_SELL_DONE|closed=N`, capturé côté prompt pour mettre à jour les variables de synthèse du heartbeat Phase 3.

## Impact sur l'architecture

**Localisation de la Phase 3** (flow schématique) :
```
Phase 3 Input
├── phase3_scoring.py (produit buy_candidates, sell_candidates, skip_coins_detail)
└─► phase3_signal_sell.py (orchestre l'exécution)
    ├── Annule stop actif (sl_order_txid)
    ├── Vend au marché min(quantity, balance) tronqué au lot_decimals
    ├── Query du fill (3 tentatives / 2s)
    └── Clôture ou reprotection via _repose_stop_and_alert()
        ↓
    Output : /tmp/cycle_{CYCLE_ID}_phase3_signal_sell_output.json { "closed": N }
        ↓ (lu par Phase 3 prompt, mis à jour heartbeat)
    Notification Telegram + sauvegarde atomique trade_history
```

**Intégration au flux global** (prompts/phases/phase3_scoring.txt) :
- Précédemment : consigne minimale « Claude, improvise la vente des sell_candidates »
- Maintenant : appel structuré au script avec contrat de données explicite

La **séparation prompt ↔ script** établit une frontière claire :
- Le **prompt** (phase3_scoring.txt) : décrit les phases logiques (scan, scoring, sélection)
- Les **scripts** (phase0/3/5/8) : orchestrent l'exécution (appels Kraken-cli, état persistant)

Ce pattern, éprouvé ailleurs (#270), rend chaque phase testable indépendamment et sa sortie traçable dans les logs.

## Références CLAUDE.md respectées

- **Règle 1 — Tout via venv .venv (Python 3.11)** : le script s'exécute via `.venv/bin/python3` depuis le prompt, important ses helpers depuis le venv.

- **Règle 2 — PROJECT_DIR dynamique** : ✓ `PROJECT_DIR = os.path.dirname(os.path.dirname(...))` (ligne 41), utilisé pour charger config, trade_history et appels aux helpers.

- **Règle 3 — Pas de code modificateur direct sur main** : ✓ PR opérée via la branche dédiée et le workflow ticket → branche → PR.

- **Règle 4 — Tous appels Telegram via curl** : ✓ C'est le prompt qui notifie, pas le script. Le script appelle `tg()` (helper du prompt), qui shell out vers curl.

- **Règle 5 — Stdout/stderr toujours sauvegardés** : ✓ Stdout du script sur stdout → logs/stdout/cycle_{cycle_id}.log ; erreurs → logs/stderr/cycle_{cycle_id}.log (géré par `run_trade_workflow()`).

- **Règle 6 — UTC interne, local à l'affichage** : ✓ Phase3_signal_sell ne s'appuie que sur des timestamps stockés en UTC dans trade_history. Affichage des notifications via fmt_local() du prompt.

- **Règle 7 — Contrats prompt ↔ script via /tmp** : ✓ Input/output JSON à chemins fixes par cycle, validés dans `tests/test_prompt_script_contract.py`.

## Tests

- **Cas nominal** (stop actif) : annulation → vente → fill retrouvé → clôture avec close_reason=signal_sell_scoreN, cycle_id et PnL net
- **Sans stop actif** : pas d'annulation tentée, vente normale
- **Sans trade open** : passe sans rien casser
- **Fill introuvable après 3 tentatives** : jamais de prix fabriqué, trade non clôturé, reprotection immédiate
- **SELL échoué après annulation du stop** : reprotection via `_repose_stop_and_alert()`, jamais nue
- **Remplissage partiel** : reliquat suivi et protégé, pas clôturé
- **Quantité insuffisante ou dépassant le solde** : tronquée au lot_decimals et min(trade_qty, balance)

Résultats : `pytest tests/ → 510 passed` (baseline main : 493 + les tests phase3_signal_sell ajoutés).
