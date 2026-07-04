# PR #344 — Recalibrage TP automatique en Phase 0

> **Mergée le** : 2026-07-04
> **Branche** : `feat/issue-343-phase0-calibrate-tp`
> **Issues** : #343

## Contexte

La Phase 0 du cycle de trading doit maintenant calibrer intelligemment les take-profit (TP) en intégrant les niveaux de résistance TradingView. Précédemment, les TPs étaient figés ou recalculés heuristiquement (Phase 4 + `/calibrage`), mais en Phase 0 il n'y avait aucune synchronisation. Cette PR ajoute un recalibrage automatique en Phase 0 pour s'assurer que chaque position ouverte a un TP optimal calculé comme `tp_smart = min(tp_mécanique, R2 × 0.98)`, où R2 est le deuxième niveau de résistance TradingView (4h).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/phases/phase0_snapshot.txt` | Ajout de section | Insertion du bloc « RECALIBRAGE TP » entre trailing stop et réalisation de profits |
| `prompts/phases/phase0_calibrate_tp.txt` | Nouveau fichier | Template Python pour persister les TPs recalibrés dans `trade_history.json` |

### Détail des modifications

**`prompts/phases/phase0_snapshot.txt`** (lignes 59–94) :
- **Nouvelle section** : `# --- RECALIBRAGE TP (Smart TP automatique) ---`
- Pour chaque position ouverte, appel MCP `mcp__tradingview__combined_analysis()` 4h BINANCE
- Calcul `tp_smart = min(tp_mécanique, R2 × 0.98)` si R2 > entry_price
- Fallback silencieux sur TP mécanique si MCP échoue ou R2 indisponible
- Seuil de 0.5% pour accepter le recalibrage (évite les petits changements)
- Génération dict `updates` avec ancien/nouveau TP + nom de coin
- Injection du template `phase0_calibrate_tp.txt` et exécution du script Python via `exec()`
- Notification Telegram par coin recalibré (gérée dans le template)

**`prompts/phases/phase0_calibrate_tp.txt`** (nouveau) :
- Template Python généré dynamiquement dans le sous-processus Claude
- Remplace `__UPDATES__` par le dict d'updates calculé
- Remplace `__PROJECT_DIR__` par le chemin absolu du projet
- Charge `trade_history.json`, met à jour les TPs ouverts correspondants
- Sauvegarde atomique via `_save_trade_history_atomic()`
- Envoie une notification Telegram par coin modifié
- Affiche le résumé `PHASE0_CALIBRATE_TP_DONE|updated=N` sur stdout

### Logique de calcul

```python
# Pseudo-code du recalibrage
for trade in open_trades:
    entry = float(trade["entry_price"])
    stop = float(trade["stop_price"])
    tp_current = float(trade["tp_price"])
    
    # Vérification intégrité
    if entry <= 0 or stop <= 0 or tp_current <= 0 or stop >= entry:
        continue
    
    # Appel TradingView
    try:
        result = mcp__tradingview__combined_analysis(
            symbol=f"{coin}USDT",
            exchange="BINANCE",
            timeframe="4h"
        )
        r2_4h = result["technical"]["support_resistance"]["resistance_2"]
    except:
        continue  # Fallback silencieux
    
    # Calcul TP intelligent
    stop_distance_pct = (entry - stop) / entry
    tp_mecanique = entry * (1 + stop_distance_pct * reward_risk_ratio)
    
    if r2_4h and float(r2_4h) > entry:
        tp_smart = min(tp_mecanique, float(r2_4h) * 0.98)
    else:
        tp_smart = tp_mecanique
    
    # Seuil de 0.5% avant mise à jour
    if abs(tp_smart - tp_current) / tp_current > 0.005:
        updates[trade_id] = {
            "old_tp": tp_current,
            "new_tp": tp_smart,
            "coin": coin
        }
```

## Décisions techniques notables

- **MCP TradingView à chaque cycle** : chaque position ouverte bénéficie du calcul R2 frais en Phase 0, synchronisant les TPs intelligents avec le marché en temps quasi-réel
- **Fallback silencieux** : si MCP échoue (timeout, erreur API), le TP existant est conservé — aucun risque de sortie prématurée ou dégradation
- **Seuil de 0.5%** : évite les microchangements (volatilité intra-jour) qui satureraient les notifications Telegram et compliquent le debug
- **Notification par coin** : chaque mise à jour TP génère un message Telegram, traçabilité maximale
- **Mapping TV** : pièges Kraken gérés (XBT→BTC, XDG→DOGE) via dict `TV_MAP` local au script
- **Pas d'impact sur SL** : le recalibrage ne touche jamais `stop_price` — responsabilité exclusive du trailing stop de Phase 0

## Impact sur l'architecture

**Aucun impact architectural.** Ajout isolé en Phase 0 :
- **Phase 0** gère maintenant 3 tâches : protection_failed (OCO retry) + trailing stop (SL) + **recalibrage TP (nouveau)**
- **Phase 4** et **`/calibrage`** restent autorité sur le TP pour le cycle suivant (logique MCP identique)
- **Boucle de synchronisation** : Phase 0 (synchrone) ↔ Phase 4/`/calibrage` (cyclique) → TPs tous les 4h + sur demande utilisateur
- Aucune modification Python (`.py`) — uniquement les templates (`.txt`)

## Références CLAUDE.md respectées

- **Règle 5 — Modifications chirurgicales** : ajout ciblé (2 fichiers template), aucune modification de scripts existants
- **Règle 1 — Substitutions de template** : `__UPDATES__`, `__PROJECT_DIR__` injectés par Claude au runtime
- **Règle 4 — Telegram via curl** : notification gérée par le helper `tg()` importé depuis `core/trade_helpers.py` (curl-based)
- **Règle 2 — Absence de dépendances** : MCP TradingView déjà utilisé en Phases 2/4, aucun ajout
- **Règle 5 — Fallback silencieux** : exception swallowée en bloc try/except, TP existant préservé

## Test plan

- [ ] Vérifier présence section `# --- RECALIBRAGE TP ---` entre trailing stop et réalisation de profits
- [ ] Vérifier `TV_MAP = {"XBT": "BTC", "XDG": "DOGE"}` présent
- [ ] Vérifier fallback silencieux `except: continue` en place
- [ ] Vérifier template `phase0_calibrate_tp.txt` importe `tg`, `_save_trade_history_atomic` de `core.trade_helpers`
- [ ] Vérifier deux placeholders `__UPDATES__` et `__PROJECT_DIR__` dans le template
- [ ] Vérifier message stdout `PHASE0_CALIBRATE_TP_DONE|updated=N`
- [ ] Test manuel : `/trade` manual et vérifier notification Telegram si au moins 1 TP changé
