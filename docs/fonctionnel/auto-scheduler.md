# Cycle automatique toutes les 4 heures

> **Statut** : Disponible
> **Commande** : Automatique

## Résumé

Le bot se déclenche automatiquement toutes les 4 heures pour analyser le marché et placer des ordres si les conditions sont bonnes — sans que tu aies à faire quoi que ce soit.

## Comment l'utiliser

Aucune action requise. Dès que le bot est démarré, il planifie lui-même les cycles automatiques. Les horaires de déclenchement sont fixes et alignés sur les grandes périodes d'analyse des marchés : environ 02h05, 06h05, 10h05, 14h05, 18h05 et 22h05 (en heure de Paris, l'heure exacte dépend du décalage UTC du moment).

### Commandes Telegram

Cette feature est automatique — aucune commande requise.

Tu peux consulter l'heure du prochain cycle avec `/status`.

## Cas d'usage

- **Quand** : Le bot est démarré et tourne en arrière-plan.
  **Résultat** : Toutes les 4 heures, le bot analyse le marché et te notifie via Telegram du résultat, exactement comme si tu avais envoyé `/trade` manuellement.

- **Quand** : Tu as laissé le bot tourner la nuit.
  **Résultat** : Le matin, tu retrouves les notifications des cycles nocturnes avec les décisions prises et les ordres éventuellement passés.

## Comportement en cas d'erreur

- Si un cycle manuel est en cours au moment du déclenchement automatique, le cycle automatique est ignoré pour ce créneau et sera relancé au suivant.
- Si le bot rencontre une erreur lors du cycle automatique, il t'envoie la même notification d'erreur que pour un `/trade` manuel.

## Limitations connues

- Les cycles automatiques ne se déclenchent que si le bot est démarré. Si le bot est arrêté (redémarrage du Mac, coupure de courant, etc.), aucun cycle ne tourne pendant l'arrêt.
- Il n'est pas possible de changer les horaires de déclenchement depuis Telegram — ils sont définis dans la configuration du bot.
- Si deux créneaux consécutifs échouent, aucun mécanisme de rattrapage n'est prévu : le bot reprend simplement au créneau suivant.

## Liens

- Doc technique : [SPEC.md](../technique/SPEC.md)
