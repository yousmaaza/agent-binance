# PR #143 — Vérifier la définition des variables Phase 3/5/6 en trade_prompt

> **Mergée le** : 2026-05-28
> **Branche** : `feat/issue-125-verifier-variables-phase-8`
> **Issues** : #125

## Contexte

Phase 8 (CYCLE LOG JSONL) utilise un ensemble de variables de synthèse (`top_score`, `executed`, `skipped`, `skip_type`, `skip_detail`, `sentiment`, `portfolio_total`, `open_positions`) qui sont censées être définies et mises à jour par les phases précédentes. Cependant, le prompt ne les initialisait pas explicitement ni ne spécifiait clairement :
- **où** chaque variable doit être définie
- **quand** elle doit être mise à jour
- **quel fallback** utiliser en cas d'erreur

Cette ambiguïté pouvait entraîner des `UnboundLocalError` en Phase 8 si une phase précédente échouait partiellement.

## Changements

### Fichiers modifiés

| Fichier | Type de changement | Impact |
|---|---|---|
| `prompts/trade_prompt.txt` | Modification | Ajout initialisations explicites + instructions claires de tracking |

### Structure des modifications

**1. Initialisation explicite (bloc Python au démarrage, après Phase 0)**
```python
# Initialisation des variables de synthèse (utilisées par Phase 8)
top_score = 0
executed = 0
skipped = 0
skip_type = None
skip_detail = None
sentiment = "Neutral"
portfolio_total = 0.0
open_positions = 0
```

Ces fallbacks garantissent que même si une phase échoue, Phase 8 peut écrire un document minimal sans erreur UnboundLocalError.

**2. Phase 3 — Scoring et sélection** (nouvelles instructions)
Ajout d'un bloc explicite de mise à jour des variables après le calcul des scores :
- `top_score = score maximum parmi tous les coins analysés (0-10)`
- `skipped = nombre de coins avec décision == "SKIP"`
- `skip_type = classification du skip principal (TYPE_A/B/C/D ou None)`
- `skip_detail = phrase courte décrivant la raison du skip`

**3. Phase 5 — Exécution automatique** (nouvelles instructions)
Ajout d'un bloc explicite après le traitement de tous les ordres :
- `executed = len(orders_placed) — nombre d'ordres BUY MARKET passés`
- `open_positions = nombre de trades status="open" dans trade_history.json après cette phase`

**4. Phase 8 — CYCLE LOG JSONL** (rédaction clarifiée)
Documentation textuelle complète explicitant :
- La liste de toutes les variables attendues
- Où chaque variable est définie et trackée
- Le format JSON à écrire dans `state/cycle_log.jsonl`
- Le processus complet d'écriture (lire, ajouter, tronquer à 90 lignes, réécrire)

## Décisions techniques notables

- **Initialisation fallback** : placée après les helpers heartbeat (`tg()` et `hb()`) et avant Phase 0, elle est garantie d'être exécutée quoi qu'il advienne. Si une phase échoue, les valeurs restent à leurs fallbacks (0, None, "Neutral").
  
- **Type classification en Phase 3** : le tri par type de skip (TYPE_A/B/C/D) force le prompt à expliciter **pourquoi** un coin est skippé, ce qui améliore la debuggabilité et le reporting post-cycle.

- **Pas de recalcul tardif** : les variables sont mises à jour au moment où la décision est prise (Phase 3, Phase 5), pas rétroactivement en Phase 8. Ceci élimine les risques de désynchronisation.

## Impact sur l'architecture

Changement isolé sur le prompt, sans impact architectural. La structure des 7 phases reste inchangée. L'effet visible :
- **Robustesse** : Phase 8 ne peut plus échouer sur UnboundLocalError
- **Traçabilité** : les décisions de skip et leurs raisons sont dorénavant explicitement documentées dans le JSONL
- **Testabilité** : chaque variable a un point d'assignation clair, facilitant le debug de cycles incomplets

## Références CLAUDE.md respectées

- **Aucune modification applicative** : le changement est entièrement dans `prompts/trade_prompt.txt`, aucun code Python n'est ajouté à `scripts/`
- **Nouvelles variables bien documentées** : le comportement de `skip_type` et `skip_detail` est conforme à la classification définie en CLAUDE.md §"Cycles de trading : skip_type et skip_detail"
- **Format JSONL conforme** : les variables écrites dans `state/cycle_log.jsonl` respectent la structure définie en CLAUDE.md
