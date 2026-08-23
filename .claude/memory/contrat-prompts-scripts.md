# Le contrat entre les scripts de phase et les prompts

## Ce que c'est

La logique d'un cycle est répartie entre deux mondes :

- des **scripts Python** (`binance-bot/core/phases/*.py`), testés unitairement ;
- des **prompts** (`prompts/phases/*.txt`) exécutés par Claude dans un sous-processus, qui écrivent et lisent les fichiers que ces scripts attendent.

Le contrat repose sur des **chemins en dur des deux côtés** : `/tmp/cycle_{CYCLE_ID}_phaseN_(input|output).json` côté script, `/tmp/cycle___CYCLE_ID___phaseN_...` côté prompt (notation de substitution différente, même chemin).

**Toute modification d'un de ces chemins doit être faite des deux côtés simultanément.** Sinon : `FileNotFoundError` en plein cycle de production, aucun trade exécuté, et rien dans les tests unitaires ne l'aura vu — ils valident chaque script isolément, jamais la jointure.

Depuis l'issue #403, `tests/test_prompt_script_contract.py` vérifie cette cohérence automatiquement.

## Quatre ruptures en une seule journée (22-23/08/2026)

Toutes causées par le **même mécanisme** : un outillage de review automatique corrige un chemin `/tmp` en appliquant la règle bandit **B108** (chemin temporaire prévisible), sans savoir que ce chemin fait partie d'un contrat avec un prompt qu'il ne lit pas.

1. **PR #391** — chemin déplacé vers `state/` dans `phase5_execution.py` seulement, le prompt continuant d'écrire dans `/tmp/`. Aurait cassé la Phase 5 à chaque cycle. Annulé avant merge.
2. **PR #397** — sortie de Phase 5 écrite vers un chemin `tempfile.mkstemp()` imprévisible, alors que le prompt et les Phases 6-8 attendent un chemin fixe. Corrigé pendant la PR.
3. **PR #414** — `phase1_scan.py` passé à `tempfile.gettempdir()`. Ne casse pas *aujourd'hui* car `gettempdir()` renvoie `/tmp` sur la VPS (vérifié : l'unité systemd ne définit ni `TMPDIR` ni `PrivateTmp`), mais introduit une dépendance implicite à l'environnement.
4. **Issue #411** — la formule du TP dupliquée dans `prompts/phases/phase0_snapshot.txt`, qui **annulerait un correctif Python au cycle suivant**, en moins de quatre heures et sans aucune trace.

Les deux premiers ont été rattrapés en review manuelle uniquement. Rien ne garantissait que le suivant le serait — d'où #403.

## La famille est plus large que les chemins

Le cas n°4 et le bug **#385** (`portfolio_total` calculé dans `phase0_snapshot.txt`) montrent que le problème dépasse les chemins de fichiers : **de la logique métier vit dans les prompts**, hors de portée de tout test. Le test de #403 ne couvre que les chemins ; les formules dupliquées restent à vérifier à la main.

Avant de corriger une formule, chercher si elle existe ailleurs — y compris dans `prompts/`. Le TP en est le meilleur exemple : quatre emplacements, dont un dans un prompt.

## Le silencieux bandit est temporaire

Les `# nosec B108` posés sur ces lignes empêchent l'outillage automatique de « corriger » ce qui doit rester stable. Ils sont **provisoires** et doivent être levés quand l'issue **#392** (déplacement propre et coordonné de `/tmp/` vers `state/`, scripts **et** prompts en un seul changement) sera traitée.

Ne pas confondre les **fichiers d'échange éphémères** (`/tmp/cycle_*`) avec les **fichiers d'état persistants** (`state/trade_history.json`, `cycle_log.jsonl`, `tp_watcher_state.json`, `maker_watcher_state.json`, `maker_pending_orders.json`) : ces derniers sont légitimement dans `state/` et ne relèvent pas de ce contrat.

## Détail utile pour faire évoluer le test

Le marqueur `# contract-dynamic` sur une ligne autorise un chemin réellement non résoluble statiquement. Il est **porteur** — le retirer fait échouer le test, ce qui a été vérifié. La charge de la preuve est inversée : un chemin partagé non résoluble **échoue** tant qu'il n'est pas justifié.

À noter au passage : cinq scripts (`phase0_snapshot.py`, `phase0_profit.py`, `phase0_oco_retry.py`, `phase0_trailing_stop.py`, `phase6_next_cycle.py`) écrivent un `_output.json` que leur prompt ne lit jamais — potentiellement du code mort, jamais vérifié.

Voir aussi [[verifier-le-travail-des-agents]].
