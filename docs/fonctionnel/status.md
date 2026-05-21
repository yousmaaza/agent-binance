# État du portefeuille et ordres ouverts

> **Statut** : Disponible
> **Commande** : `/status`

## Résumé

La commande `/status` affiche en un coup d'œil l'état de ton portefeuille Binance : argent disponible, positions en cours, ordres actifs et heure du prochain cycle automatique.

## Comment l'utiliser

Envoie `/status` dans le chat Telegram. Le bot interroge Binance en temps réel et te répond en quelques secondes avec un tableau de bord complet.

### Commandes Telegram

| Commande | Description | Réponse attendue |
|---|---|---|
| `/status` | Affiche le portefeuille et les ordres en cours | Un message structuré avec USDC disponible, positions, ordres ouverts et prochain cycle |

## Cas d'usage

- **Quand** : Tu veux savoir combien d'argent est disponible avant de lancer un `/trade` manuel.
  **Résultat** : Le montant USDC libre et le budget effectivement utilisable par le bot (40 % du solde libre).

- **Quand** : Tu veux vérifier quels ordres sont en attente sur Binance.
  **Résultat** : La liste des ordres ouverts avec le coin, le type d'ordre, le prix cible et la quantité.

- **Quand** : Tu veux savoir quand aura lieu le prochain cycle automatique.
  **Résultat** : L'heure du prochain cycle affichée en heure locale.

## Comportement en cas d'erreur

- Si Binance est injoignable ou retourne une erreur : `❌ Erreur /status : {message d'erreur}`.

## Limitations connues

- Le budget affiché (40 % du USDC libre) est calculé à l'instant de la requête — il peut différer du budget réel utilisé lors du dernier cycle si des ordres ont été placés entre-temps.
- Seuls les 8 premiers ordres ouverts sont affichés pour garder le message lisible.
- Les crypto verrouillées en staking Binance (préfixe `LD`) sont exclues de l'affichage des positions.

## Liens

- Doc technique : [SPEC.md](../technique/SPEC.md)
