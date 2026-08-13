# PR #381 — [M1] Élargir la zone RSI bonus Phase 3 et la rendre configurable

> **Mergée le** : 2026-08-13
> **Branche** : `feat/issue-380-rsi-zone-config`
> **Issues** : #380

## Contexte

Lors de 4 cycles observés, le coin LINK présentait un signal 4h+1D BUY valide mais un RSI 59–65, ce qui plafonnait son score à 5/10 (juste sous le seuil minimum requis de 6/10). La borne haute de la zone RSI bonus était codée en dur à 55 dans `phase3_scoring.py`, bloquant les opportunités promettantes avec RSI légèrement élevé.

Cette PR élargit la borne haute de 55 à 65 et rend la zone RSI entièrement configurable via `config.json` (clés `rsi_zone_min` et `rsi_zone_max`), suivant le pattern existant pour les autres seuils (`min_signal_score`, `max_open_positions`, etc.).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase3_scoring.py` | Modification | Lecture `rsi_zone_min`/`rsi_zone_max` depuis config avec défauts 30/65, suppression des littéraux codés en dur |
| `config.json` | Modification | Ajout explicite des clés `rsi_zone_min: 30` et `rsi_zone_max: 65` |
| `tests/test_phase3_scoring.py` | Ajout tests | Ajout de la classe `TestRsiZoneBonus` couvrant RSI in-zone (60) et out-of-zone (66) |

### Fonctions modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `main()` (Phase 3) | `phase3_scoring.py:46-47` | Modification | Extraction des bornes RSI depuis config : `rsi_zone_min = cfg.get("rsi_zone_min", 30)` et `rsi_zone_max = cfg.get("rsi_zone_max", 65)` |
| `main()` (Phase 3) | `phase3_scoring.py:87` | Modification | Utilisation des bornes dynamiques : condition `rsi_zone_min <= rsi_4h <= rsi_zone_max` au lieu de littéraux 30/55 |

## Décisions techniques notables

- **Pattern de configuration réutilisé** : les variables `rsi_zone_min`/`rsi_zone_max` utilisent la même convention `cfg.get(..., default)` que les autres seuils (`min_signal_score`, `max_open_positions`, `max_correlated_positions`). Uniformité avec le reste du codebase.

- **Défauts cohérents** : les défauts (30/65) correspondent à la borne inférieure inchangée (30) et à la nouvelle borne supérieure (65). Si `config.json` n'a pas ces clés, le script utilise les défauts directement, assurant la rétrocompatibilité.

- **Message utilisateur inchangé** : le message d'exclusion `f"RSI {rsi_4h:.0f} hors zone"` ne mentionne pas les valeurs numériques, donc reste cohérent quelles que soient les bornes configurées. Pas de surcharge informationnelle pour l'utilisateur.

- **Aucun nouveau pattern de scoring** : le bonus RSI (+1 point) reste identique ; seules les bornes qui le triggent changent. Le reste de la formule de score est inaffecté.

## Impact sur l'architecture

Changement isolé, sans impact sur l'architecture globale :
- La Phase 3 continue de calculer les scores et de sélectionner les candidats BUY.
- Aucun changement dans le flux de données, l'état persistant, ou les composants externes.
- La configurabilité offre une flexibilité accrue sans complexifier le code.

## Références CLAUDE.md respectées

- **Minimalisme** : changement chirurgical limité à la zone RSI, aucun autre critère de scoring touché. Deux lignes ajoutées au lieu de refactorer.
- **Configuration via `config.json`** : suit le pattern existant `cfg.get(..., default)` utilisé pour tous les autres seuils (§6 CLAUDE.md).
- **Tests unitaires** : la classe `TestRsiZoneBonus` couvre les deux cas limite (RSI 60 dans la zone, RSI 66 hors de la zone) avec assertions sur le score et les raisons.

## Vérifications effectuées

- ✅ Syntaxe Python : `python -c "import ast; ast.parse(...)"` sur les fichiers modifiés.
- ✅ Suite de tests : 11/11 tests verts pour `test_phase3_scoring.py` (pas de régression sur la formule existante).
- ✅ Tests spécifiques ajoutés : `TestRsiZoneBonus` avec deux cas (`test_rsi_60_within_default_zone_gets_bonus`, `test_rsi_66_outside_default_zone_no_bonus`).
- ✅ Rétrocompatibilité : si `config.json` n'a pas les clés RSI, les défauts (30/65) sont utilisés automatiquement.
