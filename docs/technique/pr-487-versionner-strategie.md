# PR #487 — Versionner le document de stratégie et le tenir à jour

> **Mergée le** : 2026-09-11
> **Branche** : `feat/issue-486-doc-strategie`
> **Issues** : #486

## Contexte

Le document "La mécanique du bot" (`docs/strategie.html`) décrivait historiquement la stratégie de trading : formules des 8 phases, rôle de chaque paramètre `config.json`, mesures justifiant les valeurs retenues. Mais il n'existait que comme artefact publié en dehors du dépôt — non versionné, non relu en PR, non synchronisé avec les modifications de code.

Conséquence observable : le 07/09, `atr_stop_multiplier` est passé de 3,5 à 1,75 sans que rien n'oblige la mise à jour du document. La dérive s'accumule.

Cette PR instaure une **source unique de vérité** (HTML) avec génération automatique d'une version markdown diffable en PR, et ajoute une règle CLAUDE.md pour empêcher la divergence future.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `CLAUDE.md` | Modification | Ajout règle 8 : toute PR touchant une formule des phases 0/3/4/5 ou une clé config doit mettre à jour la doc stratégie |
| `docs/strategie.html` | Création | **Source unique** : document HTML complet décrivant les phases, formules, paramètres. Source de publication de l'artefact. État du 08/09 : `atr_stop_multiplier = 1,75` |
| `docs/strategie.md` | Création | **Généré** : markdown diffable en PR, jamais édité à la main. Figures SVG remplacées par diagrammes mermaid |
| `scripts/strategie_to_md.py` | Création | Convertisseur HTML → markdown. Modes : `-` (régénère) et `--check` (échoue si périmé, utile en CI) |

### Nouvelles fonctions / scripts

| Élément | Action | Description |
|---|---|---|
| `scripts/strategie_to_md.py` | Créé | Orchestrateur : lit `docs/strategie.html`, parse les sections H2/H3, convertit les formules et tableaux HTML en markdown monospace, remplace les 3 figures SVG par des diagrammes mermaid définis en constante, génère ou valide `docs/strategie.md` |

## Décisions techniques notables

- **Source unique = HTML** : choix d'une seule source de vérité (`.html`) plutôt que d'éditer le `.md` directement. Raison : le HTML peut être généré ou mis en forme pour la publication, le markdown est diffable et reviewable en PR. Même pattern que `docs/visuals/` (SVG générés depuis D2/Mermaid).

- **Figures remplacées par mermaid** : les trois diagrammes SVG du HTML n'ont pas d'équivalent markdown statique performant. Ils sont donc remplacés par leurs sources mermaid inline dans le markdown (plus léger, lisible sur GitHub directement, pas d'image binaire en diff).

- **Mode `--check` en CI** : permet de valider en pipeline que le markdown est à jour avec le HTML, prévenant la divergence silencieuse.

- **Pas de régénération automatique** : le dev doit appeler `python scripts/strategie_to_md.py` manuellement après chaque modification du HTML (le reverse-engineering automatique du HTML → markdown serait fragile). CLAUDE.md règle 8 l'impose explicitement.

## Impact sur l'architecture

**Changement isolé, pas d'impact sur l'architecture globale du bot.**

L'ajout de la règle 8 modifie le workflow des PRs futures : toute modification d'une formule de phase ou d'un paramètre stratégique devra maintenant inclure une mise à jour de `docs/strategie.html` (et sa régénération `.md`). Cela n'affecte ni le runtime du webhook_server.py ni les phases elles-mêmes — c'est une obligation de documentation.

## Références CLAUDE.md respectées

- **Règle 2 (PROJECT_DIR dynamique)** : `scripts/strategie_to_md.py:19` utilise `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` pour calculer le chemin de projet de manière portable (Mac dev → VPS prod).

- **Règle 8 (Nouvelle)** : la PR elle-même matérialise la règle 8. Elle énumère les clés `config.json` affectant la stratégie et les phases concernées (0, 3, 4, 5), donnant aux futurs développeurs une liste de contrôle claire.

- **Minimalisme (CLAUDE.md Principes généraux)** : `scripts/strategie_to_md.py` fait strictement la conversion HTML → markdown, sans abstraction ni traitement spéculatif. Le module `texte()` encapsule 3 transformations répétées (balises HTML → markdown, entités XML → caractères, espaces).

---

## Annexe : Structure du script `strategie_to_md.py`

```python
# Constantes
SOURCE = docs/strategie.html
CIBLE = docs/strategie.md
MERMAID = {0: flowchart scan/score/sizing/exec, 1: flowchart scoring, 2: flowchart maker_exit}

# Fonctions utilitaires
texte(s)      # HTML inline → markdown
bloc_pre(s)   # Formules monospace → conserve sauts de ligne
table(t)      # <table> HTML → markdown

# Flux principal
1. Charge docs/strategie.html
2. Extrait <div class="sheet"> (corps rédactionnel)
3. Regex les blocs par type (h2, h3, p, figure, table, etc.)
4. Pour chaque bloc :
   - Si <figure> : remplace par le mermaid correspondant (i_fig)
   - Si <table> : convertit en markdown
   - Sinon : extrait le texte et convertit inline HTML/entities
5. Écrit en markdown ou valide (mode --check)
```

