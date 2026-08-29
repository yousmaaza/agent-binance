# Journal Medium — agent-binance

Carnet de bord technique, une entrée par jour actif. Alimente des articles Medium réguliers.
Chaque entrée suit le format : PRs mergées · issues fermées · tickets créés · matériel · angle Medium.

---

## 2026-08-29

### PRs mergées (4)

**PR #443 — Aligner le dashboard sur la maquette validée et arrondir les prix**

Le dashboard livré deux jours plus tôt (#434) était fonctionnel mais son apparence ne correspondait pas à la maquette validée — `binance-dev` s'exécutant sans navigateur, il avait écrit une feuille de style minimale de son cru. Cette PR porte l'alignement visuel complet : polices (Archivo, IBM Plex Mono, Source Serif 4), palette papier/encre avec thème clair/sombre (CSS variables + `prefers-color-scheme`), onglets en CSS pur via radios (zéro JavaScript), courbe d'équité avec aire remplie et ligne zéro. Les prix illisibles de Kraken (flottantes brutes comme `706.4407567166553`) sont désormais formatés via `format_price()` : 2 décimales au-dessus de 1 USDC, 6 en dessous, espace fine insécable comme séparateur milliers. La note de la semaine (`weekly_note()`) devient une synthèse recalculée à chaque affichage plutôt qu'un texte figé qui mentirait dès que les données changent. Refactoring simultané de `dashboard_home()` en 5 helpers (`_load_*`, `_build_*`). +24 tests couvrant les nouvelles fonctions, tous verts.

**PR #449 — /maker — afficher les abandons et corriger la précision du délai**

La commande Telegram `/maker` ne montrait pas les ordres abandonnés (ordres limite maker expirés sans remplissage ni fallback marché) et arrondissait le délai médian à la minute alors que la stratégie a besoin de précision à la seconde pour calibrer `maker_max_concession_pct` et `maker_timeout_seconds`. Ajout d'un funnel watcher (fills / replis marché / abandons) avec compteur `total_abandoned` dans le bloc de santé, délai médian en secondes via `_fmt_seconds_precise()` — distincte de `_fmt_duration()` qui sert à l'âge des ordres actifs, deux métriques de nature différente. Tendance 7 jours du taux de remplissage avec garde-fou : calcul affiché uniquement si l'échantillon dépasse 5 trades classés (`_MIN_TREND_SAMPLE = 5`), sinon message honnête « échantillon insuffisant ». Chargement mutualisé de l'état JSON (une seule I/O en amont dans `run_maker()`, passée aux helpers). +10 tests, tous verts.

**PR #451 — Graphe de PnL par jour/mois et grille d'état des cycles**

La bande de cadence SVG affichait de petites barres illisibles avec des infobulles `<title>` inaccessibles au clavier et invisibles sur mobile. Cette PR la remplace par deux éléments. Premier : barres divergentes de PnL (positives vers le haut, négatives vers le bas, échelle symétrique `max(|min|, |max|)`) avec toggle jour/mois et infobulles JavaScript positionnées au survol et au focus clavier. Deuxième : grille calendrier des créneaux théoriques 4h. Le point technique central de la grille : un cycle qui ne démarre pas n'écrit rien en MongoDB — toute agrégation est aveugle à ces lacunes. La grille part du calendrier attendu (6 créneaux × N jours UTC) et cherche le cycle correspondant avec une tolérance ±1h ; s'il est absent, la cellule est marquée « missing ». Sur 30 jours réels de données : 139 créneaux sur 601 n'avaient jamais démarré — statistique impossible à obtenir par une requête Mongo. Optimisation de la projection Mongo pour la grille (10 champs sur ~40 dans le document complet) : 100 ms vs 2–3 s par rafraîchissement. +35 tests ajoutés, 4 supprimés (+31 net), tous verts.

**PR #454 — Analyse hebdomadaire rédigée par Claude dans le dashboard**

La section « Note de la semaine » du dashboard affichait un résumé statique généré par `weekly_note()`. Cette PR substitue un texte rédigé par Claude Sonnet 4.6, avec un garde-fou numérique strict : `_verify_numbers()` extrait tous les nombres du texte produit et vérifie que chacun est retrouvable dans la charge utile transmise (tel quel ou dérivé par une opération simple — somme, pourcentage, différence). Un chiffre inventé fait échouer la génération ; le dashboard retombe silencieusement sur le résumé déterministe sans révéler la défaillance à l'utilisateur. Fenêtre adaptative : 7 jours si ≥ 10 trades, sinon 30 jours avec flag `window_widened` clairement signalé. Idempotence par semaine ISO (`2026-W35`) stockée dans une nouvelle collection MongoDB `weekly_analysis` — pas de double appel si le bot redémarre le lundi. L'analyse est schedulée dans `main_loop()` juste après le créneau de trading du lundi 00:05 UTC (déclenchement à 00:10). Isolation totale : tout échec (quota, timeout, contrôle numérique) est capturé localement, jamais remonté au cycle de trading. Nouveaux fichiers : `core/weekly_analysis.py` (416 lignes) et `tests/test_weekly_analysis.py` (351 lignes), plus additions dans timing, mongo, dashboard.

### Issues fermées aujourd'hui (10)

Fonctionnelles :
- **#442** [M1] Aligner le dashboard sur la maquette validée et arrondir les prix → PR #443
- **#430** [M1] /maker — afficher les abandons et corriger la précision du délai → PR #449
- **#450** [M1] Remplacer la bande de cadence par un graphe de PnL par jour / mois → PR #451
- **#453** [M1] Analyse hebdomadaire rédigée par Claude dans le dashboard → PR #454
- **#389** [M1] Commande Telegram /maker — suivi du watcher d'ordres maker

Tickets REC-AUTO (créés + fermés automatiquement par la pipeline review) :
- **#444** [REC] Utiliser X | None au lieu de Optional[X]
- **#445** [REC] Envelopper la concaténation de chaînes dans des parenthèses
- **#446** [REC] Décomposer dashboard_home() pour réduire la complexité
- **#447** [REC] Trier les imports selon les conventions (ruff check --fix)
- **#448** [REC] Utiliser itertools.pairwise() au lieu de zip() pour les paires

### Tickets créés aujourd'hui (9)

- **#452** [BUG] error_type, coût et durée perdus sur les cycles en échec (update sans upsert) — ouvert, non traité
- **#453** [M1] Analyse hebdomadaire → créé et fermé le même jour
- **#450** [M1] Graphe de PnL → créé et fermé le même jour
- **#444–#448** (5 tickets REC-AUTO) → créés et fermés automatiquement par la pipeline de review

### Matériel disponible pour Medium

- 4 PRs mergées dans la même journée (08h21 → 18h01 UTC), toutes centrées sur le dashboard : rendu visuel → observabilité commande → graphiques données → IA intégrée.
- Chiffre-clé grille cycles : 139 créneaux sur 601 « jamais démarrés » sur 30 jours, invisible à toute requête MongoDB, visible uniquement via la grille calendrier théorique.
- Garde-fou anti-hallucination : `_verify_numbers()` comme contrat strict entre Claude et les données — le mécanisme de repli gracieux (aucun message d'erreur utilisateur) est aussi important que la fonctionnalité elle-même.
- Décision non évidente sur le formatage du temps : deux fonctions distinctes (`_fmt_duration` pour l'âge des ordres actifs, `_fmt_seconds_precise` pour le délai médian historique) pour éviter une confusion métrique subtile.
- Optimisation MongoDB : projection de 10 champs au lieu du document complet → ×20–30 sur le temps de chargement de la grille (100 ms vs 2–3 s).

### Angle Medium potentiel

**Angle principal** : « Comment j'ai intégré Claude dans le dashboard de mon bot de trading — et pourquoi j'ai passé plus de temps sur le garde-fou que sur le prompt. » La PR #454 illustre le vrai effort d'une IA intégrée dans un système de production : idempotence, fenêtre adaptative, contrôle numérique des hallucinations, isolation des erreurs dans la boucle principale. L'IA n'est qu'une des quatre améliorations du jour — les autres (grille, PnL, affichage maker) sont entièrement déterministes.

**Angle secondaire** : « Une statistique impossible à requêter en Mongo » — la grille calendrier qui révèle les créneaux manquants (139/601) qu'aucune agrégation ne peut voir, car un cycle qui n'a pas démarré n'écrit aucun document.

---

## 2026-08-28

### PRs mergées (4)

**PR #429 — Plafonner le TP à ce que le marché délivre réellement**
Déclencheur : analyse de 13 trades réels montrait que la formule mécanique `reward_risk_ratio × distance_stop` produisait des cibles jusqu'à 14% de hausse, alors que la hausse médiane observée pendant la détention n'est que +4.9% (90e centile : +9.3%) et qu'aucune cible au-delà de 8% n'a jamais été atteinte. Solution : nouveau paramètre `max_tp_pct = 0.06` dans `config.json`, appliqué dans 4 emplacements simultanément — Phase 4 (dimensionnement), Phase 5 (recalcul post-fill MARKET), `maker_watcher.py`, et le prompt Claude de Phase 0 (recalibrage). Ce dernier point est le piège non évident : omettre le prompt aurait annulé le correctif au cycle suivant (< 4h). Gestion explicite du conflit plancher/plafond (#411) : si le plafond descend sous le plancher de viabilité, le plancher prime. Tests : 226 → 226+13 = résulte en 226 tests, tous verts.

**PR #433 — Publier l'état du bot dans MongoDB pour le dashboard**
Socle de données pour le dashboard : à chaque Phase 7 (persistance MongoDB), `_build_dashboard_state()` reconstruit un document unique (`_id: "current"`) dans une nouvelle collection `dashboard_state`. Le document agrège l'état global depuis `state/trade_history.json`, `maker_watcher_state.json`, `tp_watcher_state.json` et une whitelist de 12 clés de `config.json`. Notable : la courbe d'équité est compressée à un point par jour (vs 84 trades bruts), soit ~50% de réduction du document. Deux types d'exception MongoDB distincts (`MongoUnavailable` vs `DashboardStateMissing`) pour que les messages d'erreur du dashboard soient précis. Suite : 226 → 236 tests (+10), tous verts.

**PR #434 — Dashboard web du bot hébergé sur Railway**
L'application Flask complète : 20 fichiers créés dans `dashboard/` (app.py, auth.py, mongo_client.py, kraken_client.py, cache.py, analysis.py, viewdata.py, templates Jinja2, CSS/JS). 3 onglets — Résultats (P&L brut/frais/net, courbe d'équité SVG, positions ouvertes enrichies avec prix Kraken courants et distances stop/TP), Cycles (journal JSONL, bande de cadence, motifs de blocage, fiabilité 7j/30j), Réglages (config active). Architecture complètement découplée : `dashboard/` ne fait aucun import de `binance-bot/` — Railway peut donc déployer uniquement le sous-dossier sans le bot. Décisions notables : cache TTL process-local (pas de Redis, 1 dyno Railway mono-utilisateur), auth password + Flask session (timing-safe via `hmac.compare_digest`), 4 états dégradés distincts avec messages d'aide. `urllib` toléré ici car pas en contexte nohup Mac (la règle CLAUDE.md §4 est scoped au bug Telegram). Suite : 236 → 296 tests (+60 dashboard), tous verts.

**PR #436 — Fermer la redirection ouverte sur next du login dashboard**
Correctif sécurité découvert immédiatement après la PR #434 : la route `/login?next=https://attacker.com` redirige sans validation. Ajout de `safe_next_path()` dans `dashboard/auth.py` via `urllib.parse.urlsplit()` — rejette tout URL absolue, protocole-relative (`//`) ou variante antislash (`/\`). Fallback silencieux vers `/` si chemin rejeté. Suite : 296 → 307 tests (+11), tous verts.

### Issues fermées aujourd'hui (9)

Fonctionnelles :
- **#428** [M1] Plafonner le TP à ce que le marché délivre réellement → PR #429
- **#431** [M1] Publier l'état du bot dans MongoDB pour le dashboard → PR #433
- **#432** [M1] Dashboard web du bot hébergé sur Railway → PR #434
- **#435** [BUG] Redirection ouverte sur le paramètre next du login dashboard → PR #436

Tickets REC-AUTO (créés + fermés automatiquement par la pipeline review) :
- **#437** [REC] Simplifier la vérification des préfixes dans safe_next_path()
- **#438** [REC] Corriger l'ordre des imports (Ruff I001)
- **#439** [REC] Supprimer les directives noqa: E402 inutiles
- **#440** [REC] Moderniser les appels .encode('utf-8') (UP012)
- **#441** [REC] Monitorer la complexité de dashboard_home() (CC=15)

### Tickets créés aujourd'hui (1)

- **#430** [M1] /maker — afficher les abandons et corriger la précision du délai (ouvert, non assigné)

### Matériel disponible pour Medium

- 3 PRs dashboard en séquence rapide (#431 → #433 → #434 → #436) montrent le rythme "données → backend → frontend → sécurité" d'une journée
- Stat narrative : 81 tests créés en une journée (226 → 307)
- Tableau des 13 trades analysés pour le plafond TP (médiane +4.9%, 90e centile +9.3%, taux de réussite des cibles > 8% : 0/4)
- Décision technique précise : pourquoi `urllib` est interdit dans le bot mais toléré dans le dashboard (contexte nohup Mac vs Railway Linux)
- Règle des 4 emplacements pour `max_tp_pct` : un correctif numérique qui doit aussi aller dans le prompt Claude, sinon annulé à chaud

### Angle Medium potentiel

**Angle principal** : "J'ai sorti un dashboard de trading de zéro à déployé en une journée — et le correctif sécurité a suivi dans les 3 heures." La journée démontre le flux complet : insight statistique sur données réelles → correctif TP → backend MongoDB → frontend Flask → sécurité. Sans une ligne de code manuelle directe : agents `binance-dev`, pipeline CI/review auto, tickets REC-AUTO.

**Angle secondaire** : La règle des "4 emplacements" — pourquoi un paramètre de trading doit être appliqué à la fois dans le code Python et dans le prompt LLM, sinon le bot se reconfigure lui-même en < 4h.

---
