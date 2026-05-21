# Documentation fonctionnelle — agent-binance

Base documentaire des fonctionnalités du bot Telegram de trading Binance.
Mise à jour automatiquement par l'agent `binance-doc-fonc` à chaque nouvelle feature planifiée.

## Index des fonctionnalités

| Feature | Description courte | Commande(s) Telegram |
|---|---|---|
| [Déclenchement manuel d'un cycle](trade.md) | Analyse le marché immédiatement et place des ordres si les conditions sont favorables | `/trade` |
| [État du portefeuille](status.md) | Affiche le solde, les positions ouvertes et les ordres en attente | `/status` |
| [Rapport de performance](perf.md) | Bilan des trades fermés : taux de réussite, gains, pertes et fiabilité statistique | `/perf` |
| [Explication du dernier cycle](raisonnement.md) | Résumé en français simple des décisions prises lors du dernier cycle | `/raisonnement` |
| [Libération du verrou](reset.md) | Débloque le bot si un cycle s'est arrêté de manière inattendue | `/reset` |
| [Cycle automatique 4h](auto-scheduler.md) | Le bot analyse et trade automatiquement toutes les 4 heures sans intervention | Automatique |

---
*Dernière mise à jour : générée automatiquement par `binance-doc-fonc`.*
