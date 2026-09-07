# PR #483 — [BUG] Résoudre les codes d'actifs Kraken préfixés dans la vente sur signal

> **Mergée le** : 2026-09-07
> **Branche** : `fix/issue-476-kraken-asset-codes-clean`
> **Issues** : #476

## Contexte

Kraken expose certains actifs historiques sous des codes préfixés (`XETH` au lieu de `ETH`, `XXBT` au lieu de `XBT`, etc.) dans la réponse `kraken balance`. Le code de vente sur signal (Phase 3) lisait directement `balance.get(coin, 0)`, ce qui retournait toujours 0 pour ces 4 actifs majeurs (ETH, XRP, XBT, DOGE), résultant en `sell_qty = 0` et l'absence complète de ventes sur signal pour ces coins. Bug actif en production depuis 2026-09-06.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/trade_helpers.py` | Ajout | Ajout du helper `kraken_coin_balance()` et de la table `KRAKEN_ASSET_ALIASES` — seul endroit qui définit cette correspondance |
| `binance-bot/core/phases/phase3_signal_sell.py` | Modification | Utilisation du helper pour résoudre le solde réel ; distinction entre alias manquant (défaut de code) et panne Kraken (aléa réseau) |
| `tests/fixtures/fake_kraken.py` | Amélioration | Support de `"balance_fail": true` pour simuler une panne réelle de l'API Kraken |
| `tests/test_phase3_signal_sell.py` | Extension | 6 nouveaux tests validant les comportements avec les vrais codes Kraken préfixés et non-préfixés |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `kraken_coin_balance(balance: dict, coin: str) -> float` | Ajoutée | Résout le solde d'un coin en essayant la clé brute, puis l'alias Kraken connu. Lève `KeyError` si aucune n'existe — jamais retourner 0 pour un actif absent du solde (distinction critique #476). |
| `KRAKEN_ASSET_ALIASES` | Ajoutée | Dict fermé de 13 actifs historiques préfixés constatés via `kraken assets -o json` : ETC, ETH, LTC, MLN, REP, XBT/BTC, XDG/DOGE, XLM, XMR, XRP, ZEC. |
| `phase3_signal_sell.py:Step 2` | Modifiée | Utilise `kraken_coin_balance()` au lieu de `balance.get(coin, 0)`. Distingue explicitement : alias manquant (alerte Telegram + repli sur `trade_qty`) vs. panne Kraken (repli sur `trade_qty` sans alerte). |

## Décisions techniques notables

- **Table fermée, pas de règle générale** : Kraken ne documente pas sa politique de préfixage (SOL, ADA, LINK, BNB, TRUMP n'ont pas de préfixe). La table provient d'une observation expérimentale en production, pas d'une déduction. Tout nouvel actif manquant sera visible via l'alerte "alias manquant" et pourra être ajouté à la table.

- **Distinction alias manquant vs. panne réseau** : Le traitement des exceptions après annulation du stop (Step 1) reste volontairement large (`except Exception`, jamais un sous-ensemble précis). Sur ce chemin, une position sans stop exposée à une exception non rattrapée serait laissée nue. Exception sur la résolution du solde (Step 2) : `KeyError` signale un alias manquant (défaut de code, alerte Telegram explicite) ; tout autre exception (`IOError`, `json.JSONDecodeError`) signale une panne réseau (repli silencieux). Le bug initial était confondu avec un solde nul, ce qui est incorrect.

- **Pas de prix fabriqué (#469)** : Si le fill ne se confirme pas après 3 tentatives, ou si la vente échoue, la position est reprotégée et n'est jamais clôturée — jamais d'invention de prix de sortie qui contredisait l'historique réel.

- **Mesure du reliquat contre `trade_qty`, pas `sell_qty`** : `sell_qty` est déjà plafonné par le solde réel et le pas de la paire. Mesurer le reliquat d'un remplissage partiel contre `sell_qty` au lieu de `trade_qty` masque la partie de la position exclue par ce plafonnement. Utiliser `trade_qty` garantit qu'un remplissage significatif est reconnu correctement et que la position n'est pas clôturée sur une quantité jamais vendue.

## Impact sur l'architecture

Changement isolé, pas d'impact sur l'architecture globale. Le flux d'exécution Phase 3 reste inchangé :
1. Annuler le stop
2. Lire le solde réel (nouveau : résoudre les aliases)
3. Vendre au marché
4. Requêter le fill (avec reprotection en cas d'échec)
5. Enregistrer le PnL si réellement clôturé

La reprotection suite à un échec de vente s'appuie sur l'existant `_repose_stop_and_alert()` (core/maker_exit_watcher.py) — aucune nouvelle dépendance.

## Références CLAUDE.md respectées

- **Minimalisme** : Aucune feature spéculative, aucune abstraction pour un usage unique. Le helper est simple et ciblé.
- **Modifications chirurgicales** : Seul le chemin de vente sur signal est touché. L'historique des trades et les autres phases restent inchangées.
- **Commentaires explicites** : Ajout de commentaires détaillés aux endroits critiques (Step 1 : position sans stop ; Step 2 : distinction alias manquant vs panne réseau ; Step 3 : typage large volontaire pour éviter les positions nues).
- **Gestion d'erreur minimale** : Les erreurs captées sont uniquement celles qui ont un impact direct sur la protection de la position. Le typage volontairement large des exceptions après l'annulation du stop reflète la priorité : jamais de position sans stop.
- **Tests exhaustifs** : 6 nouveaux tests validant tous les cas critiques (prefix et non-prefix, solde nul, alias manquant, panne réseau, timeout de subprocess, remplissage partiel).

## Notes

- PR #477 (fermée) contenait cette correction mais avait accumulé 5 commits automatisés étrangers au ticket. Cette PR repart proprement depuis `main` avec uniquement le correctif #476.
- Les anciens tests utilisaient des clés simplifiées (`"ETH": "1.0"` au lieu de `"XETH": "1.0"`) qui masquaient complètement le bug. Les nouveaux tests utilisent les vrais codes Kraken pour valider la fix.
- L'alerte "alias manquant" permet un monitoring futur : si un actif préfixé est régulièrement not-found, c'est un signal que la table `KRAKEN_ASSET_ALIASES` est incomplète et peut être enrichie.
