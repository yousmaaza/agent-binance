# PR #489 — Sortie maker sur la vente sur signal (score ≤ 3)

> **Mergée le** : 2026-09-11
> **Branche** : `claude/sortie-avec-maker-5anl0n`
> **Ferme** : #488

## Contexte

Jusqu'à cette PR, la vente sur signal retombé (score ≤ 3) vendait **toujours au marché** (taker), au tarif preneur. Or `core/maker_exit_watcher.py` (#390) offrait déjà un chemin discrétionnaire pour les TP atteint (tp_watcher.py) et l'objectif de profit (phase0_profit.py) : une vente LIMIT post-only, suivie par un watcher qui bascule au marché si la concession dépasse 0,3% ou après 10 minutes.

Le score retombé n'est pas une urgence : contrairement à un stop touché (protection obligatoire) ou une réalisation de profit (opportunité de marché immédiate), une vente sur signal peut attendre son acheteur en limite. Gain estimé : **~8,61 USDC** sur les 29 ventes de l'historique, soit 0,3% du volume, à comparer au résultat net du bot actuellement négatif (−26 USDC).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/maker_exit_watcher.py` | Modification | Extension de la signature `attempt_maker_exit()` pour accepter un volume imposé |
| `binance-bot/core/phases/phase3_signal_sell.py` | Modification majeure | Logique dédoublée : chemin maker ou marché selon solde et config |
| `prompts/phases/phase3_scoring.txt` | Modification | Intégration du compteur `maker_pending` dans la sortie JSON |
| `tests/test_maker_exit_watcher.py` | Modification | Ajout de tests unitaires pour la nouvelle signature et expansion du test d'appelants |
| `tests/test_phase3_signal_sell.py` | Modification majeure | Suite complète de tests du chemin maker : 5 cas limites validés |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `attempt_maker_exit()` | Modifiée | Signature étendues (param `quantity` optionnel) pour que l'appelant impose le volume ; clarification docstring des trois appelants : TP watcher, objectif profit, vente sur signal |
| `phase3_signal_sell.py::main` | Modifiée | Logique dédoublée : si solde couvre la position, délégation maker ; sinon, repli marché ; comptage de `maker_pending` dans la sortie |
| `_maker_exit_patchers()` (tests) | Ajoutée | Factory pour patcher l'état persistant du watcher en tests |

## Décisions techniques notables

1. **Paramètre `quantity` optionnel** : la vente sur signal calcule elle-même la quantité (min(trade_qty, solde réel), tronquée au pas Kraken) depuis l'incident XRP du 18/08 (#472). Elle passe ce volume arrondi à `attempt_maker_exit()` plutôt que de le remettre dans `pos["quantity"]`, car un pos["sl_order_txid"] déjà purgé (stop annulé en Step 1 du script) évite au watcher une seconde annulation rejetée par Kraken.

2. **Vérification de non-doublure** : quand le watcher charge déjà un ordre maker pour ce trade, le script passe (ne vend pas une seconde fois). Cette vérification entre les deux appels à `load_maker_exit_pending_orders()` (début de script + avant pose de la limite) garantit qu'aucune position ne subit deux ventes en parallèle.

3. **Fallback marché sur solde insuffisant** : le watcher clôture le trade entier dès que sa limite est remplie — il n'a aucune notion de vente partielle. Si le solde réel ne couvre qu'une partie de la position, la vente reste donc sur le chemin marché classique (qui mesure le reliquat et le reprotège), jamais sur le chemin maker.

4. **Délégation via callback de notification** : le watcher appelle une fonction `notify()`, par défaut `send_telegram`. La vente sur signal passe un callback lambda qui préfixe les messages du watcher avec le score retombé, gardant le motif de la vente visible en cas de succès ou d'échec sans générer une deuxième notification.

5. **État persistant `maker_exit_pending_orders.json`** : la sortie JSON de phase3_signal_sell.py inclut maintenant `maker_pending` (nombre de ventes déléguées), distinct de `closed` (ventes complétées). Phase 3 du prompt doit lire les deux et mettre à jour ses compteurs de synthèse.

## Impact sur l'architecture

**Flux modifié de Phase 3** :
```
Phase 3 : Scoring
├── phase3_scoring.py → BUY / HOLD / SKIP / SELL
│
└── phase3_signal_sell.py
    ├── Step 1 : annuler SL si existe
    ├── Step 2 : calculer min(trade_qty, solde réel), tronqué au pas
    ├── Step 3 : si maker_exit_enabled ∧ solde couvre toute la position
    │   └──► attempt_maker_exit() + enregistrement dans maker_exit_pending_orders
    │        Output: {"closed": 0, "maker_pending": 1}
    │        ⚠️ Le trade n'est PAS clôturé ici, sera clôturé par le watcher
    │
    └── Step 4+ : SELL MARKET (repli)
        Output: {"closed": N, "maker_pending": 0}
        (Cas dégradé ou solde insuffisant)
```

**Conséquences observables** :
- Les ventes sur signal avec solde suffisant ne retournent plus une clôture immédiate mais une "clôture en attente" (maker_pending).
- Le TP d'une position peut être atteint (watcher) tandis que son score retombe (vente sur signal) — le watcher duplexe les deux ordres limit et choisit celui qui se remplit en premier ; le second est annulé.
- Les traces de sortie (`exit_maker_or_taker`) ne sont pas visibles en Phase 7 ni sur le dashboard — limité actuellement à l'usage interne du watcher. Suivi séparé prévu.

**Compatibilité backwards** :
- `config.json:maker_exit_enabled` (défaut `True`) bascule la fonctionnalité. `False` restaure le chemin marché pur.
- Champs `maker_pending` dans la sortie JSON : consommée en Phase 3 du prompt, doit être passée dans la synthèse de heartbeat.

## Références CLAUDE.md respectées

- **Règle 3 : aucun secret hardcodé** — Pas applicable, aucun secret ajouté.
- **Règle 5 : stdout/stderr capturés** — stdout/stderr du sous-processus Claude restent capturés comme avant ; les logs internes du watcher (loguru) ne sont pas impactés.
- **Règle 6 : convention horaire UTC** — Pas applicable, aucune modification des slots ou timezones.
- **Règle 7 : auto-scheduler dans main_loop** — Pas applicable, aucune modification du scheduler.
- **Règle 8 : mise à jour de docs/strategie.html** — Ce changement ne modifie aucune formule de phase (0, 3, 4, 5) ni aucun réglage stratégique (`config.json`), donc `docs/strategie.html` reste à jour.

## Vérifications

- **530 tests passent** (520 sur `main` + 10 nouveaux)
- **ruff : 108 erreurs**, identique à baseline — aucune ajoutée
- Délégation maker neutralisée dans les tests → **3 tests ajoutés tombent** (tests du chemin maker lui-même, qui nécessitent `maker_exit_enabled=True`)
- Couverture de cas limites : position déjà en chasse, stop déjà annulé, solde insuffisant, échec de pose de limite

## Limitation connue

`exit_maker_or_taker` (classement sortie MAKER vs TAKER) est écrit par le watcher mais **n'est publié ni par Phase 7 ni par le dashboard**. Une fois cette PR mergée, les ventes en maker seront silencieuses sur ce champ jusqu'à mise à jour des points de publication. Prévu en PR de suivi.
