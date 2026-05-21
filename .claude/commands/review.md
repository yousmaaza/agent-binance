---
description: Review tech lead du diff vs main (ruff/radon/bandit/mypy + commentaire PR)
---

Lance une review tech lead complète sur la branche actuelle.

Invoque l'agent `tech-lead-reviewer` via le Task tool avec le prompt suivant :

> Effectue une review tech lead complète sur la branche Git actuelle. Suit strictement le workflow décrit dans ton system prompt (8 étapes : détection scope, install outils, lancement ruff/radon/bandit/mypy, lecture des fichiers, calcul note maintenabilité, composition du commentaire, persistance dans `reports/reviews/`, post sur la PR si elle existe). Termine par le récap terminal au format exact défini.

L'agent doit faire **tout le travail tout seul** : ne fais rien à sa place avant ou après. Affiche simplement son récap final.
