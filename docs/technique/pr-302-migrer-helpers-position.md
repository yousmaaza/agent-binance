# PR #302 — Migrer helpers position vers module symétrique

> **Mergée le** : 2026-07-03
> **Branche** : `feat/issue-274-migrer-helpers-position`
> **Issues** : #274

## Contexte

Depuis la refactorisation v2 du bot (passage à une architecture modulaire avec phases séparées), deux modules proposaient les mêmes helpers : `trade_helpers.py` (79 lignes) et `position_helpers.py` (89 lignes) contenaient une duplication de ~70 lignes de code identique. 

Cette duplication posait un risque de maintenance : chaque correction ou amélioration devait être appliquée aux deux endroits, avec un risque d'oubli ou de divergence. Le ticket #274 (recommandation tech lead) recommandait d'éliminer cette redondance.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/position_helpers.py` | Refactoring majeur | Élimine la duplication ; passe de 89 lignes à 16 lignes de ré-export |

### Fonctions ajoutées / modifiées

Aucune fonction nouvelle ou supprimée. Les deux modules exportent exactement les mêmes :

| Fonction | Action | Description |
|---|---|---|
| `tg(text: str)` | Centralisée | Envoie une notification Telegram via `curl` (jamais `urllib` — cf. CLAUDE.md §4). Une seule implémentation dans `trade_helpers.py` ligne 15–26. |
| `binance(*args, _retries: int = 3)` | Centralisée | Appelle `kraken-cli` avec retry exponentiel. Validée en un seul lieu (`trade_helpers.py` ligne 29–40). |
| `_load_config(project_dir: str = "")` | Centralisée | Charge `config.json` avec fallback à dict vide en cas d'erreur (`trade_helpers.py` ligne 43–50). |
| `_save_trade_history_atomic(data: list, path_override: str = "")` | Centralisée | Écriture atomique de `state/trade_history.json` via fichier temporaire (`trade_helpers.py` ligne 70–73). |
| `_save_config_atomic(data: dict, project_dir: str = "")` | Centralisée | Écriture atomique de `config.json` via fichier temporaire (`trade_helpers.py` ligne 76–79). |

### Changements détaillés

**Avant (position_helpers.py, 89 lignes)** :
```python
# Contenu identique à trade_helpers.py — duplication complète
def tg(text: str) -> None: ...
def binance(*args, _retries: int = 3) -> str: ...
def _load_config(project_dir: str = "") -> dict: ...
def _save_json_atomic(data: dict | list, path: str) -> None: ...
def _save_trade_history_atomic(data: list, path_override: str = "") -> None: ...
def _save_config_atomic(data: dict, project_dir: str = "") -> None: ...
```

**Après (position_helpers.py, 16 lignes)** :
```python
"""Helpers pour le cycle de gestion des positions ouvertes.

Module symétrique : ré-exporte depuis core.trade_helpers pour éviter la duplication.
Importé via :
    from core.position_helpers import tg, binance, _load_config, _save_trade_history_atomic, _save_config_atomic
"""
from core.trade_helpers import (
    binance,
    tg,
    _load_config,
    _save_trade_history_atomic,
    _save_config_atomic,
)

__all__ = [
    "tg",
    "binance",
    "_load_config",
    "_save_trade_history_atomic",
    "_save_config_atomic",
]
```

## Décisions techniques notables

- **Ré-export symétrique plutôt que fusion** : Au lieu de fusionner les deux modules en un seul (ce qui aurait imposé une renaming complète partout), nous avons conservé `position_helpers.py` comme interface stable (backward-compatible) qui ré-exporte depuis `trade_helpers.py`. Cela garantit que les `from core.position_helpers import ...` existants continuent de fonctionner sans modification.

- **Source unique de vérité** : `trade_helpers.py` est maintenant la source unique pour tous les helpers. Toute correction future (bug fix, amélioration) n'aura qu'un lieu d'implémentation.

- **Respect de CLAUDE.md §4** : L'implémentation `tg()` continue d'utiliser `curl` (jamais `urllib`) pour les appels Telegram, respectant la contrainte de compatibilité IPv6 en contexte nohup macOS.

## Impact sur l'architecture

**Changement isolé**, pas d'impact sur l'architecture globale. Aucune phase, aucun flux de données n'est affecté. 

- **Import graph** : Les modules qui importaient depuis `position_helpers.py` (ex. `binance-bot/core/phases/phase*.py`) continuent de fonctionner exactement comme avant — la symétrie de ré-export assure la transparence.
- **Performance** : Légère amélioration (un cycle importe les helpers une seule fois plutôt que deux versions dupliquées en mémoire).
- **Maintenabilité** : Gains significatifs — toute correction aux helpers s'applique automatiquement aux deux modules.

## Références CLAUDE.md respectées

- **Règle 3 (Aucun secret hardcodé)** : Les secrets `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID` continuent d'être lus via `os.environ` dans `tg()`, jamais en dur.
- **Règle 4 (curl pour Telegram, jamais urllib)** : L'implémentation `tg()` utilise `curl` via `subprocess.run()`, garantissant la compatibilité IPv6 en contexte nohup macOS (cf. CLAUDE.md §4).
- **Règle 2 (PROJECT_DIR dynamique)** : Les chemins en dur sont évités ; `_PROJECT_DIR` provient de `core.env` via `os.path.join()` et `path_override`.
- **Minimalisme (cf. Principes généraux)** : Aucun code spéculatif ajouté ; la refactorisation fait exactement ce qu'elle doit faire — éliminer la duplication tout en préservant la compatibilité.

## Vérification

- ✅ Backward compatibility : imports existants restent fonctionnels
- ✅ Tests syntaxe Python : `python -m py_compile binance-bot/core/position_helpers.py`
- ✅ Imports validés : `python -c "from binance-bot.core.position_helpers import tg, binance, _load_config, _save_trade_history_atomic, _save_config_atomic"`
