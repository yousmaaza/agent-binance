# PR #267 — [M1] fix(Phase 0) — comptage open_positions, retry OCO + close_reason

> **Mergée le** : 2026-06-28
> **Branche** : `feat/issue-266-phase-0-bugs`
> **Issues** : #266

## Contexte

PR #267 résout trois bugs critiques affectant la Phase 0 du cycle de trading :
1. **Comptage inexact des positions ouvertes** : n'incluait pas les positions avec `protection_failed=True`, entraînant un dépassement du seuil `max_open_positions`
2. **Rattrapage OCO échouant silencieusement** : pas de compteur de tentatives ni fallback, ce qui a causé des positions sans protection pendant plusieurs jours (AAVE sans protection du 26/06 04:05 au 28/06 08:05)
3. **`close_reason` ad-hoc** : valeurs non standardisées, rendant impossible le debug et la traçabilité des fermetures

La PR fusionne la branche `feat/issue-266-phase-0-bugs` avec les corrections implémentées par binance-dev.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `config.json` | Ajout paramètre | Nouveau paramètre `max_oco_retry` (défaut 3) pour configurer le nombre de tentatives avant fallback SELL MARKET |
| `prompts/trade_prompt.txt` | Refactoring Phase 0 | (+98/-41) Correction du comptage `open_positions`, ajout routine `oco_retry_count`, fallback SELL MARKET `protection_exhausted`, standardisation `close_reason` |

### Changements détaillés

#### 1. Comptage `open_positions` (Phase 0, lignes 504–510)

**Avant** : Comptage implicite ou incomplet.

**Après** (code explicite) :
```python
open_positions = len([t for t in _op_history if t.get("status") == "open"])
```
- **Impact** : Inclut maintenant **toutes** les positions `status="open"`, y compris celles avec `protection_failed=True`.
- **Raison** : Les positions non protégées sont toujours des positions ouvertes et doivent compter contre le seuil `max_open_positions` (4 par défaut).

#### 2. Compteur OCO et fallback SELL MARKET (Phase 0, lignes 256–288)

**Ajout du compteur `oco_retry_count`** dans chaque trade (`trade_history.json`) :
- Initialisé à 0 au placement du trade (Phase 5)
- Incrémenté à chaque tentative de rattrapage OCO échouée en Phase 0
- Remis à 0 si l'OCO réussit

**Fallback automatique** après `max_oco_retry` (config, défaut 3) tentatives :
```python
if _oco_retry_count >= _max_oco_retry:
    # SELL MARKET avec close_reason="protection_exhausted"
```
- **Impact** : Ferme la position via SELL MARKET forcé si le rattrapage OCO échoue 3 fois consécutives.
- **Raison** : Évite l'accumulation de positions non protégées et la saignée lente du P&L.

#### 3. Standardisation `close_reason` (Phase 0, lignes 106–110 + implémentation)

**Valeurs autorisées en Phase 0 uniquement** :
- `"market_above_tp"` : Prix marché au-dessus du TP lors du rattrapage OCO → fermeture SELL MARKET immédiate
- `"profit_target_phase0"` : Position fermée en Phase 0 pour prise de profit (P&L ≥ `min_profit_pct_take`)
- `"protection_exhausted"` : SELL MARKET après `max_oco_retry` échecs de rattrapage OCO

**Autres valeurs** (tp_hit, sl_hit, etc.) restent réservées aux autres phases.

- **Impact** : Traçabilité claire des motifs de fermeture en Phase 0.
- **Raison** : Permet le debug et l'analyse stratégique (ex: comment souvent `protection_exhausted` se déclenche).

#### 4. Paramètre `config.json` (ligne 27)

```json
"max_oco_retry": 3
```
- **Type** : entier (nombre de tentatives)
- **Défaut** : 3
- **Rôle** : Seuil avant fallback SELL MARKET en Phase 0 du rattrapage OCO.

### Fonctions modifiées

| Fonction | Section du code | Action | Description |
|---|---|---|---|
| Phase 0 (TRADE_PROMPT) | Snapshot positions (lignes 112–165) | Refactorisation | Ajout d'un résumé explicite des positions ouvertes avec prix actuel et P&L avant toute autre action Phase 0 |
| Phase 0 (TRADE_PROMPT) | Rattrapage protection_failed (lignes 191–333) | Refactorisation majeure | Restructuration : lecture config `max_oco_retry`, compteur `oco_retry_count`, fallback SELL MARKET après seuil atteint, ajout des 3 `close_reason` standardisées, notification Telegram granulaire |
| Phase 0 (TRADE_PROMPT) | Réalisation de profits (lignes 439–502) | Refactorisation | Ajout boucle explicite sur positions ouvertes avec critères profit (P&L ≥ `min_profit_pct_take`) et hold max (> `max_hold_days`) pour SELL MARKET automatique |
| Phase 0 (TRADE_PROMPT) | Comptage final (lignes 504–519) | Refactorisation | Code explicite : compte toutes positions `status="open"` indépendamment du champ `protection_failed`, charge `max_open_positions` depuis config |

