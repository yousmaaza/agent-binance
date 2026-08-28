# Journal Medium — agent-binance

Carnet de bord technique, une entrée par jour actif. Alimente des articles Medium réguliers.
Chaque entrée suit le format : PRs mergées · issues fermées · tickets créés · matériel · angle Medium.

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
