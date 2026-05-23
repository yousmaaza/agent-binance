# PR #91 — Commande /eval : rapport performance + coût abonnement vs API

> **Mergée le** : 2026-05-23
> **Branche** : `feat/issue-90-eval-command`
> **Issues** : #90

## Contexte

Ajout d'une nouvelle commande `/eval` pour offrir à l'utilisateur un rapport synthétique hebdomadaire combinant trois axes : fiabilité opérationnelle (cycles complétés vs erreurs), performance commerciale (win rate, PnL, ratio gain/perte), et coût réel en tenant compte du mode de facturation abonnement vs API fallback. Cette commande devient la version "simplifiée" du dashboard et facilite l'analyse du ROI de la stratégie.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/commands/eval.py` | Ajoutée | Nouvelle commande de rapport synthétique (138 lignes) |
| `binance-bot/cli.py` | Modification | Import + subcommand `eval --days N` (5 lignes) |
| `binance-bot/orchestration/runner.py` | Modification | Suivi du mode de facturation (abonnement\|api) en MongoDB (12 lignes) |
| `binance-bot/webhook_server.py` | Modification | Dispatch `/eval` + mise à jour du message d'aide (8 ajouts, 2 suppressions) |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `run_eval(period_days: int)` | Ajoutée | Orchestre la génération du rapport : sections fiabilité, performance, coût, risque |
| `_trades_section(cutoff)` | Ajoutée | Analyse trade_history.json : win rate, PnL net, ratio gain/perte |
| `_cycles_and_cost_section(cutoff, period_days)` | Ajoutée | Interroge MongoDB cycles : taux de complétude, coût abonnement proratisé vs surcoût API réel |
| `_risk_section()` | Ajoutée | Comptabilise les positions ouvertes sans stop-loss (protection_failed) |
| `_stat_note(n_closed, period_days)` | Ajoutée | Avertissement si < 30 trades sur la période (échantillon trop petit) |
| `_parse_dt(s: str)` | Ajoutée | Utilitaire : parse ISO datetime avec fallback UTC |
| `_update_billing_mode_in_mongo()` | Ajoutée (runner.py) | Enregistre le mode de facturation (abonnement\|api) après chaque cycle |

## Décisions techniques notables

- **Facturation binaire abonnement | api** : chaque cycle est marqué avec son mode en MongoDB. Le fallback API (déjà présent en PR #50) définit le mode comme "api", sinon "abonnement" par défaut. Ceci permet aux analyses ultérieures de différencier les coûts réels.
  
- **Trade history JSON + MongoDB** : le rapport utilise deux sources : `trade_history.json` (source locale, fiable) pour les stats commerciales (win rate, PnL) et MongoDB (si disponible) pour l'historique des cycles (fiabilité, coût API). Si Mongo est absent, le rapport fonctionne partiellement mais sans historique fiabilité/coût.

- **Période configurable (--days)** : par défaut 7 jours. Permet à l'utilisateur de tirer des rapports sur 14j, 30j, etc., sans code applicatif.

- **Format HTML Telegram** : le rapport utilise `<b>`, `<i>`, `<code>` et emojis (📊 🔄 📈 💳 🛡️) pour une lisibilité Telegram. Pas de dépendance externe pour le formatage.

- **Gestion des absences gracieuse** : MongoDB absent → sections fiabilité/coût vides, pas d'erreur. trade_history.json absent → histoire vide mais pas de crash. Ceci maintient le bot opérationnel même en mode dégradé.

## Impact sur l'architecture

- **Nouvelle commande Telegram** : `/eval` entre dans le même flux que `/perf`, `/status`, etc. Elle ne modifie pas le dispatcher ni l'auto-scheduler.
  
- **Nouveau champ MongoDB** : `billing_mode` ("abonnement" | "api") est désormais écrit à la fin de chaque cycle dans la collection `cycles`. Ceci enrichit le document de cycle sans impact rétroactif (cycles anciens resteront sans ce champ, les requêtes utilisent `.get("billing_mode", "abonnement")` pour le défaut).

- **Changement isolé** : la PR n'impacte pas les phases du cycle, le flux d'exécution, ni le scheduler. C'est une pure augmentation du périmètre "reporting" sans couplage au core trading.

## Références CLAUDE.md respectées

- **Règle 2 (secrets via .env)** : Aucun secret ne vient du code. Les données proviennent de MongoDB (connectable via `MONGODB_URI` du `.env` déjà présent) et de `trade_history.json`.
  
- **Règle 5 (UTC interne)** : `run_eval()` accepte `period_days` (jours naturels) mais utilise `datetime.now(timezone.utc) - timedelta(days=...)` pour découper les cycles et trades. Les filtres MongoDB et la comparaison des dates utilisent ISO format UTC.

- **Règle 3 (PROJECT_DIR dynamique)** : `eval.py` importe `PROJECT_DIR` depuis `core.env` (pas hardcodé). La lecture de `trade_history.json` utilise `f"{PROJECT_DIR}/state/trade_history.json"`.

- **Pas de dépendances lourdes** : le calcul des stats (win rate, ratio gain/perte, PnL) se fait en Python natif (pas scipy, pandas).

## Code clé

**Dispatch dans webhook_server.py** (ligne 112–116) :
```python
elif text.startswith("/eval"):
    threading.Thread(
        target=lambda: send_telegram(run_eval(), parse_mode="HTML"),
        daemon=True,
    ).start()
```

**Enregistrement du mode facturation dans runner.py** (ligne 91) :
```python
_update_billing_mode_in_mongo(cycle_id, "api" if fallback_used else "abonnement", cycle_log)
```

**Récap rapport** :
- Section 1 (Fiabilité) : nombre cycles total / OK / erreurs, taux complétude
- Section 2 (Performance) : win rate, gains/pertes moyens, ratio G/P, PnL net, positions ouvertes
- Section 3 (Coût) : abonnement proratisé sur la période + surcoût API réel
- Section 4 (Risque) : positions sans stop-loss
- Section 5 (Note) : avertissement si < 30 trades (échantillon petit)
