# PR #436 — [BUG] Fermer la redirection ouverte sur next du login dashboard

> **Mergée le** : 2026-08-28
> **Branche** : `fix/issue-435-open-redirect`
> **Issue** : #435

## Contexte

Le dashboard Flask (`dashboard/app.py`) avait une faille de redirection ouverte : après authentification, il redirige vers la valeur du paramètre `next` sans validation, ce qui permettait à un attaquant de rediriger l'utilisateur vers un site malveillant avec une URL comme `/login?next=https://attacker.com`.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `dashboard/auth.py` | Ajout fonction | Nouvelle fonction `safe_next_path()` pour valider les chemins de redirection |
| `dashboard/app.py` | Modification | Utilisation de `safe_next_path()` dans la route `/login` |
| `tests/test_dashboard_auth.py` | Ajout tests | 7 tests unitaires pour `safe_next_path()` |
| `tests/test_dashboard_app.py` | Ajout tests | 4 tests d'intégration pour la redirection `/login` |

### Fonctions ajoutées / modifiées

| Fonction | Action | Description |
|---|---|---|
| `safe_next_path(value)` | Ajoutée (auth.py:20) | Valide un chemin de redirection : n'accepte que les chemins relatifs internes (commencent par `/`, sans schéma ni hôte). Utilise `urllib.parse.urlsplit()` pour parser et rejette tout URL absolue, protocole-relative (`//`), ou variante antislash (`/\`). Retourne le chemin validé ou `None`. |
| `login()` (app.py:30) | Modifiée | Passe maintenant `next` via `safe_next_path()` avant redirection : retombée sur `dashboard_home` si la valeur est rejetée |

## Décisions techniques notables

- **Validation via `urllib.parse.urlsplit()`** : utilisation de la stdlib Python pour parser robustement les URLs ; détecte les schémas (`http://`, `https://`) et les netloc via les champs `scheme` et `netloc` du tuple retourné.
- **Rejet early** : rejet immédiat si `value` est vide/None, ou ne commence pas par `/`, ou commence par `//` ou `/\` (variantes protocole-relative et antislash).
- **Fallback silencieux** : si `safe_next_path()` retourne `None`, la redirection retombe sur `url_for("dashboard_home")` (route racine `/`), ce qui est le comportement sûr par défaut sans exposer d'erreur.

## Impact sur l'architecture

Changement isolé au dashboard : aucun impact sur le bot de trading principal (`webhook_server.py`, phases de trading, MongoDB). Le dashboard reste une application Flask indépendante avec ses propres contraintes de sécurité (authentification password simple, session cookies).

## Références CLAUDE.md respectées

- Pas de code applicatif du bot modifié — uniquement le code du dashboard.
- Syntaxe Python vérifiée (`python -c "import ast; ast.parse(open('dashboard/app.py').read())"` → 0).
- Tests complets : 11 nouveaux tests + 296 existants = 307 total sans régression.
- Pas de dépendance externe ajoutée — utilisation stdlib `urllib.parse.urlsplit()`.

## Tests ajoutés

**Unitaires** (test_dashboard_auth.py:TestSafeNextPath) :
- Chemin interne `/` accepté
- URL absolue `https://exemple-malveillant.test/x` rejetée
- URL protocole-relative `//exemple.test/x` rejetée
- Variante antislash `/\exemple.test` rejetée
- `None` rejeté
- Chaîne vide rejetée
- Chemin sans `/` initial rejeté

**Intégration** (test_dashboard_app.py:TestLoginRedirectNext) :
- URL absolue en `next` → redirection vers `/` (home)
- URL protocole-relative en `next` → redirection vers `/`
- Variante antislash en `next` → redirection vers `/`
- Chemin interne `next=/` → redirection vers `/` (accepté et fonctionnel)
