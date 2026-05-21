# Rapport de performance

> **Statut** : Disponible
> **Commande** : `/perf`

## Résumé

La commande `/perf` te donne un bilan complet de tous les trades fermés : taux de réussite, gain moyen, perte moyenne et une indication chiffrée sur la fiabilité statistique des résultats.

## Comment l'utiliser

Envoie `/perf` dans le chat Telegram. Le bot lit l'historique des trades et calcule les statistiques en quelques secondes.

### Commandes Telegram

| Commande | Description | Réponse attendue |
|---|---|---|
| `/perf` | Affiche le bilan de performance complet | Un rapport avec win rate, espérance, ratio profit/perte, Sharpe, drawdown max, PnL total et indicateur de fiabilité statistique |

## Cas d'usage

- **Quand** : Tu veux savoir si le bot gagne vraiment de l'argent sur la durée.
  **Résultat** : PnL total en USDC, taux de réussite et espérance par trade.

- **Quand** : Tu veux évaluer si les résultats sont le fruit du hasard ou d'un vrai avantage.
  **Résultat** : Un indicateur de fiabilité statistique (p-value) avec une interprétation simple : `✅ Edge significatif` ou `⚠️ Pas encore significatif`.

- **Quand** : Tu veux voir la perte maximale encaissée en une série.
  **Résultat** : Le drawdown maximum exprimé en USDC.

## Comportement en cas d'erreur

- Moins de 2 trades fermés : `📈 Pas encore assez de trades fermés pour les stats.` avec le nombre actuel et le nombre requis.
- Fichier d'historique absent ou illisible : `❌ Pas encore de données de trading.`
- L'indicateur de fiabilité statistique ne s'affiche que lorsqu'il y a au moins 30 trades fermés ; avant ce seuil, un compteur de progression est affiché.

## Limitations connues

- Les trades encore ouverts ne sont pas inclus dans les statistiques.
- La fiabilité statistique (p-value) nécessite au moins 30 trades fermés pour être précise. En dessous, seul le compteur de progression est visible.
- Le Sharpe est annualisé en supposant 6 cycles de 4 heures par jour, ce qui correspond au rythme maximal du bot.

## Liens

- Doc technique : [SPEC.md](../technique/SPEC.md)
