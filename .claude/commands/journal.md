---
description: Génère le récap du jour pour Medium (PR mergées + issues + tickets) dans docs/medium-journal.md
---

Lance l'agent `daily-recap` pour produire le récap du jour.

Invoque l'agent via le Task tool avec le prompt suivant :

> Tu es l'agent `daily-recap` (lis ta définition complète dans `.claude/agents/daily-recap.md`). Mode : **interactif** (lancé via /journal par l'utilisateur).
>
> Exécute les 8 étapes obligatoires de ton workflow :
> 1. Détermine la date du jour (Europe/Paris).
> 2. Récupère les PR mergées aujourd'hui via `gh pr list`.
> 3. Pour chaque PR, lis la doc tech associée si elle existe (`docs/technique/pr-N-*.md`).
> 4. Récupère issues fermées + issues créées aujourd'hui.
> 5. Lis `docs/medium-journal.md` et détecte si une entrée du jour existe déjà.
> 6. Compose l'entrée du jour (création ou enrichissement) selon le format strict.
> 7. Écris dans `docs/medium-journal.md` (insertion en tête ou remplacement).
> 8. **Ne commits pas** — mode interactif. L'utilisateur relira avant de pousser.
>
> Termine par le récap structuré (✅ Journal mis à jour — ...) défini dans ton system prompt.

L'agent fait tout le travail. Affiche simplement son récap final à l'utilisateur.
