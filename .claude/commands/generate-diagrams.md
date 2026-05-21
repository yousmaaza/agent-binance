---
description: Génère des diagrammes D2 depuis la documentation du projet et les rend en SVG via Kroki.io. Claude analyse le contenu, choisit la bonne structure D2, écrit le code, rend le SVG et sauvegarde les deux dans docs/visuals/. Gratuit, sans clé API. Usage : /generate-diagrams architecture | /generate-diagrams --all | /generate-diagrams --file docs/fonctionnel/trade.md | /generate-diagrams --custom "décris ce que tu veux"
---

Tu es un expert en diagrammes techniques D2. Ta mission : lire la documentation du projet, générer le code D2 le plus clair et le plus précis possible, rendre le SVG via Kroki.io, et sauvegarder les fichiers.

**Répertoire de travail** : `/Users/yousrimaazaoui/Documents/projets/test-debile/agent-binance`
**Sortie** : `docs/visuals/<nom>.d2` (source) + `docs/visuals/<nom>.svg` (rendu)
**Renderer** : Kroki.io (gratuit, sans auth, POST `application/json`)

---

## Étape 0 — Interprétation de l'argument

Parse l'argument passé au skill :

- **Nom de section** (ex: `architecture`, `trade-phases`, `data-flow`, `commands`, `state-files`, `trade`, `perf`) → voir la table de mapping ci-dessous
- **`--all`** → traite toutes les sections de la table
- **`--file <chemin>`** → lit le fichier indiqué, génère 1 ou plusieurs diagrammes selon le contenu
- **`--custom "<description>"`** → génère un diagramme sans lire de fichier, basé sur la description fournie
- **Aucun argument** → affiche la liste des sections disponibles et arrête

---

## Table de mapping sections → documentation

| Section ID | Fichier source | Section à lire | Type D2 recommandé |
|---|---|---|---|
| `architecture` | `docs/technique/SPEC.md` | §2 Architecture (entier) | flowchart `direction: down` |
| `trade-phases` | `docs/technique/SPEC.md` | §2.1 Process principal (arbre main_loop) | flowchart `direction: down` |
| `data-flow` | `docs/technique/SPEC.md` | §2.2 Flux de données | flowchart `direction: right` |
| `commands` | `docs/technique/SPEC.md` | §4 Commandes Telegram | flowchart `direction: right` |
| `state-files` | `docs/technique/SPEC.md` | §5 État persistant | flowchart `direction: down` |
| `trade` | `docs/fonctionnel/trade.md` | (entier) | sequence diagram |
| `perf` | `docs/fonctionnel/perf.md` | (entier) | flowchart `direction: down` |
| `auto-scheduler` | `docs/fonctionnel/auto-scheduler.md` | (entier) | flowchart `direction: down` |

---

## Étape 1 — Lecture de la source

Pour chaque section ciblée :
1. Lis le fichier source avec l'outil Read
2. Identifie les éléments structurants : composants, étapes, flux, relations, décisions
3. Note le type D2 recommandé dans la table (tu peux choisir un type différent si plus adapté)

---

## Étape 2 — Génération du code D2

### Règles de génération

1. **IDs sans espaces ni accents** : `webhook_daemon` pas `webhook daemon` ni `wébhook`. Les labels (entre guillemets) peuvent avoir des espaces et accents.
2. **Labels entre guillemets doubles** : `daemon: "webhook_server.py"` — les guillemets protègent les espaces et caractères spéciaux.
3. **Longueur** : entre 10 et 35 nœuds — ni trop simple, ni illisible.
4. **Shapes disponibles** : `rectangle` (défaut), `circle`, `oval`, `cloud`, `cylinder`, `diamond`, `document`, `person`, `hexagon`, `queue`, `package`.
5. **Commence toujours** par `direction: down` ou `direction: right` (selon le type).
6. **Pas de `#` dans les IDs** — les `#` sont des commentaires D2.
7. **Conteneurs** : utilise des blocs `{}` pour grouper les sous-composants.
8. **Labels de connexion** : `source -> target: "label"` — entre guillemets si espaces.

### Exemples de syntaxe D2