## Décisions techniques notables

- **`oco_retry_count` persisté dans `trade_history.json`** : Permet de reprendre exactement où on en était en cas de redémarrage du bot mi-cycle (idempotence). Remis à 0 si l'OCO réussit ou après fallback.

- **Fallback SELL MARKET au lieu de prise de position manuellement** : Le bot ne peut pas anticiper le prix optimal ; mieux vaut vendre au marché que d'accumuler des positions orphelines sans protection.

- **Phase 0 d'abord, avant Phase 1** : Calibrage du portefeuille (solde, limit pertes jour, réalisation profits, protection positions) avant d'identifier de nouveaux candidats. Garantit que les contraintes de risque sont respectées **avant** toute nouvelle entrée.

- **Standardisation `close_reason` en Phase 0 uniquement** : Les valeurs `tp_hit`, `sl_hit`, `timeout` (etc.) sont générées par Binance mais **ne passent jamais par Phase 0**. Phase 0 gère les fermetures proactives (profits manuels, protection épuisée, prix au-dessus du TP). Les autres raisons appartiennent à d'autres phases ou à des processus externes.

## Impact sur l'architecture

**Correctif isolé, pas d'impact architectural global.**

- Phase 0 acquiert une logique de calibrage plus robuste et explicite.
- Le flux global (Phases 1–8) reste inchangé.
- Amélioration de la traçabilité via standardisation des `close_reason` et historique `oco_retry_count` dans `trade_history.json`.

**Impact opérationnel** :
- Positions non protégées seront fermées après 3 tentatives OCO échouées (au lieu de s'accumuler indéfiniment).
- Positions avec P&L profitable seront réalisées en Phase 0 dès que le seuil `min_profit_pct_take` est atteint.
- Le comptage `open_positions` sera désormais exact pour tous les appels à la limite `max_open_positions`.

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : `__PROJECT_DIR__` reste utilisé pour les chemins (lignes 118, 199, etc.).
- **Règle 3 (Secrets via .env)** : Aucun secret dans le code ; `max_oco_retry` est un paramètre config public dans `config.json`.
- **Règle 5 (Stdout/stderr toujours capturés)** : Phase 0 envoie les notifications via `tg()` (helpers) et écrit les logs à travers le flux normal.
- **Règle 6 (UTC interne)** : Toutes les dates en Phase 0 restent UTC (timestamps `datetime.now(timezone.utc).isoformat()`).
- **Convention horaire** : Affichages utilisateur en heure locale via `fmt_local()` si besoin.

---

## Cas d'usage et scénarios

### Scenario 1 : Position avec protection_failed = True

1. **Phase 5 (antérieur)** : BUY MARKET réussit, mais OCO échoue → trade enregistré avec `protection_failed=True`, `oco_retry_count=0`.
2. **Prochain cycle Phase 0** : Routine rattrapage identifie la position non protégée.
3. **Tentative OCO** : Réussit ? Remise à `protection_failed=False`, `oco_retry_count=0`, cycle continue.
4. **3 tentatives échouées** : `oco_retry_count` atteint 3 → SELL MARKET forcé avec `close_reason="protection_exhausted"`.

### Scenario 2 : Comptage dépassement max_open_positions

**Avant PR #267** :
- 4 positions `status="open"`, 1 avec `protection_failed=True` = comptage=4 (skip nouvelle entrée incorrectement).
- Ou comptage=3 si `protection_failed` exclu → nouvelle entrée lancée, dépassement de limite.

**Après PR #267** :
- 4 positions `status="open"` dont 1 `protection_failed=True` = comptage=5 → respecte limite `max_open_positions=4` explicitement.

### Scenario 3 : Réalisation P&L en Phase 0

Position SOL : entrée 100 USDC, prix courant → P&L +3% (>= seuil `min_profit_pct_take=2%`).
- **Phase 0** : SELL MARKET automatique avec `close_reason="profit_target_phase0"`.
- **Notification** : "✅ Phase 0 — SOL vendu (P&L cible) +3.0% | +3.00 USDC".
- **Impact** : Capital libéré pour nouvelles entrées, risque réduit sur position profitable.
