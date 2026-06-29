# PR #268 — [M1] Réduire min_order_usdc de 11 à 9 USDC

> **Mergée le** : 2026-06-29
> **Branche** : `feat/issue-236-config-min-order-usdc`
> **Issues** : #236

## Contexte

Les 7 derniers cycles de trading ont généré 4 erreurs de type **TYPE_B** (ordres dimensionnés sous le seuil minimum acceptable). Après analyse, le dimensionnement ATR produit régulièrement des montants dans la plage 8–11 USDC, juste sous le seuil précédent de 11 USDC, ce qui forçait le bot à skipper des opportunités de trading valides.

L'issue #236 recommande un abaissement du seuil minimum à 9 USDC (conservateur) pour couvrir ces cas sans violer le minimum Binance de facto (~10 USDC strict, mais 9 USDC passe en pratique avec LIMIT + offset sur les paires majeures BTC/SOL/XRP). Le portefeuille reste stable avec un solde minimum de 25 USDC pour les marges.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Modification paramètre | Abaissement `min_order_usdc` : 11 → 9 USDC |

### Détail du changement

**Fichier** : `config.json`, ligne 8

```diff
- "min_order_usdc": 11,
+ "min_order_usdc": 9,
```

**Rôle du paramètre** : Seuil minimum du montant ordre (en USDC) imposé en Phase 4 (Sizing). Tout dimensionnement généré par l'ATR produisant un montant < `min_order_usdc` est rejeté avec `skip_type="TYPE_B"` et `skip_detail="Montant X USDC < seuil Y"`.

**Justification** :
- **Problème avant** : ATR sizing sur volatilité normale (BTC, SOL, XRP) produit 8–11 USDC ; avec seuil 11, ces coins valides étaient rejetés 4 fois/7j.
- **Avantage après** : Couvre les dimensionnements légitimes sans casser la contrainte Binance.
- **Stabilité maintenue** : Portfolio minimum 25 USDC conserve le rapport risk/reward ; `risk_per_trade_pct=0.02` (2%) inchangé.

## Décisions techniques notables

- **Valeur 9 plutôt que 10** : Donne une marge contre les frais de trading et la précision de calcul, tout en restant validable par Binance en pratique.
- **Pas de changement de stratégie** : C'est un ajustement de contrainte opérationnelle, non une modification du scoring ou du dimensionnement algorithmique.
- **Retrocompatibilité** : Aucune variable d'état affectée ; la modification est transparente au redémarrage.

## Impact sur l'architecture

**Changement isolé, pas d'impact architectural global.**

- Le flux de phases (0–8) reste identique.
- La classification TYPE_B en Phase 4 demeure inchangée ; seule la condition `montant < min_order_usdc` est affectée.
- Pas d'impact sur la persistance (MongoDB, `trade_history.json`), les handlers Telegram, ou les assistants externes (MCP TradingView, binance-cli).

**Impact opérationnel attendu** :
- Réduction du TYPE_B : cible 0–1 par 7 jours (au lieu de 4).
- Plus de coins tradables par cycle (montants légitimes ne seront plus filtrés).
- Solde USDC et P&L pas affectés (risque par trade inchangé).

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : `config.json` est chargé via `app.config.load()` qui construit les chemins dynamiquement, pas d'hardcode.
- **Règle 3 (Secrets via .env)** : `min_order_usdc` est un paramètre de stratégie publique dans `config.json`, non un secret.
- **Règle 4 (Minimalisme)** : Modification d'une seule ligne (un nombre), aucun code applicatif ajouté.

---

## Cas d'usage et scénarios

### Scenario 1 : Dimensionnement 9.5 USDC

**Avant PR #268** :
- Coin candidat XRP, volatilité normale, ATR sizing → 9.5 USDC.
- Condition Phase 4 : `9.5 < 11` → **skip TYPE_B**, perte d'opportunité.

**Après PR #268** :
- Même candidat, même dimensionnement 9.5 USDC.
- Condition Phase 4 : `9.5 < 9` → FAUX → **ordre placé**.
- P&L futur : contribue au portefeuille, réalisation de profit ou perte sur ce coin.

### Scenario 2 : ATR très faible (ex : 3 USDC)

- Coin avec volatilité anormalement basse (micropumpette, liquidité très mince).
- ATR sizing → 3 USDC.
- **Après PR #268** : `3 < 9` → VRAI → **skip TYPE_B comme avant**.
- Comportement inchangé : les coins trop peu volatiles restent filtrés.

### Scenario 3 : Solde insuffisant

- Portfolio USDC = 8 USDC (anormal, mais possible après perte).
- Candidat dimensionné à 9 USDC.
- **Phase 4 (Sizing)** : Vérifie `solde (8) >= montant (9)` → FAUX → **skip TYPE_C** (insuffisant funds).
- La valeur 9 n'affecte pas ce flux ; c'est un contrôle indépendant.

---

## Plan de test (utilisateur)

1. **Vérif syntaxe** : `python3 -c "import json; json.load(open('config.json'))"` doit passer.
2. **Redémarrage du bot** : `/status` doit répondre en < 5s.
3. **Observation** : Surveiller les 7 prochains cycles (7j environ) :
   - Nombre de TYPE_B : **cible ≤ 1 par semaine** (au lieu de 4/7j).
   - Montants ordres : **accepter 9–11 USDC qui étaient précédemment rejetés**.
4. **Stabilité** : Pas de changement dans `/perf` (P&L, Sharpe, drawdown) ; seul le nombre d'ordres augmente.
