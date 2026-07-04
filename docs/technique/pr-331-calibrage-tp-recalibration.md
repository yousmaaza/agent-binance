# PR #331 — `/calibrage` recalcule les TP via combined_analysis

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-330-calibrage-tp-recalibration`
> **Issues** : #330, #331, #332, #333, #334, #337, #336

## Contexte

La commande `/calibrage` est invoquée pour mettre à jour les take-profit (TP) des positions ouvertes en fonction des résistances TradingView détectées en 4h. Cette PR introduit un **bloc de recalibrage TP intelligent** qui repose sur les résistances de marché (`resistance_2`) plutôt que sur le calcul mécanique seul.

La tâche 3 (Recalibrage TP) s'exécute maintenant **avant** l'évaluation des positions (tâche 4), permettant de recalibrer les TP intelligemment avant de décider des ventes.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/position_prompt.txt` | Modification majeure | Ajout bloc "Recalibrage TP" (tâche 3) + renumérotation tâches 3→4, 4→5, 5→6 |
| `binance-bot/core/phases/phase4_sizing.py` | Modification mineure | Ajout commentaire explicite sur `reward_risk_ratio` (config.json, default 2) |
| `tests/test_reward_risk_ratio_default.py` | Ajout test unitaire | Validation que l'absence de `reward_risk_ratio` en config utilise le default 2.0 |
| `docs/test-stabilite-tp-337.md` | Documentation test | Plan de test pour stabilité du seuil 0.5% d'oscillation TP |

### Fonctions ajoutées / modifiées

| Fonction / Section | Action | Description |
|---|---|---|
| **Tâche 3 — Recalibrage TP** | Nouvelle section | Dans `position_prompt.txt`, appelle MCP `combined_analysis()` en 4h sur symbole TradingView, récupère R2, calcule `tp_smart = min(tp_mecanique, r2_4h × 0.98)`, met à jour `tp_price` si écart > 0.5% |
| `TV_MAP` | Ajout | Dictionnaire de translation symboles : `{"XBT": "BTC", "XDG": "DOGE"}` pour normaliser appels TradingView |
| `_save_trade_history_atomic()` | Appel ajouté | Si au moins un TP recalibré, sauvegarde atomique du fichier `trade_history.json` |
| `stop_distance_pct` assertion | Ajout validation | `assert stop_price < entry_price` pour valider calcul TP sur positions long uniquement |

## Décisions techniques notables

1. **Recalibrage AVANT évaluation** : La tâche 3 s'exécute avant la tâche 4 (Évaluation). Cela permet de mettre à jour les TP intelligemment avant de décider si une position doit être vendue, évitant les ventes prématurées si le TP est recalibré à la hausse.

2. **Formule TP intelligent** : `tp_smart = min(tp_mecanique, r2_4h × 0.98)`. On prend le minimum des deux pour éviter un TP trop agressif si R2 est extrêmement élevé. Le facteur 0.98 laisse une marge de 2% par rapport à la résistance exacte.

3. **Seuil de recalibrage 0.5%** : Un TP n'est mis à jour que si l'écart absolu `| tp_smart - tp_actuel | / tp_actuel > 0.005` pour éviter les oscillations de recalibrage à chaque cycle sur des variations mineures.

4. **TV_MAP pour normalisation symboles** : Les symboles internes (`XBT`, `XDG`) doivent être traduits en symboles TradingView standard (`BTC`, `DOGE`) pour les appels MCP.

5. **Robustesse long-only** : Assertion explicite que le calcul `stop_distance_pct` suppose des positions long (`stop < entry`). Une short position produirait un `stop_distance_pct` négatif et un TP invalide — cette PR documente la contrainte sans la modifier (les shorts ne sont pas en scope).

6. **Format prix 0.6f** : Remplacement de `.4g` par `.6f` pour l'affichage des prix R2 et TP dans les notifications Telegram. Cela évite la notation scientifique pour les très petites valeurs (< 0.0001) et améliore la lisibilité.

7. **reward_risk_ratio par défaut** : Le paramètre `reward_risk_ratio` est désormais explicitement documenté comme "chargé depuis config.json, défaut 2". Cela clarifie que le rapport TP/SL est configurable et non hardcodé.

## Impact sur l'architecture

### Flux de cycle `/calibrage`

Le cycle position (commande `/calibrage` ou déclenchement par tâche horaire) change ainsi :

```
Avant (Phase 0)          →         Après (Phase 0)
├── Tâche 1 : Charge config      ├── Tâche 1 : Charge config
├── Tâche 2 : Récupère ordres    ├── Tâche 2 : Récupère ordres
├── Tâche 3 : Évalue positions   ├── Tâche 3 : Recalibrage TP ← NOUVEAU
├── Tâche 4 : Exécute ventes     ├── Tâche 4 : Évalue positions
└── Tâche 5 : Résumé             ├── Tâche 5 : Exécute ventes
                                  └── Tâche 6 : Résumé
```

### Intégration MCP

L'appel MCP `combined_analysis(symbol, exchange, timeframe)` injecte une dépendance vers les outils TradingView pour chaque recalibrage TP. Si l'appel échoue (réseau, quota), la boucle passe silencieusement au coin suivant et les TP restent inchangés — **pas de blocage du cycle**.

### Persistance

Avant : `tp_price` était immutable après création de la position.
Après : `tp_price` peut être mis à jour via `/calibrage` et recalibré intelligemment. Les changements sont persistés atomiquement dans `trade_history.json`.

## Références CLAUDE.md respectées

- **Secrets via .env** : Les tokens Telegram et symboles externes (TradingView) sont injectés via variables substituées (`__BOT_TOKEN__`, `__PROJECT_DIR__`), jamais hardcodés.
- **Appels MCP au lieu de skills** : L'appel `mcp__tradingview__combined_analysis()` est un outil MCP, pas une skill Claude Code. Il respecte la contrainte "Interdit" du prompt qui interdit les invocations de skills.
- **Pas de modification CLAUDE.md** : Cette PR ne modifie pas les contraintes — elle enrichit la logique sans violer les règles existantes.
- **Helpers partagés via imports** : Les fonctions `tg()`, `_load_config()`, `_save_trade_history_atomic()` sont importées depuis `core/position_helpers.py`, conformément au pattern modularisé.
- **Atomicité persistance** : Utilisation de `_save_trade_history_atomic()` pour éviter les corruption de fichier en cas de crash mid-write.

## Notes

- **Seul changement applicatif** : le bloc Tâche 3 dans `position_prompt.txt` (texte, pas Python direct).
- **Pas de dépendance nouvelle** : La PR n'ajoute pas de packages (MCP est déjà disponible via `.mcp.json`).
- **Renumérotation compatible** : Les anciennes tâches 3, 4, 5 deviennent 4, 5, 6 — les références dans la doc et les logs sont à jour.
- **Test de stabilité** : Le plan `docs/test-stabilite-tp-337.md` documente comment valider que le seuil 0.5% ne génère pas d'oscillations sur cycles consécutifs.

## Vérification PR

✅ Changement isolé au cycle position (`/calibrage`), pas d'impact sur cycle trade (`/trade`)
✅ MCP appelé avec gestion d'erreur (continue si fail)
✅ Tests unitaires pour `reward_risk_ratio` default
✅ Documentation du plan de stabilité TP 0.5%
✅ Atomicité persistance garantie
