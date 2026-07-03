# PR #310 — Mettre à jour config.json pour Kraken

> **Mergée le** : 2026-07-03  
> **Branche** : `feat/issue-291-kraken-config`  
> **Issues** : #291

## Contexte

Migration du bot de **Binance** vers **Kraken** comme source de liquidité pour les ordres spot. Le fichier `config.json` devait être adapté pour refléter les paires USDC réellement disponibles sur Kraken et la structure de gestion des credentials (globale, pas par profil).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Modification | Suppression de `binance_profile`, mise à jour de `portfolio_coins` vers les coins Kraken supportés |

### Configuration clé

**Avant** (implicite Binance) :
- `binance_profile` : clé présente pour spécifier le profil Binance CLI
- `portfolio_coins` : `["BTC", "STX", "SUI", "XRP", "SOL"]` (exemple)

**Après** (Kraken) :
- `portfolio_coins` : `["XBT", "XRP", "SOL"]` — coins disponibles en paires USDC sur Kraken
  - `XBT` (au lieu de `BTC`) construit la paire `XBTUSDC` attendue par Kraken
  - `XRP` et `SOL` conservés (paires `XRPUSDC` et `SOLUSDC` disponibles)
  - `STX` et `SUI` retirés (paires USDC introuvables sur Kraken)
- `binance_profile` : **supprimée** — Kraken utilise une authentification globale via `kraken setup` (pas de profil par commande)

## Décisions techniques notables

- **XBT vs BTC** : Kraken utilise historiquement le ticker `XBT` pour Bitcoin (en conformité ISO 4217). Le code construit la paire avec `f"{coin}USDC"`, donc `XBT` donne `XBTUSDC` (correct pour Kraken), tandis que `BTC` aurait produit `BTCUSDC` (introuvable).
- **Credentials globales** : Kraken accepte une configuration unique via `kraken setup`, à l'inverse de Binance qui permettait des profils nommés. La clé `binance_profile` est donc inutile et supprimée pour éviter la confusion.

## Impact sur l'architecture

Changement isolé du fichier de configuration. Pas d'impact architectural — la logique de trading (`webhook_server.py`, phases) n'est pas modifiée. Les appels Kraken CLI utiliseront désormais l'authentification globale au lieu d'un profil spécifique.

**Détail** : le code qui construit les paires (ex : `f"{coin}USDC"`) était déjà compatible avec cette migration. Seule la liste `portfolio_coins` et la suppression de `binance_profile` étaient nécessaires pour que le bot utilise Kraken correctement.

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : `config.json` est à la racine et chargé par `webhook_server.py` via chemin dynamique — pas de hardcodage.
- **Règle 3 (secrets via `.env`)** : aucun secret ajouté à `config.json` ; les credentials Kraken restent en `.env` (`KRAKEN_API_KEY`, `KRAKEN_API_SECRET`).
- **Pas de code applicatif** : seule la configuration est modifiée, pas les scripts Python.

## Test de validation

La PR inclut un test inline pour valider :
```bash
python3 -c "import json; c=json.load(open('config.json')); \
  assert 'binance_profile' not in c; \
  assert c['portfolio_coins']==['XBT','XRP','SOL']; \
  print('OK')"
```

Résultat : ✅ `OK`
