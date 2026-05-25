---
description: "Gère les articles Medium : /medium new \"Titre\", /medium publish NN https://..., /medium update-index"
---

Invoque l'agent `medium-articles-manager` pour l'action demandée.

**Syntaxe** :
- `/medium new "Titre de l'article"` → crée une branche article + brouillon + issue de tracking
- `/medium publish NN https://medium.com/...` → marque l'article NN comme publié + met à jour l'index
- `/medium update-index` → resynchronise le tableau README avec les fichiers présents

Lance l'agent via le Task tool avec le prompt suivant, en substituant l'action et les arguments :

> Tu es l'agent `medium-articles-manager` (lis ta définition complète dans `.claude/agents/medium-articles-manager.md`). Mode : **interactif** (slash command /medium).
>
> Action demandée : **[ACTION]** — arguments : [ARGS]
>
> Exécute les étapes correspondantes à cette action telles que définies dans ton system prompt. **Ne commite pas** — tu es en mode interactif. Termine par le récap structuré (✅ ...) et la liste "📋 Prochaines étapes" avec les commandes git exactes.