**Flowchart vertical (`direction: down`)**
```d2
direction: down

user: "Utilisateur Telegram" {
  shape: person
}

telegram: "Telegram Bot API" {
  shape: cloud
}

daemon: "webhook_server.py" {
  poll: "Poll Telegram 30s"
  dispatch: "Dispatch commande" {
    shape: diamond
  }
  scheduler: "Auto-scheduler 4h"
  lock: "Verrou cycle"

  poll -> dispatch
  scheduler -> lock
  dispatch -> lock: "trade"
}

claude: "Claude CLI" {
  p0: "Phase 0 - Verifications"
  p1: "Phase 1 - Scan marche"
  p2: "Phase 2 - Analyse"
  p7: "Phase 7 - Persistance"

  p0 -> p1 -> p2 -> p7
}

user -> telegram: "commandes"
telegram -> daemon.poll: "long-poll 30s"
daemon.lock -> claude: "subprocess"
claude.p7 -> telegram: "notification"
```

**Flowchart horizontal (`direction: right`)**
```d2
direction: right

user: "Utilisateur" {
  shape: person
}

tg: "Telegram"
server: "webhook server"

binance: "Binance API" {
  shape: cylinder
}

mongodb: "MongoDB Atlas" {
  shape: cylinder
}

user -> tg: "commandes"
tg -> server: "long-poll"
server -> binance: "binance-cli"
server -> mongodb: "upsert cycles"
```

**Sequence diagram**
```d2
shape: sequence_diagram

user: "Utilisateur"
tg: "Telegram"
srv: "webhook server"
cl: "Claude CLI"
bn: "Binance"

user -> tg: "/trade"
tg -> srv: "update getUpdates"
srv -> srv: "acquire_lock"
srv -> cl: "subprocess TRADE_PROMPT"
cl -> bn: "get-account"
bn -> cl: "soldes USDC"
cl -> tg: "Phase 0 OK"
cl -> bn: "order-list-otoco"
bn -> cl: "ordres confirmes"
cl -> tg: "resume final"
srv -> srv: "release_lock"
```

---

## Étape 3 — Écriture du fichier .d2

Détermine le nom du fichier :
- Section nommée → `docs/visuals/<section-id>.d2` (ex: `docs/visuals/architecture.d2`)
- Fichier source → `docs/visuals/<basename-sans-extension>.d2`
- Custom → `docs/visuals/custom-<slug>.d2`

Écris le fichier `.d2` avec le code D2 généré.

---

## Étape 4 — Rendu SVG via Kroki.io

Utilise ce script bash pour appeler l'API Kroki avec POST JSON :

```bash
D2_FILE="docs/visuals/<nom>.d2"
SVG_FILE="docs/visuals/<nom>.svg"

# Encoder le contenu D2 en JSON et appeler Kroki
JSON_BODY=$(python3 -c "
import json, sys
content = open('$D2_FILE').read()
print(json.dumps({'diagram_source': content}))
")

curl -s -f -X POST https://kroki.io/d2/svg \
  -H "Content-Type: application/json" \
  -H "User-Agent: agent-binance-diagrams/1.0" \
  --data-raw "$JSON_BODY" \
  -o "$SVG_FILE"

echo "Exit: $?"
```

Si l'appel échoue (exit non-zéro) :
1. Affiche le contenu de la réponse pour debug : `cat "$SVG_FILE" | head -5`
2. Vérifie :
   - Pas d'IDs avec espaces (remplace par `_`)
   - Pas de `#` dans les IDs (c'est un commentaire D2)
   - Les labels sont bien entre guillemets doubles si espaces
   - La syntaxe des connexions (`->` pas `-->`)
3. Corrige le code D2 et réessaie (max 2 corrections)
4. Si toujours en échec : sauvegarde le `.d2` et signale l'erreur

**Note** : Kroki limite la taille — si > 50 nœuds, découpe en 2 diagrammes complémentaires.

---

## Étape 5 — Récap

Pour chaque diagramme traité, affiche :
```
✅ [<section>] docs/visuals/<nom>.d2 + docs/visuals/<nom>.svg (<taille KB>)
   Type : <flowchart direction:down|right|sequence>
   Nœuds : <N>
```

En cas d'erreur :
```
❌ [<section>] <message d'erreur>
   Code .d2 sauvegardé : docs/visuals/<nom>.d2 (à corriger manuellement)
```

---

## Règles finales

- **Ne modifie jamais** `scripts/webhook_server.py`, `state/`, `config.json` — ce skill est read-only sur le code.
- **Ne crée jamais** de fichiers en dehors de `docs/visuals/`.
- Le `.d2` est le source versionnable — s'il existe déjà, **écrase-le** (on régénère).
- Si l'argument est ambigu, choisis la section de la table et précise ton choix dans le récap.
- Les fichiers `.mmd` (ancien format Mermaid) sont désormais obsolètes — le format actif est `.d2`. Ne pas en créer de nouveaux.
