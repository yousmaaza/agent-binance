# PR #263 — [BUG] position_prompt.txt : mauvaises commandes binance-cli et mauvais noms de champs

> **Mergée le** : 2026-06-28
> **Branche** : `feat/issue-261-fix-position-prompt-binance-cli`
> **Issues** : #261

## Contexte

Le prompt de gestion des positions ouvertes (`prompts/position_prompt.txt`, créé en PR #256/#241) contenait plusieurs bugs d'incompatibilité avec :
1. Les commandes réelles `binance-cli` (syntaxe et arguments incorrects)
2. La structure réelle de `state/trade_history.json` (noms de champs mal nommés)

Ces bugs empêchaient l'exécution correcte de la commande `/calibrage` (déclenchement manuel du cycle position) et de l'intégration automatique du calibrage en Phase 0 du trade workflow.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/position_prompt.txt` | Création (fichier ajouté) | Correction des appels binance-cli et noms de champs trade_history pour que le cycle position soit exécutable |

### Correctifs appliqués

#### 1. Commandes binance-cli corrigées

| Ancien | Nouveau | Raison |
|---|---|---|
| `binance("open-orders", ...)` | `binance("spot", "get-open-orders", ...)` | Syntaxe correcte pour la commande spot GET open-orders |
| `binance("get-price", "--symbol", ...)` | `binance("spot", "ticker-price", "--symbol", ...)` | Syntaxe correcte pour récupérer le prix actuel (get-price n'existe pas) |

#### 2. Noms de champs trade_history.json corrigés

| Ancien | Nouveau | Raison |
|---|---|---|
| `status == "OPEN"` (majuscule) | `status == "open"` (minuscule) | trade_history.json utilise `"open"` en minuscule |
| `pos["symbol"]` | `pos["coin"]` | Le champ réel dans trade_history est `"coin"`, pas `"symbol"` |
| `pos.get("qty", 0)` | `pos.get("quantity", 0)` | Le champ réel est `"quantity"` |
| `pos.get("entry_time", "")` | `pos.get("date", "")` | Le champ réel est `"date"` (ISO 8601 avec Z) |

**Note** : Les lignes affectées dans le fichier :
- Ligne 34 : filtre champs ouvertes `status == "open"`
- Ligne 43 : accès au coin `pos["coin"]`
- Ligne 47 : commande get-open-orders
- Ligne 64 : commande ticker-price
- Ligne 87, 179 : champ `quantity`
- Ligne 88 : champ `date`

## Décisions techniques notables

- **Pas de nouvelles abstractions** : les correctifs sont minimaux et ciblés, sans refactoring du prompt lui-même. Les bugs étaient des incompatibilités factuelles avec les APIs (binance-cli) et la schéma de données (trade_history.json).
- **Respect de la structure existante** : le prompt continue d'itérer sur `trade_history` en lecture directe (pas de filtres additionnels) et utilise la fonction helper `binance()` pour tous les appels CLI.
- **Cohérence avec CLAUDE.md § Règle 4** : les appels Telegram restent via `tg()` (pas d'ajout de curl direct), et les appels binance-cli restent via le helper sans subprocess direct.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. Le fichier `prompts/position_prompt.txt` est un prompt injecté dans le sous-processus Claude (comme `prompts/trade_prompt.txt`). Les corrections rendent le prompt exécutable en Phase 0 du trade workflow et via la commande `/calibrage`, sans modification du flux de données ni des composants existants.

## Références CLAUDE.md respectées

- **Règle 4 — Appels Telegram via curl uniquement** : le prompt utilise `tg()` helper existant pour toutes les notifications
- **Minimalisme** : 8 additions / 8 suppressions (changements chirurgicaux uniquement, pas de restructuration)
- **Modifications non négociables § 3** : aucune modification de code applicatif, uniquement du contenu du prompt qui est un fichier de données
