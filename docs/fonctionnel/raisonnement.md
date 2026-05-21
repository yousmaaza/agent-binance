# Explication du dernier cycle

> **Statut** : Disponible (nécessite MongoDB configuré)
> **Commande** : `/raisonnement`

## Résumé

La commande `/raisonnement` t'explique en langage simple ce que le bot a fait lors de son dernier cycle : pourquoi il a acheté (ou pas), quel était l'état du marché, et combien de positions ont été ouvertes.

## Comment l'utiliser

Envoie `/raisonnement` dans le chat Telegram. Le bot récupère les données du dernier cycle enregistré et te les résume en quelques secondes.

### Commandes Telegram

| Commande | Description | Réponse attendue |
|---|---|---|
| `/raisonnement` | Affiche l'explication du dernier cycle de trading | Un résumé avec le sentiment du marché, le portefeuille, les ordres placés et une explication en français |

## Cas d'usage

- **Quand** : Le bot vient de finir un cycle et tu veux comprendre ses décisions sans lire les logs techniques.
  **Résultat** : Un paragraphe en français clair expliquant la météo du marché et pourquoi des ordres ont (ou n'ont pas) été passés.

- **Quand** : Tu veux vérifier si le bot a bien analysé le marché ce matin.
  **Résultat** : L'identifiant du cycle, l'heure, le sentiment global (haussier, neutre, baissier) et la liste des coins achetés.

## Comportement en cas d'erreur

- Si MongoDB n'est pas configuré dans le fichier `.env` : `⚠️ MongoDB non configuré (MONGODB_URI absent ou invalide dans .env).`
- Si aucun cycle n'a encore été enregistré : `📭 Aucun cycle en base. Lance /trade pour générer le premier.`
- Si la connexion à la base de données échoue : `❌ Erreur Mongo : {message d'erreur}`.

## Limitations connues

- Cette commande ne fonctionne que si la variable `MONGODB_URI` est configurée dans le fichier `.env`. Sans base de données, aucune explication n'est disponible.
- Seul le dernier cycle est affiché. Pour consulter les cycles précédents, il faut accéder directement à la base de données.
- Si le dernier cycle a planté avant la fin, l'explication disponible sera minimaliste : "Le cycle a échoué avant de produire un résultat exploitable."

## Liens

- Doc technique : [SPEC.md](../technique/SPEC.md)
