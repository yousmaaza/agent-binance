# Test de stabilité du seuil 0.5% (Issue #337)

## Objectif
Valider que le seuil de recalibrage TP de 0.5% (ligne 116 de `prompts/position_prompt.txt`) ne génère pas d'oscillations du take-profit autour de ce seuil lors de cycles consécutifs.

## Contexte
Le mécanisme de recalibrage TP dans la PR #331 met à jour le TP si l'écart entre `tp_smart` et `tp_actuel` dépasse 0.5% :

```python
if abs(tp_smart - tp_actuel) / tp_actuel > 0.005:
    pos["tp_price"] = tp_smart
```

Cette vérification doit garantir que le TP ne "oscille" pas (remont up/down alternativement) à cause d'une valeur critique juste au-dessus du seuil.

## Test plan recommandé
- [ ] Lancer 10+ cycles de `/calibrage` consécutifs sur une position test stable
- [ ] Pour chaque cycle, vérifier que `tp_price` n'oscille pas (change toujours dans une seule direction ou reste stable)
- [ ] Vérifier les logs Telegram : aucune séquence "📐 TP recalibré : X → Y" suivi de "📐 TP recalibré : Y → X" sur cycles consécutifs
- [ ] Observer les valeurs `tp_smart` et `tp_actuel` dans les logs de debug pour confirmer qu'elles convergent

## Critique d'acceptation
✅ Le TP converge après 2-3 cycles vers une valeur stable
✅ Aucun oscillation détectée sur 10+ cycles
✅ Les notifications Telegram reflètent des changements monotones ou constants

## Notes
Cette vérification est critère de stabilité pour éviter les oscillations qui pourraient créer du bruit opérationnel ou impacter la stratégie de sortie.
