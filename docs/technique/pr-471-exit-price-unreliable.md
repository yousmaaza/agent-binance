# PR #471 — [BUG] SYN 38515bab : marquer exit_price non fiable au lieu de le réécrire

> **Mergée le** : 2026-09-06
> **Branche** : `feat/issue-469-syn-non-fiable`
> **Issues** : #469

## Contexte

Le trade SYN (trade_id: 38515bab) du 26 juin 2026 présentait une anomalie grave : l'`exit_price` enregistré (0,5543) était incompatible avec le `pnl_usdc` réel (-1,165 USDC). Le prix impliquait un gain de +42 USDC alors que le résultat était une perte — un cas physiquement impossible, résultant d'un arrêt-loss déclenché au-dessus du prix d'entrée.

Le ticket #469 interdisait de **réécrire** `exit_price`. Au lieu de cela, cette PR marque explicitement la donnée comme non fiable via un nouveau champ `data_quality`, permettant au dashboard de signaler l'anomalie sans falsifier l'historique.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `dashboard/viewdata.py` | Modification (4 lignes +, 1 ligne −) | Fonction `_suspect_exit()` : lecture du marqueur `data_quality` en priorité |
| `state/trade_history.json` | Modification (2 lignes +, 1 ligne −) | Ajout du champ `data_quality: "exit_price_unreliable"` au trade SYN 38515bab |
| `tests/test_dashboard_viewdata.py` | Modification (42 lignes +) | Nouvelle classe de tests `TestSuspectExitMarker` : 4 assertions couvrant le marqueur + rendu dashboard |
| `tests/test_trade_history_data_quality.py` | Ajouté (38 lignes) | Nouveau fichier : tests sur le vrai `state/trade_history.json` pour prévenir futurs backfills accidentels |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_suspect_exit(trade: dict)` | Modifiée | Lit d'abord le champ `data_quality` ; si égal à `"exit_price_unreliable"`, retourne message explicite. L'heuristique existante (prix impliquant gain vs perte enregistrée) reste active pour détecter de futurs cas non marqués. |
| `TestSuspectExitMarker` | Ajoutée | Classe unittest avec 4 tests : marqueur lu avant heuristique, marqueur appliqué même si heuristique silencieuse, `pnl_usdc` inchangé, rendu dashboard (exclu montants, comptabilisé en net). |
| `TestSyn38515babStaysMarked` | Ajoutée | Classe unittest lisant le vrai `state/trade_history.json` pour certifier persistance du marqueur, invariance de `pnl_usdc`, absence de réécriture de `exit_price`. Protège contre futurs backfills. |

## Décisions techniques notables

- **Marqueur explicite plutôt que réécriture** : respecte le ticket #469 ("marquer... au lieu de le réécrire"). Laisse la donnée brute intacte mais documentée comme immuable mais non fiable.
- **Lecture du marqueur avant l'heuristique** : empêche une future correction accidentelle du prix si l'heuristique déterministe était appliquée en sortie. Le marqueur prime, c'est intentionnel.
- **Champ `data_quality` extensible** : nouveau schéma permettant d'autres marqueurs futurs (`exit_price_unreliable`, `entry_price_suspicious`, etc.) sans mutation de la structure historique.
- **Test sur fichier réel, pas fixture** : le trade est historique, immuable, versionné en git. Seul un test lisant le vrai `state/trade_history.json` peut prévenir une réécriture silencieuse lors d'un futur backfill.
- **Agrégats non affectés** : `pnl_usdc` (-1,165) reste inchangé — c'est lui qu'utilisent `/perf`, la courbe d'équité, tous les totaux. Les 88 autres trades clôturés et 3 rouvertures ne changent pas. Vérification : net -26,35 USDC avant/après, identique au centime.

## Impact sur l'architecture

Changement isolé, pas d'impact architectural.

**Dashboard — onglet Ventes** :
- La ligne SYN affiche le marqueur dans la colonne "Suspect" : `"prix de sortie marqué non fiable (data_quality)"`.
- Le montant investi de ce trade (quantité × `entry_price`) sort du total "Investi" (ligne totals).
- Le net du trade (-1,165 USDC) reste comptabilisé dans "Net" (position close reste active dans la P&L globale).
- Cette dichotomie (exclu des montants, inclus en net) communique clairement au lecteur : "ce trade affecte votre P&L mais les montants sont suspects, vérifiez manuellement le fill réel".

**Performance et fiabilité** :
- Aucune modification du modèle de donnée historique `trade_history.json` (juste ajout d'un champ optionnel).
- Les 482 tests pass inchangés (new test `TestSuspectExitMarker` ajoute 4 cas sans régression).
- Aucun appel réseau ni I/O supplémentaire : lecture de champ local dans `_suspect_exit()`.

## Références CLAUDE.md respectées

- **Règle 3** (Minimalisme) : code minimum qui résout le problème. Aucun backfill global ni "correction intelligente" — marqueur simple et explicite.
- **Règle 6** (Convention horaire) : le marqueur ne touche ni aux timestamps ni aux conversions UTC/local. L'horloge du trade reste 2026-06-26T20:06:52.744107+00:00.
- **Pas de gestion d'erreur pour scénarios impossibles** : le test est intrinsèque (si le marqueur disparaît, le test le signale immédiatement).

## Validation

- ✅ Marqueur présent sur trade 38515bab
- ✅ `pnl_usdc` inchangé (-1,1650800000000001)
- ✅ `exit_price` n'a pas été réécrit (toujours 0.5543, pas 0.33825 dérivé)
- ✅ Agrégats financiers stables avant/après : net -26.35 USDC, brut +42.78 USDC, frais 67.72 USDC (88 trades clos)
- ✅ 482 tests pass, dont 4 nouveaux spécifiques au marqueur
- ✅ `ruff check` : 0 erreur (108 préexistantes dans d'autres fichiers, non touchées)
- ✅ Dashboard : rendu fixture `SYN_38515BAB` — ligne suspect, montant exclu, net inclus
