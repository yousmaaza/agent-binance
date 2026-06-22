# PR #256 — feat: commande Telegram /calibrage pour déclencher le cycle position

> **Mergée le** : 2026-06-22
> **Branche** : `feat/issue-254-calibrage-command`
> **Issues** : #254

## Contexte

La PR #241 a introduit un auto-scheduler 1h pour les cycles de gestion des positions (`run_position_check_workflow`). Cependant, l'utilisateur n'avait aucun moyen de déclencher manuellement ce cycle à la demande — contrairement aux cycles `/trade` qui peuvent être lancés n'importe quand via la commande `/trade`.

Cette PR expose la commande `/calibrage` pour permettre un lancement manuel immédiat du cycle position, cohérent avec le pattern des autres commandes.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `binance-bot/webhook_server.py` | Modification | Ajout du handler `/calibrage` dans la dispatch de commandes |

### Fonctions modifiées

| Fonction | Action | Description |
|---|---|---|
| `main_loop()` → handler `/calibrage` | Ajoutée | Intercepte la commande texte `/calibrage`, envoie un message immédiat au chat, puis lance `run_position_check_workflow(trigger='manual')` en thread daemon |

### Changements détaillés

**Lignes 71 & 154** : Mise à jour du message de boot et du message par défaut pour inclure `/calibrage` dans la liste des commandes affichée.

**Lignes 142–148** : Nouveau handler :
```python
elif text.startswith("/calibrage"):
    send_telegram("⚙️ Calibrage des positions en cours...")
    threading.Thread(
        target=run_position_check_workflow,
        kwargs={"trigger": "manual"},
        daemon=True,
    ).start()
```

Le handler suit le même pattern que `/trade` et autres commandes existantes :
1. Envoi immédiat d'un message de confirmation (`"⚙️ Calibrage des positions en cours..."`)
2. Lancement du workflow en thread daemon pour ne pas bloquer la boucle de polling Telegram
3. Passage de `trigger='manual'` pour que le workflow sache qu'il a été déclenché manuellement (utile pour les logs et les notifications)

## Décisions techniques notables

- **Confirmation immédiate** : contrairement à `/trade`, qui ne passait pas de message avant de lancer le workflow, `/calibrage` envoie une confirmation pour signaler que la commande a été reçue — le workflow enverra son résumé détaillé à la fin via le mécanisme existant de MongoDB + Telegram.
- **Thread daemon** : cohérent avec toutes les autres commandes ; le process principal ne s'attend pas à terminer le workflow avant de continuer.
- **`trigger='manual'`** : permet à `run_position_check_workflow` de distinguer les lancements manuels des lancements auto (scheduler), ce qui peut affecter les logs et les notifications.

## Impact sur l'architecture

Changement **très isolé** : aucun impact architectural. L'ajout d'une nouvelle commande dispatcher ne modifie pas :
- Le flux de données (polling → dispatch → handler) — le pattern existe déjà
- Les workflows (position_check et trade) — pas de modification
- Les composants externes (Telegram, Binance, MongoDB)
- L'auto-scheduler (qui continue à fonctionner indépendamment)

Cette PR fournit simplement un **point d'entrée manuel** pour une fonctionnalité déjà existante (le cycle de gestion des positions).

## Références CLAUDE.md respectées

- **"Tous les appels Telegram passent par `curl` via subprocess"** : le handler utilise `send_telegram()`, qui utilise lui-même `tg_post()` via curl — conforme.
- **"Modifications chirurgicales"** : uniquement 2 lignes modifiées dans le message de boot/par défaut, et un nouveau bloc handler inséré. Pas de refactoring non demandé.
- **"Code minimum qui résout le problème"** : 7 lignes pour le handler, sans abstraction spéculative.
- **"Threading daemon pour les workflows"** : cohérent avec le pattern `/trade` et autres commandes existantes.
