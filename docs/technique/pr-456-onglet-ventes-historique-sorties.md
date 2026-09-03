# PR #456 — Onglet Ventes — historique des sorties dans le dashboard

> **Mergée le** : 2026-09-03
> **Branche** : `feat/issue-455-onglet-ventes`
> **Issues** : #455

## Contexte

Le dashboard montrait les **positions ouvertes** et les cycles qui les créent, mais aucun historique des sorties. L'onglet Ventes (#455) comble ce vide en exposant :
- Résumé **brut / frais / net** et part des gagnantes
- **Ce que chaque motif de sortie rapporte** en barres divergentes gain/perte
- **Durées médians de maintien** par résultat et par déclencheur
- **Qui a déclenché la vente** : cycle, watcher TP, stop Kraken, manuel
- **Sorties qui n'ont pas suivi le plan** : détection d'anomalies
- **Journal complet** avec filtres 1 semaine / 1 mois / 3 mois / 6 mois / tout

Données réelles : sorties sur cible rapportent +44,81 USDC (21 ventes), sorties au stop coûtent −54,86 USDC (14 sorties) ; arrêts mettent 70 h médian contre 16 h pour une cible — l'écart vient du mécanisme, pas du résultat.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/core/phases/phase7_mongo.py` | Ajout | Nouvelle fonction `_closed_trades()` : projection étroite des 200 ventes récentes pour le dashboard (#455) — frais estimés et défauts de données préservés tels quels |
| `dashboard/viewdata.py` | Ajout | 240 lignes : module complet pour l'onglet Ventes — `build_sales_view()`, filtrage par fenêtre, détection d'anomalies, mapping des motifs de clôture, agrégats, médianes de durée |
| `dashboard/app.py` | Modification | Route `/` enrichie : passe `window` et `tab` depuis l'URL, filtre côté serveur pour garantir cohérence bandeau/journal, marque `published` si `closed_trades` en state |
| `dashboard/templates/dashboard.html` | Modification | Nouvel onglet radio #4 "Ventes" (155 lignes) : tableau journal filtré, bandeau résumé, barres divergentes motifs, durées, déclencheurs, anomalies |
| `dashboard/static/css/style.css` | Modification | 45 lignes CSS : styles onglet Ventes (grille, badges, barres, état d'attente avant redéploiement) |
| `tests/test_dashboard_viewdata.py` | Ajout | 142 tests : classement déclencheurs, anomalies (cible franchie / sortie sous cible), filtrage fenêtres, agrégats, cohérence montants, qualité frais, cas limites |
| `tests/test_phase7_mongo.py` | Ajout | 63 tests : projection `_closed_trades()`, limite 200, champs transmis correctement, tri DESC par date de sortie |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `_closed_trades()` | Ajoutée | Phase 7 — Projection des ventes récentes pour l'onglet : limite 200, exclut ordres/prix stop, inclut indicateurs de fiabilité (`fees_estimated`) |
| `build_sales_view()` | Ajoutée | Orchestration complète onglet Ventes : agrégats, anomalies, déclencheurs, qualité des frais |
| `build_sales_rows()` | Ajoutée | Transformation chaque vente en ligne prête affichage : conversions horaires locales, labels motifs, calcul `invested`/`proceeds` en USDC |
| `filter_sales_window()` | Ajoutée | Restreint ventes à une fenêtre (7j/30j/90j/180j/tout) avant agrégation — garantit cohérence bandeau/journal |
| `sale_trigger()` | Ajoutée | Map motif clôture → déclencheur (cycle / watcher / kraken / manuel / inconnu) — base de fiabilité sur motif, jamais horodatage (#455 retour review) |
| `sale_anomaly()` | Ajoutée | Détecte deux écarts sans OHLC : cible franchie mais vendue ailleurs, sortie TP nettement sous cible |
| `close_reason_label()` | Ajoutée | Unification motifs avec plusieurs noms (sl_hit / stop_hit / sl → "stop touché", tp_watcher / tp_watcher_cycle → "cible atteinte") |

## Décisions techniques notables

- **Le déclencheur vient du motif de clôture, jamais de l'horodatage**  
  Un test sur données réelles (15 ventes TP watcher) : 6 tombaient dans une fenêtre de cycle par coïncidence. Rattacher sur la base du temps serait faux 40 % du temps. Enregistrer `cycle_id` à la source fera l'objet d'un ticket séparé.

- **Le filtre s'applique avant les agrégats**  
  Bandeau (brut/frais/net), motifs, durées et journal portent tous sur la même fenêtre. Sinon le total du haut contredirait la liste du bas.

- **Les défauts des données sont montrés, jamais lissés**  
  33 ventes sur 87 portent des frais **estimés** marqués `est.` ; 2 n'en ont aucun affichent « — » jamais 0 ; vente au prix impossible signalée. Cette dernière exclue des montants investi/retiré (creusait 42,57 USDC d'écart) mais reste comptée au net : c'est le prix faux, pas le résultat.

- **L'onglet actif survit au rechargement via l'URL**  
  `window` (periode=...) et `tab` (tab=ventes) passés en query string, filtre côté serveur garantit cohérence.

## Impact sur l'architecture

- **Dashboard (`dashboard/`)** : ajout complet module `viewdata.py` (+240 lignes) dédié ventes. Phase 7 enrichie d'une projection étroite `_closed_trades()` injectée dans `dashboard_state`.
- **Architecture globale** : pas d'impact, change isolé au dashboard (lecture seule du state MongoDB, pas de mutation du flux de trading).
- **Accessibilité données** : `closed_trades` champ nouveau dans `dashboard_state` (#455), n'existe qu'après redéploiement VPS + un cycle. Onglet affiche message explicite d'attente, pas erreur ni page vide.

## Références CLAUDE.md respectées

- ✅ **Pas de dépendances lourdes** : pandas/scipy non utilisés, stats précomputées (médians via tri manual)
- ✅ **Minimalisme fonctionnel** : chaque fonction fait une seule chose (agrégation, détection d'anomalie, filtrage)
- ✅ **Pas d'erreur pour l'impossible** : absence `closed_trades` en state gérée par flag `published` et message utilisateur explicite
- ✅ **Français** : tous labels, motifs de sortie, messages, docstrings en français
- ✅ **Tests complets** : 205 tests ajoutés couvrent les cas réels (ADA anomalie, SYN prix corrompu, doublons motifs)

## Validation

- Rendus contrôlés au navigateur sur données réelles (87 ventes historiques)
- Thèmes clair et sombre vérifiés
- Les 5 fenêtres de filtre testées
- 429 tests passing (28 pré-existants + 142 viewdata + 63 phase7 + 196 autres), `ruff` propre
- Détection in-situ d'anomalies : 3 sorties ne suivent pas le plan (ADA du 21/08 : sortie à 0,2072 cible 0,2034, TP n'a pas déclenché)
