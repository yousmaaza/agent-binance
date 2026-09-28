# PR #510 — Filtre anti-poursuite : refuser une entrée après une hausse 24h excessive

> **Mergée le** : 2026-09-28
> **Branche** : `feat/issue-507-filtre-anti-poursuite`
> **Issue** : #507

## Contexte

Le timing d'entrée est critique pour la profitabilité. Une hausse 24h excessive avant l'entrée est statistiquement corrélée à une perte à 24h post-entrée (médiane -1,83% sur échantillon mesuré). Cette PR introduit un filtre en Phase 3 qui refuse une entrée (BUY) si le prix a monté plus que le seuil `max_24h_runup_pct` configuré, tout en préservant le HOLD pour les coins déjà en portefeuille (issue #507).

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase1_scan.py` | Modification | Calcul `change_24h_pct` depuis les bougies OHLC 4h de persistance volume — aucun appel réseau supplémentaire |
| `binance-bot/core/phases/phase3_scoring.py` | Modification | Filtre anti-poursuite en Phase 3 : skippe TYPE_A si `change_24h_pct > max_24h_runup_pct` (sauf coins en portefeuille) |
| `config.json` | Modification | Nouvelle clé `max_24h_runup_pct = 0.04` (4%) |
| `prompts/phases/phase3_scoring.txt` | Modification | Contrat Phase 3 met à jour la structure `analysis_results` avec le champ `change_24h_pct` |
| `docs/strategie.html` | Modification | Documentation du filtre dans l'arbre de décision (5 étapes) ; clé de config documentée |
| `docs/strategie.md` | Modification | Régénéré par `scripts/strategie_to_md.py` |
| `tests/test_phase1_scan.py` | Modification | Tests ajoutés : calcul `change_24h_pct`, absence pour coins portefeuille |
| `tests/test_phase3_scoring.py` | Modification | Tests ajoutés : skip au-dessus du seuil, HOLD préservé si `in_portfolio`, comportement inchangé si absent/sous seuil |

### Fonctions ajoutées / modifiées

| Fonction | Fichier | Action | Description |
|---|---|---|---|
| `_volume_persistence_and_change()` | phase1_scan.py | Renommée + modifiée | Précédemment `_volume_is_persistent()` — retourne maintenant un tuple `(is_persistent, change_24h_pct)`. Calcule la variation de prix sur 24h à partir des bougies 4h : `(close_now - open_24h_ago) / open_24h_ago`. Retourne `None` pour `change_24h_pct` si les données sont insuffisantes ou absent pour les coins en portefeuille. |
| `phase1_scan.py` main loop | phase1_scan.py | Modifiée | Expose `change_24h_pct` sur chaque entrée `tradable` : `None` pour coins portefeuille, float calculé pour autres (peut être `None` si ohlc indisponible). |
| Phase 3 scoring | phase3_scoring.py | Modifiée | Ajoute filtre `runup_block` lignes 120-121 : vérification `change_24h_pct > max_24h_runup_pct` avec condition `not in_portfolio`. Skip TYPE_A avec `skip_detail` explicite si dépassement. |

## Décisions techniques notables

- **Réutilisation des bougies ohlc** : Les bougies 4h appelées pour vérifier la persistance du volume en Phase 1 sont réutilisées pour calculer `change_24h_pct` — zéro appel réseau supplémentaire, bonne pratique éco-système API.
- **Position du filtre dans l'arbre** : Positionné juste après le check `in_portfolio` et avant le mode dégradé (lignes 120-121 de phase3_scoring.py). Le filtre prime sur les autres verrous car il s'agit d'un risque de timing d'entrée indépendant du score.
- **Préservation du HOLD** : Les coins en portefeuille (`in_portfolio: true`) ne sont jamais skippés par ce filtre — le HOLD reste intact quelles que soient les conditions de prix. Cette asymétrie est intentionnelle : la gestion des positions ouvertes (stop-loss, trailing stop, TP) relève d'une phase 0, pas de la phase 3 qui traite uniquement les nouvelles entrées.
- **Absence de `change_24h_pct`** : Le filtre est ignoré silencieusement si `change_24h_pct` est `None` (données ohlc indisponible, ou coin portefeuille sans appel ohlc). Le comportement de scoring reste inchangé.
- **Seuil configurable** : Clé `max_24h_runup_pct` dans `config.json`, défaut 4%, ajustable sans redéploiement du bot.

## Impact sur l'architecture

Changement isolé à la stratégie de sélection (Phase 1 + Phase 3), pas d'impact architectural global. Les flux de données et les contrats prompt/script restent cohérents : Phase 1 expose un champ supplémentaire, Phase 3 le consomme pour un filtre supplémentaire. Les tests validations des contrats (PR #423) continuent de passer.

## Références CLAUDE.md respectées

- **Minimalisme** (§ Minimalisme) : Changement minimal — une fonction renommée+exposée, un filtre booléen, une clé config, pas de refactoring adjacent.
- **Précision des modifications** (§ Modifications chirurgicales) : Lignes 80-95 et 120-121, deadcode absent, style existant préservé.
- **Mutation config.json** (§ Déploiement — Prod sur VPS) : La nouvelle clé `max_24h_runup_pct` sera live après merge et redéploiement VPS — aucune variable d'env supplémentaire, pas d'impact fichier `.env`.
- **Stratégie mise à jour** (§ Toute modification de la stratégie...) : `docs/strategie.html` et `.md` mis à jour (arbre de décision, clé config, mesure justifiant le seuil 4%).

## Tests

- Calcul `change_24h_pct` depuis bougies 4h ✅
- Absence pour coins portefeuille ✅
- Skip TYPE_A si `change_24h_pct > seuil` ✅
- HOLD préservé si `in_portfolio: true` (même si `change_24h_pct > seuil`) ✅
- Comportement inchangé si `change_24h_pct` absent/`None` ✅
- Comportement inchangé si `change_24h_pct ≤ seuil` ✅
- Syntaxe Python valide ✅
- Tests phase 1 et phase 3 passants ✅

Aucun test d'intégration du bot end-to-end exigé à cette étape : la Phase 1 a été intégrée par PR #312, Phase 3 par PR #317. Ce changement reste une mutation de stratégie isolée bien contenue.
