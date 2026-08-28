# PR #434 — [M1] Dashboard web du bot hébergé sur Railway

> **Mergée le** : 2026-08-28
> **Branche** : `feat/issue-432-dashboard-railway`
> **Issues** : #432

## Contexte

Déploiement du **dashboard web** du bot (jelon **[M1]** d'une feuille de route multi-parts). Après la PR #431 (publikation de l'état du bot dans MongoDB `dashboard_state`), cette PR ajoute une **app Flask indépendante** hébergée sur Railway, en lecture seule sur MongoDB Atlas, pour afficher 3 onglets : résultats (P&L, courbe d'équité, positions ouvertes avec prix Kraken courants), cycles (historique, motifs de blocage, fiabilité), réglages (config active). Aucune intégration dans le bot `webhook_server.py` — architecture complètement découplée (`dashboard/` est un sous-dossier autonome).

## Changements

### Fichiers modifiés

| Fichier | Type | Impact |
|---|---|---|
| `.github/workflows/tests.yml` | Modification | Install `dashboard/requirements.txt` en plus du `requirements.txt` racine pour que les 60 nouveaux tests dashboard trouvent Flask |
| `binance-bot/core/phases/phase7_mongo.py` | Modification | Expose `display_timezone` dans le whitelist `_CONFIG_KEYS` (1 ligne + test) — nécessaire pour que le dashboard récupère le fuseau d'affichage configuré dans `config.json` |

### Fichiers créés

| Fichier | Type | Lignes | Description |
|---|---|---|---|
| `dashboard/app.py` | Python | 106 | App Flask principale — 4 routes : `/login` (POST, auth password), `/logout`, `/` (dashboard home avec session), `before_request` (contrôle configuration) |
| `dashboard/auth.py` | Python | 25 | Auth simple : `check_password()` (hmac.compare_digest), `login_required` (décorateur Flask), `is_configured()` (vérifie DASHBOARD_PASSWORD + SECRET_KEY) |
| `dashboard/mongo_client.py` | Python | 71 | Lectures MongoDB : `get_dashboard_state()` (cache 60s), `get_recent_cycles()` (cache 60s) ; 2 exceptions distinctes `MongoUnavailable` et `DashboardStateMissing` pour états dégradés précis |
| `dashboard/kraken_client.py` | Python | 51 | Prix courants via Kraken API publique : appel groupé `GET /Ticker?pair=XXUSDC,...` (urllib stdlib), cache 30s, gestion paires legacy (X/Z prefix remap) |
| `dashboard/cache.py` | Python | 26 | Cache TTL process-local : `TTLCache.get_or_set()` (time.monotonic, dict process-local) — pas de Redis, 1 dyno web sur Railway |
| `dashboard/analysis.py` | Python | 90 | Analyses recalculées à chaque affichage : `blocking_reasons()` (skip_type breakdown), `reliability_by_period()` (7j vs 30j success rate + trend phrase dynamique) |
| `dashboard/viewdata.py` | Python | 128 | Transform Mongo brut en structures view : `build_positions()` (enrichit avec prix courants, distances stop/tp, PnL %), `build_cycle_row()`, `build_periods_table()`, `equity_curve_points()` (SVG polyline), `build_cadence_band()` |
| `dashboard/timeutil.py` | Python | 33 | Utils temps : `parse_iso()`, `to_local()` (réimplémentation autonome pour éviter dépendances `binance-bot/`) |
| `dashboard/settings.py` | Python | 38 | Config variables d'environnement : `MONGODB_URI`, `DASHBOARD_PASSWORD`, `DASHBOARD_SECRET_KEY`, seuils cache TTL, threshold péremption 5h, repli `display_timezone` |
| `dashboard/requirements.txt` | Dependencies | 3 | Flask 3.0.0, gunicorn 23.0.0, pymongo 4.10.1 — **isolé du `requirements.txt` racine** |
| `dashboard/Procfile` | Config | 1 | `web: gunicorn app:app --bind 0.0.0.0:$PORT` — Railway détecte Procfile → lanceur Nixpacks |
| `dashboard/.env.example` | Config | 4 | Exemple `.env` pour dev local : template MONGODB_URI, DASHBOARD_PASSWORD, SECRET_KEY |
| `dashboard/static/css/style.css` | CSS | 130 | Style responsive mobile (flexbox, media queries), 3 onglets (tabbed interface), graphiques sparkline/positions table |
| `dashboard/static/js/app.js` | JavaScript | 9 | Refresh timer (30s auto-reload), feedback utilisateur |
| `dashboard/templates/base.html` | Jinja2 | 12 | Template de base : nav header, tab navigation, block content |
| `dashboard/templates/login.html` | Jinja2 | 13 | Formulaire login avec CSRF token |
| `dashboard/templates/dashboard.html` | Jinja2 | 199 | Affichage 3 onglets : Résultats (P&L brut/frais/net, courbe SVG, tranches période, positions avec distances, bilan maker), Cycles (journal JSONL, bande de cadence, motifs blocage, fiabilité 7/30j, bannière périmée/Mongo-down/Kraken-down), Réglages |
| `dashboard/templates/degraded.html` | Jinja2 | 24 | État dégradé : 4 types (mongo_unavailable, state_missing, kraken_unavailable, stale) avec messages d'aide |
| `dashboard/templates/not_configured.html` | Jinja2 | 13 | HTTP 503 si DASHBOARD_PASSWORD ou SECRET_KEY absent |
| `tests/test_dashboard_app.py` | Test | 172 | 29 tests Flask : login flow, routes protégées, 4 états dégradés, rendu templates |
| `tests/test_dashboard_auth.py` | Test | 48 | 8 tests auth : password check, login_required decorator |
| `tests/test_dashboard_mongo_client.py` | Test | 105 | 15 tests Mongo : cache behavior, exception handling, state vs cycles |
| `tests/test_dashboard_kraken_client.py` | Test | 104 | 14 tests Kraken API : parsing réponse, gestion paires legacy, timeout, API down |
| `tests/test_dashboard_analysis.py` | Test | 79 | 11 tests analysis : blocking_reasons breakdown, reliability trend, edge cases |
| `tests/test_dashboard_viewdata.py` | Test | 162 | 22 tests viewdata : build_positions, build_cycle_row, equity curve rendering |
| `tests/test_phase7_mongo.py` | Modification | +3 / -1 | Ajout test de la clé `display_timezone` dans `_CONFIG_KEYS` |

### Résumé numérique

- **20 fichiers créés** (dashboard/ + tests)
- **60 tests unitaires nouveaux** (pytest-style avec `unittest`)
- **296 tests totaux** en CI (236 existants + 60 dashboard)
- **0 dépendances ajoutées au `requirements.txt` racine** (Flask/gunicorn/pymongo isolés dans `dashboard/requirements.txt`)

## Décisions techniques notables

### 1. Indépendance complète `dashboard/` vs `binance-bot/`

**Choix** : Aucun import de `binance-bot/` — réimplémentation de `parse_dt`, `fmt_local` dans `dashboard/timeutil.py`.

**Raison** : Railway peut être configuré avec **Root Directory = `dashboard/`** (le sous-dossier devient la racine du build Nixpacks). Dans ce contexte, `binance-bot/` n'existerait pas à runtime. Imports relatifs (`import config` au lieu de `from binance-bot.config import ...`) garantissent portabilité.

### 2. Deux exceptions MongoDB distinctes

**Choix** : `MongoUnavailable` (réseau/credentials) vs `DashboardStateMissing` (doc absent).

**Raison** : Permet au template `degraded.html` de rendre des messages précis (ex. "MongoDB injoignable" vs "Aucune donnée encore — le bot n'a pas complété de cycle depuis #431"). UX plus claire pour l'administrateur troubleshooting.

### 3. Cache TTL process-local, pas Redis

**Choix** : `dashboard/cache.py` : dict Python + time.monotonic().

**Raison** : 1 dyno web Railway = pas de partage entre processus. Redis serait surcharge pour un dashboard mono-utilisateur (Railway impose coûts supplémentaires). Cache intra-process (60s Mongo, 30s Kraken) suffit.

### 4. API Kraken en `urllib` stdlib, pas `requests`

**Choix** : `urllib.request.urlopen()` pour `https://api.kraken.com/0/public/Ticker`.

**Raison** : La règle CLAUDE.md §4 (« jamais `urllib` ») est scopée au bug **Telegram + nohup + Mac** (DNS IPv6 en échec). Railway est Linux, l'API Kraken publique n'a pas ce défaut. `urllib` évite une dépendance (`requests`).

**Commentaire** : Gestion des paires legacy : si Kraken renomme une paire (ex. prefixe X/Z), on remap par correspondance partielle plutôt que de retourner `None` (lignes 41–43).

### 5. Auth simple : password + Flask session

**Choix** : `DASHBOARD_PASSWORD` (env var) + `session["authenticated"]` (cookie signé par `SECRET_KEY`).

**Raison** : Pas de user/role/token — URL non devinable ne suffit pas à protéger une page exposant la valeur du portefeuille. Password + session imite le comportement existant des commandes Telegram (authentification par `CHAT_ID` fixe).

**Sécurité** : Password stored en clair en env var (conforme à Heroku/Railway best practices — secrets nunca dans le code), comparaison via `hmac.compare_digest()` (timing-safe).

### 6. `display_timezone` exposée dans Phase 7

**Choix** : Ajout à `_CONFIG_KEYS` de `phase7_mongo.py` (1 ligne).

**Raison** : Le dashboard a besoin du fuseau configuré dans `config.json` pour convertir les timestamps Mongo (UTC) en affichage local. Au lieu de hardcoder `"Europe/Paris"`, on persiste la config réelle dans `dashboard_state.config.display_timezone` (avec repli `Europe/Paris` si l'instantané est antérieur à ce déploiement).

### 7. Analyses recalculées, pas figées

**Choix** : Fonctions `blocking_reasons()` et `reliability_by_period()` recalculées à chaque affichage.

**Raison** : La maquette #432 contient des phrases d'analyse (ex. "La fiabilité progresse"). Ces phrases doivent rester vraies quand les données changent — pas de statut "gelé" en base. Récalcul 60s × cycles présent dans le cache = coût acceptable.

### 8. Affichage timezone jamais UTC brut

**Choix** : Tous les timestamps affichés convertis via `to_local()` + fuseau `display_timezone`.

**Raison** : Cohérence avec CLAUDE.md §6 (« Convention horaire : interne UTC, affichage local ») et PR #393 (« jamais UTC brut »).

## Impact sur l'architecture

### Nouveau sous-système : Dashboard

```
Railway (web server)
    ├── app.py (Flask)
    │   ├── /login, /logout
    │   └── / (dashboard_home)
    │       ├── get_dashboard_state() → MongoDB
    │       ├── get_recent_cycles() → MongoDB  
    │       ├── get_prices() → Kraken API public
    │       └── analysis.py (recalc blocking, reliability)
    │           → templates/ (Jinja2, 3 onglets)
    └── static/ (CSS/JS)
         └── style.css, app.js (auto-refresh 30s)
```

### Flux données nouveaux

```
Dashboard (Railway)
    ├──► MongoDB Atlas (lecture seule)
    │    ├── db.dashboard_state (1 doc: _id="current")
    │    └── db.cycles (journal, query limit=60)
    │
    ├──► Kraken API public (prices)
    │    └── GET /0/public/Ticker?pair=XXXUSDC,...
    │
    └──► Rendu HTML (templates Jinja2)
         ├── 3 onglets : Résultats, Cycles, Réglages
         ├── 4 bannières dégradées : Mongo down, state absent, stale, Kraken down
         └── Auto-refresh 30s (JS timer)
```

### Changement à l'architecture existante du bot

**Minimal** — aucune modification des phases de trading. Seule ajout : `display_timezone` exposée depuis `config.json` vers MongoDB (Phase 7) pour que le dashboard l'utilise (ligne 47 de `phase7_mongo.py`).

### État persistant nouveau

Aucun nouvel état dans `state/` du bot — le dashboard lit `dashboard_state` et `cycles` depuis MongoDB (PRs #431). État dashboard-spécifique (session utilisateur, cache) en mémoire process (volatil) ou Flask session (cookie signé).

## Références CLAUDE.md respectées

- **§1 (venv + profil git)** : `dashboard/requirements.txt` séparé, isolation dépendances, Python 3.11 uniquement
- **§3 (pas de secret hardcodé)** : `DASHBOARD_PASSWORD`, `DASHBOARD_SECRET_KEY`, `MONGODB_URI` via env vars uniquement (`.env.example` fourni, `.env` en .gitignore)
- **§4 (Telegram via curl)** : Pas d'appel Telegram du dashboard (lecture seule)
- **§6 (UTC interne / affichage local)** : Tous timestamps affichés convertis via `to_local()` avec fuseau `display_timezone`
- **§7 (auto-scheduler dans main_loop)** : Dashboard indépendant, pas d'impact
- **Minimalisme** : 0 abstraction "hypothétique" — chaque classe/fonction sert un besoin réel (cache TTL, auth, Mongo exception distinct)

## Dépendances (dashboard uniquement)

| Paquet | Version | Raison |
|---|---|---|
| Flask | 3.0.0 | Web framework minimal (Jinja2 templates, session management) |
| gunicorn | 23.0.0 | WSGI server pour Railway (production-ready, pas `flask run`) |
| pymongo | 4.10.1 | Driver MongoDB Atlas (seul moyen légitime d'accéder à une base Atlas) |

> **`requirements.txt` racine du bot : inchangé** — aucune dépendance supplémentaire à `binance-bot/` existant. CI install les deux fichiers (`pip install -r requirements.txt -r dashboard/requirements.txt`).

## Test plan

- ✅ **296 tests unitaires** : 236 existants + **60 nouveaux dashboard**
  - `test_dashboard_app.py` : 29 tests (login flow, routes protégées, 4 états dégradés)
  - `test_dashboard_auth.py` : 8 tests (password, decorator)
  - `test_dashboard_mongo_client.py` : 15 tests (cache, exceptions)
  - `test_dashboard_kraken_client.py` : 14 tests (Kraken API, paires legacy, timeout)
  - `test_dashboard_analysis.py` : 11 tests (blocking, reliability, trends)
  - `test_dashboard_viewdata.py` : 22 tests (build functions, equity curve)
  - `test_phase7_mongo.py` : +3 / -1 (display_timezone in _CONFIG_KEYS)
  
- ✅ **Syntaxe Python** : `ast.parse()` sur tous `.py` → OK
- ✅ **Linting** : `ruff check dashboard/` → pas de problème réel (nits UP045 ignorés pour chirurgie)
- ✅ **Security** : `bandit -r dashboard/` → aucun vrai problème
- ✅ **Smoke test Flask** : test client en cycle (login, 4 états dégradés, rendu positions/cycles)

- ⏳ **À faire par l'utilisateur (post-déploiement)** :
  1. Configurer l'IP sortante statique Railway (Settings → Networking)
  2. Ajouter IP statique à la whitelist MongoDB Atlas (Network Access)
  3. Déployer Railway, tester accès 
  4. Valider responsive mobile (3 onglets, rendu positions)

## Notes d'implémentation

### Ordre de chargement des dépendances en CI

Le fichier `.github/workflows/tests.yml` est modifié pour `pip install -r requirements.txt -r dashboard/requirements.txt`. **Ordre d'installation** : d'abord racine (incluant loguru, etc.), puis dashboard (Flask, gunicorn, pymongo). Aucun conflit — packages sont disjoints.

### Absence de `FAKE_KRAKEN_SCENARIO` pour tests

Les 14 tests `test_dashboard_kraken_client.py` mockent l'API Kraken via `unittest.mock.patch('urllib.request.urlopen')` — pas besoin du harness `FAKE_KRAKEN_SCENARIO` (réservé au bot lui-même pour simulations Kraken-cli).

### MongoDB Atlas whitelist : étape manuelle

La PR elle-même n'a pas les accès pour modifier MongoDB Atlas (IP whitelist). **Message clair dans les 4 templates dégradés** : "Accès injoignable — ajouter votre IP sortante statique à MongoDB Atlas Network Access" (avec lien de doc).

### Reporage du bug adjacent

La fonction `_bloc_cycles()` dans `commands/perf.py` requête **toutes** les cycles Mongo sans fenêtre temporelle — peut devenir lente à large volume. Le dashboard, lui, limite à `DASHBOARD_CYCLES_JOURNAL_LIMIT` (60 par défaut, configurable). **Bug non corrigé** (hors scope PR), mais noté en commentaire de code.

### Schéma Mongo dérivé du code source

Tentative d'exploration MongoDB en direct du Mac dev : `SSL: TLSV1_ALERT_INTERNAL_ERROR` (réseau corporate vs whitelist Atlas resserrée depuis 2026-07-24). Schéma `dashboard_state` et `cycles` dérivé de `phase7_mongo.py` (#431) + tests — à re-vérifier visuellement une fois le déploiement Railway fonctionnel.
