# Libération du verrou en cas de cycle bloqué

> **Statut** : Disponible
> **Commande** : `/reset`

## Résumé

La commande `/reset` débloque le bot lorsqu'un cycle de trading s'est arrêté de manière inattendue et que le bot refuse de relancer une nouvelle analyse en affichant "Un cycle est déjà en cours".

## Comment l'utiliser

Envoie `/reset` dans le chat Telegram. Le bot libère le verrou immédiatement et te confirme que tout est revenu à la normale.

### Commandes Telegram

| Commande | Description | Réponse attendue |
|---|---|---|
| `/reset` | Libère le verrou de cycle bloqué | `🔓 Lock réinitialisé.` suivi de l'heure du prochain cycle automatique |

## Cas d'usage

- **Quand** : Le bot répond `⏳ Un cycle est déjà en cours` mais aucun cycle n'est visiblement en train de tourner depuis plus de quelques minutes.
  **Résultat** : Le verrou est libéré et tu peux relancer `/trade` ou attendre le prochain cycle automatique.

- **Quand** : Le bot a reçu une erreur grave et le verrou n'a pas été libéré automatiquement.
  **Résultat** : Le bot est de nouveau opérationnel.

## Comportement en cas d'erreur

La commande `/reset` ne peut pas échouer : elle réinitialise simplement un fichier interne. Si le verrou est déjà libéré, la commande fonctionne quand même sans effet négatif.

## Limitations connues

- Le `/reset` ne reporte pas ce qui a planté dans le cycle précédent. Pour comprendre la cause du blocage, consulte les logs : envoie `/raisonnement` ou vérifie les fichiers dans `logs/stderr/`.
- Le verrou se libère aussi automatiquement au bout de 2 heures sans activité — le `/reset` permet simplement de ne pas attendre ce délai.
- Si un cycle est vraiment encore en train de tourner et que tu fais `/reset`, le prochain `/trade` lancera un deuxième cycle en parallèle. À n'utiliser que si tu es sûr que le cycle précédent est réellement coincé.

## Liens

- Doc technique : [SPEC.md](../technique/SPEC.md)
