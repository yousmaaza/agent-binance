# PR #257 — Inclure les OCO manuels Binance (open-orders)

> **Mergée le** : 2026-06-22
> **Branche** : `feat/issue-255-position-oco-manuels`
> **Issue** : #255

## Contexte

Le cycle horaire de gestion des positions (PR #241) évaluait seulement les positions bot créées par le bot lui-même (via `trade_history.json`). Les utilisateurs pouvaient ouvrir des ordres OCO manuels sur Binance pour compléter leur stratégie bot, mais le cycle position les ignorait complètement. Cette PR étend le cycle position pour récupérer, évaluer et gérer aussi les ordres OCO ouverts manuellement sur Binance.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/position_prompt.txt` | Modification | Fusion bot + ordres manuels, gestion OCO au profit |

### Fonctions ajoutées / modifiées

Le prompt n'expose pas de fonctions nommées mais des blocs Python exécutables. Les changements logiques clés :

| Logique | Action | Description |
|---|---|---|
| **Récupération ordres manuels** | Ajoutée (§2) | Appel `binance("spot", "open-orders", "--profile", "agent-profile")` pour récupérer tous les ordres OCO actifs de l'utilisateur |
| **Merge bot + manuels** | Ajoutée (§2) | Union ensembliste des coins bot et manuels pour une vision consolidée des positions |
| **Évaluation OCO manuels** | Ajoutée (§3) | Extraction du prix d'entrée depuis le BUY order d'une OCO, calcul P&L, décision de fermeture au profit |
| **Annulation OCO** | Ajoutée (§4) | Si un OCO manuel atteint le profit, annuler les ordres SELL (stop/take-profit) d'abord, puis vendre au marché |
| **Tracking source** | Ajoutée (§3-5) | Ajout d'un champ `source` ("bot" vs "manual") pour différencier les positions dans les rapports et résumés |

## Décisions techniques notables

- **Récupération via `binance-cli`** : Pas de parsing Binance API direct, delegation complète à `binance-cli spot open-orders` pour cohérence avec le reste du stack (cf. CLAUDE.md rule 4 — `curl` pour Telegram, `binance-cli` pour Binance).

- **Fetch prix pour tous les coins** : Boucle `for coin in all_coins` (union bot + manuels) pour récupérer les prix actuels. Pas de cache — chaque cycle requête les prix en live.

- **Condition `not pos_bot`** : Ligne 113 `if pos_manual and not pos_bot` pour éviter de gérer deux fois un coin qui existe dans les deux sources (priorité à la source bot).

- **Annulation partielle tolérée** : La section d'annulation OCO (§4, lignes 151-152) utilise `try/except pass` pour ne pas bloquer la vente si une annulation échoue (réseau, ordre déjà expiré, etc.).

- **Format de raison étendu** : Ajoute `(OCO manuel)` ou `(bot)` à la raison de chaque action pour tracer l'origine de la décision.

## Impact sur l'architecture

Le cycle position `run_position_check_workflow()` (lancé toutes les heures, voir PR #241) n'a pas changé structurellement — il réexécute `POSITION_PROMPT` qui reçoit les variables injectées identiques. La seule différence : le prompt injecte maintenant une logique plus riche pour fusionner deux sources de positions.

**Pas d'impact sur les autres composants** :
- Pas de modification du format `trade_history.json`
- Pas de modification du format Mongo `db.cycles`
- Pas d'appels MCP ou TradingView dans ce prompt
- Pas de nouveaux fichiers `state/`
- Pas d'impact sur les commandes Telegram (déjà existe `/position`, `/status`)

Changement isolé au prompt position, déjà isolé du trade cycle.

## Références CLAUDE.md respectées

- **Rule 4** (Tous les appels Telegram via curl) : Non applicable ici, pas d'appels Telegram dans le prompt.
- **Rule 4 bis** (Binance via `binance-cli` via helper `binance()`) : ✅ Ligne 47, `binance("spot", "open-orders", "--profile", "agent-profile")` et ligne 150 `binance("cancel-order", ...)` utilisent le helper.
- **Rule 6** (UTC interne, local à l'affichage) : Non applicable, pas d'affichage ou gestion horaire.
- **Minimalisme** : ✅ Pas de refactorisation, pas d'abstraction au-delà du besoin. Code en place, pas de helper Python nouveau.

---

**Impact utilisateur** : Les utilisateurs peuvent maintenant placer des ordres OCO manuels sur Binance et le bot les inclura dans son evaluation horaire des positions. Si une OCO manuelle atteint le profit configuré, le bot annulera la protection et vendra au marché automatiquement.
