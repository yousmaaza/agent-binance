# Le ratio gain/risque réel est de 1,20 — pas les 2,0 configurés

## Le constat

`reward_risk_ratio` vaut `2.0` dans `config.json`, mais le ratio **réellement obtenu**, mesuré sur l'historique complet, est de **1,20**.

```
gain moyen     brut +3,03  →  net +2,22
perte moyenne  brut  1,23  →  net  1,84
```

Les frais **dégradent les deux côtés à la fois** : ils s'ajoutent aux pertes et se soustraient aux gains. Le ratio se dégrade donc bien plus vite que l'intuition ne le suggère. En théorie pure, avec 0,9 % de frais aller-retour :

| Stop | TP | Perte nette | Gain net | R:R réel |
|---|---|---|---|---|
| 3 % | 6 % | 3,90 % | 5,10 % | **1,31** |
| 5 % | 10 % | 5,90 % | 9,10 % | **1,54** |
| 7 % | 14 % | 7,90 % | 13,10 % | **1,66** |

La stratégie n'a donc jamais fonctionné selon ses propres paramètres.

## La décision prise (2026-08-23)

Viser **1,5:1 net** plutôt que 2:1 fictif, avec la valeur maintenue **paramétrable**.

`reward_risk_ratio` reste la clé de configuration mais **change de sémantique** : elle était interprétée comme un ratio brut, elle devient un ratio net de frais. Même type de bascule que `pnl_usdc` avec #382 — voir [[pnl-net-semantique]].

**Pourquoi 1,5 et pas 2,0** : restaurer un vrai 2:1 net exigerait un TP à +8,7 % pour un stop de 3 % (contre +6 % aujourd'hui), une cible nettement moins souvent atteinte et souvent au-delà de la résistance 4h, donc immédiatement replafonnée par le mécanisme de recalibrage. À 1,5:1 net, le TP se situe à **+6,75 %** — à peine plus haut que l'actuel, donc réaliste.

Un second paramètre, `fee_round_trip_pct` (valeur de départ 0,009), porte l'estimation du coût aller-retour. Configurable parce que le palier Kraken peut changer et que la part réelle d'exécutions maker n'est pas encore connue.

## Les deux formules à corriger ensemble

Le défaut est symétrique — la cible **et** le dimensionnement l'ignorent tous deux :

```python
# dimensionnement (phase4_sizing.py) — la perte réelle doit rentrer dans le budget
quantite = risk_usdc / (prix_entry * (stop_distance_pct + frais_aller_retour))

# cible — le gain net doit respecter le ratio
prix_tp = prix_entry * (1 + (stop_distance_pct + frais) * reward_risk_ratio + frais)
```

Preuve du défaut de dimensionnement : la position ADA du 23/08 avait un budget de risque de **9,28 USDC** et a perdu **11,01 USDC** — dépassement de 19 %, entièrement dû aux frais, avec un glissement au stop négligeable (0,081 %).

## Le piège : le TP est calculé à QUATRE endroits, dont un dans un prompt

- `binance-bot/core/phases/phase4_sizing.py`
- `binance-bot/core/phases/phase5_execution.py`
- `binance-bot/core/maker_watcher.py`
- **`prompts/phases/phase0_snapshot.txt`** — bloc « RECALIBRAGE TP (Smart TP automatique) »

Ce quatrième emplacement recalibre le TP **à chaque cycle** sur toutes les positions ouvertes. Si une correction ne touche que les trois fichiers Python, **la Phase 0 remet l'ancienne formule au cycle suivant**, soit moins de quatre heures après, sans erreur ni trace. Voir [[contrat-prompts-scripts]].

## Le plafond de résistance limite la portée de tout correctif

La règle de recalibrage plafonne le TP : `tp_smart = min(tp_mecanique, r2_4h × 0.98)`.

**31 % des positions (27 sur 86) ont un TP inférieur à la cible mécanique**, avec des écarts jusqu'à −10 %. Sur ces cas, relever la formule n'aura aucun effet — c'est le plafond qui décide.

Pire, ce plafonnement ne vérifie ni les frais ni même la rentabilité : **six positions sur 86 avaient un TP dont l'atteinte aurait fait perdre de l'argent**, dont quatre carrément sous le prix d'entrée (XRP le 19/08 : TP à −5,28 %). La condition `r2_4h > entry_price` existe, mais elle compare la résistance brute à l'entrée **avant** le rabais de 2 % et sans marge de frais. Il manque un **plancher** garantissant que le TP couvre au moins l'entrée plus les frais.

Tout ceci est consigné dans l'issue **#411**, entièrement spécifiée et sans question ouverte.
