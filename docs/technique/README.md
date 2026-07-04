# Documentation technique — agent-binance

Documentation technique du projet, mise à jour automatiquement par l'agent `binance-doc-tech`.

## Documents

| Document | Description | Dernière mise à jour |
|---|---|---|
| [SPEC.md](SPEC.md) | Spécification technique complète : architecture, composants, fonctions clés, état persistant, contraintes | 2026-07-04 |

## Diagrammes

Générés automatiquement via `/generate-diagrams` (D2 + Kroki.io). Sources dans `docs/visuals/*.d2`.

| Diagramme | Source D2 | SVG |
|---|---|---|
| Architecture globale | [`../visuals/architecture.d2`](../visuals/architecture.d2) | [`../visuals/architecture.svg`](../visuals/architecture.svg) |
| Flux de données | [`../visuals/data-flow.d2`](../visuals/data-flow.d2) | [`../visuals/data-flow.svg`](../visuals/data-flow.svg) |
| Commandes Telegram | [`../visuals/commands.d2`](../visuals/commands.d2) | [`../visuals/commands.svg`](../visuals/commands.svg) |
| Phases du cycle | [`../visuals/trade-phases.d2`](../visuals/trade-phases.d2) | [`../visuals/trade-phases.svg`](../visuals/trade-phases.svg) |
| Séquence /trade | [`../visuals/trade.d2`](../visuals/trade.d2) | [`../visuals/trade.svg`](../visuals/trade.svg) |
| Auto-scheduler | [`../visuals/auto-scheduler.d2`](../visuals/auto-scheduler.d2) | [`../visuals/auto-scheduler.svg`](../visuals/auto-scheduler.svg) |

## Historique technique par PR

| PR | Titre | Date |
|---|---|---|
| [#327](pr-327-tp-intelligent-base-sur-les-resistances.md) | [M1] TP intelligent basé sur les résistances TradingView (Phase 4) | 2026-07-04 |
| [#326](pr-326-phase2-combined-analysis.md) | [M1] Migrer Phase 2 de coin_analysis vers combined_analysis (4h) | 2026-07-04 |
| [#323](pr-323-enrichir-status-tp-watcher.md) | Enrichir /status avec état TP Watcher et prix courant vs TP | 2026-07-04 |
| [#321](pr-321-ajouter-thread-watcher-tp-temps-reel.md) | [FEAT] Ajouter thread watcher take profit temps réel | 2026-07-03 |
| [#317](pr-317-score-par-coin-phase-3.md) | [FEAT] Afficher le score par coin dans le rapport Phase 3 | 2026-07-03 |
| [#316](pr-316-fix-phase5-nonetype-guard.md) | [BUG] Fix phase5_execution.py crash TypeError quand trade=None (0 ordres) | 2026-07-03 |
| [#312](pr-312-refactor-phase1-kraken-usdc.md) | [M1] Refactorer Phase 1 — univers depuis Kraken USDC + seuil 1M | 2026-07-03 |
| [#310](pr-310-mettre-a-jour-config-kraken.md) | [M291] Mettre à jour config.json pour Kraken (coins + suppression binance_profile) | 2026-07-03 |
| [#305](pr-305-mettre-jour-prompts-api-reference-kraken.md) | [M5] Mettre à jour les prompts et api_reference pour Kraken | 2026-07-03 |
| [#304](pr-304-ajouter-unittests-fonctions.md) | [M0] Ajouter unittests pour fonctions utilitaires | 2026-07-03 |
| [#303](pr-303-phase0-structured-logs.md) | Ajouter logs structurés pour traçabilité (Phase 0) | 2026-07-03 |
| [#298](pr-298-kraken-json-parsing.md) | [M4] Migrer parsing réponses JSON Binance → Kraken (phase0_profit) | 2026-07-03 |
| [#296](pr-296-kraken-bracket-orders.md) | [M3] Migrer OCO Binance vers bracket orders Kraken | 2026-07-03 |
| [#295](pr-295-kraken-market-filters.md) | [M3] Adapter les filtres de marché Binance LOT_SIZE → Kraken | 2026-07-03 |
| [#294](pr-294-adapter-cli-kraken.md) | [M286] Adapter les appels CLI de lecture vers Kraken | 2026-07-03 |
| [#293](pr-293-remplacer-binance-cli-par-kraken.md) | [M285] Remplacer binance-cli par kraken-cli dans la couche de détection | 2026-07-03 |
| [#302](pr-302-migrer-helpers-position.md) | Refactor : éliminer duplication trade_helpers ↔ position_helpers via ré-export symétrique | 2026-07-03 |
| [#270](pr-270-refacto-externaliser-helpers-python-modules.md) | [REFACTO] Externaliser helpers Python en modules et découper trade_prompt par phase | 2026-07-03 |
| [#268](pr-268-config-min-order-usdc.md) | [M1] Réduire min_order_usdc de 11 à 9 USDC | 2026-06-29 |
| [#267](pr-267-fix-phase0-bugs.md) | [M1] fix(Phase 0) — comptage open_positions, retry OCO + close_reason | 2026-06-28 |
| [#263](pr-263-position-prompt-binance-cli-fix.md) | [BUG] position_prompt.txt : mauvaises commandes binance-cli et mauvais noms de champs | 2026-06-28 |
| [#265](pr-265-supprimer-vars-claude-code.md) | [BUG] Supprimer vars CLAUDE_CODE_* du sous-processus claude | 2026-06-24 |
| [#260](pr-260-refactor-phase0-calibrage.md) | [M259] Refactoriser : supprimer cycle horaire position, intégrer calibrage en Phase 0 | 2026-06-23 |
| [#257](pr-257-position-oco-manuels.md) | [M255] Inclure les OCO manuels Binance dans le cycle position | 2026-06-22 |
| [#256](pr-256-calibrage-command.md) | feat: commande Telegram /calibrage pour déclencher le cycle position | 2026-06-22 |
| [#241](pr-241-cycle-position-horaire.md) | [M239] Cycle horaire de gestion des positions ouvertes (POSITION_PROMPT) | 2026-06-22 |
| [#242](pr-242-rec-auto-workflow.md) | feat: tickets [REC] via REC-AUTO + binance-dev sur branche PR existante | 2026-06-22 |
| [#238](pr-238-trade-prompt-disallow-skills.md) | [M237] fix: TRADE_PROMPT disallows skill invocation | 2026-06-22 |
| [#235](pr-235-augmente-max-single-position.md) | [M218] Augmente max_single_position_pct de 0.40 à 0.65 | 2026-06-15 |
| [#234](pr-234-fix-tradingview-mcp-tools-v2.md) | [M232] Fix outils MCP TradingView — restaurer atilaahmettaner | 2026-06-14 |
| [#231](pr-231-consolidation-rec-auto.md) | [CONSOLIDATION MAJEURE] Refactoring v2 — modularisation + extraction TRADE_PROMPT + agents CI/CD | 2026-06-14 |
| [#201](pr-201-enrichir-claude-md.md) | Enrichir CLAUDE.md avec principes généraux de développement | 2026-06-03 |
| [#194](pr-194-phase-2-1d-rate-limit-handling.md) | Phase 2 : sleep 15s post-batch 4h + gestion erreur 1D silencieuse | 2026-05-31 |
| [#187](pr-187-consolidate-helpers-security-recs.md) | [CONSOLIDÉ] Helpers partagés par cycle + sécurité + recommandations tech lead | 2026-05-30 |
| [#166](pr-166-consolidation-145-146-147-148-149.md) | [CONSOLIDATION] Atomic writes + Heartbeats + JSON unification + Python venv + binance-cli docs | 2026-05-29 |
| [#17](pr-17-rotation-loguru-daemon-log.md) | [M1] Activer rotation loguru sur state/daemon.log (10 MB, retention 5) | 2026-05-21 |
| [#21](pr-21-differencer-notif-telegram-manual-vs-auto.md) | [M2] Différencier notif Telegram manual vs auto au démarrage de cycle | 2026-05-21 |
| [#22](pr-22-ajout-prompt-version-sha1-mongo.md) | [M1] Ajouter PROMPT_VERSION (sha1) dans Mongo cycles | 2026-05-21 |
| [#23](pr-23-heartbeats-par-phase-jsonl.md) | [M2] Heartbeats par phase en JSONL (logs/cycle_<id>_phases.jsonl) | 2026-05-21 |
| [#28](pr-28-supprimer-double-handler-loguru-daemon.md) | [REC] Supprimer le double handler loguru sur state/daemon.log | 2026-05-21 |
| [#36](pr-36-uniformiser-accents-logger-boot.md) | [REC] Uniformiser les accents dans les messages logger de boot | 2026-05-21 |
| [#39](pr-39-phase5-buy-market-oco-protection.md) | [BUG] Phase 5 — Remplacer OTOCO par BUY MARKET + OCO immédiat | 2026-05-22 |
| [#46](pr-46-prompt-version-fallback-mongo-erreur.md) | [REC] Ajouter prompt_version dans le fallback Mongo erreur | 2026-05-22 |
| [#48](pr-48-suivre-le-cout-api-par-cycle.md) | [M1] Suivre le cout API par cycle et exposer via /cout | 2026-05-22 |
| [#50](pr-50-fallback-abonnement-api-sonnet.md) | [M1] Fallback abonnement→API Sonnet si ressource insuffisante | 2026-05-22 |
| [#56](pr-56-trailing-stop-remonter-stop-loss.md) | [M1] Phase 0 — Trailing stop : remonter le stop-loss si le prix a progressé | 2026-05-22 |
| [#65](pr-65-session-limit-fallback-pattern.md) | [hotfix] Ajouter "session limit" dans _RESOURCE_ERROR_PATTERNS | 2026-05-22 |
| [#80](pr-80-config-llm-sonnet-abonnement-api.md) | [M79] Forcer claude-sonnet-4-6 sur abonnement et API fallback | 2026-05-23 |
| [#82](pr-82-afficher-modele-mode-notif-cycle.md) | [M81] Afficher modèle et mode (abonnement/API) dans les notifications de cycle | 2026-05-23 |
| [#87](pr-87-migrer-agents-workflows-haiku.md) | [M86] Migrer agents et workflows CI/CD vers claude-haiku | 2026-05-23 |
| [#91](pr-91-commande-eval.md) | [M90] Commande /eval : rapport performance + coût abonnement vs API | 2026-05-23 |
| [#98](pr-98-fallback-api-reprendre-session.md) | [M97] Fallback API : reprendre la session Claude via --resume | 2026-05-23 |
| [#100](pr-100-supprimer-fallback-api.md) | [M99] Supprimer le fallback API — ne pas charger ANTHROPIC_API_KEY dans le bot | 2026-05-24 |
| [#104](pr-104-phase2-1d-filtre-buy.md) | [M103] Optimiser Phase 2 — appel 1D filtré sur candidats 4h BUY | 2026-05-24 |
| [#106](pr-106-filtre-usdc-couplage-1d.md) | [OPT] Phase 1 filtre USDC non tradables + Phase 2 appels 1D couplés par coin | 2026-05-25 |
| [#117](pr-117-ci-skip-doc-medium-report.md) | ci: skip tech-lead-review et doc-tech sur doc/medium-report | 2026-05-25 |
| [#118](pr-118-medium-articles-workflow.md) | feat(medium): dossier medium-articles + agent + CI skip article/* | 2026-05-25 |
| [#130](pr-130-workflow-dispatch.md) | fix(ci): remplace projects_v2_item par workflow_dispatch dans binance-dev-auto | 2026-05-28 |
| [#131](pr-131-post-review-auto-tag.md) | ci(post-review): auto-tag tech-lead-review + In progress sur tickets générés | 2026-05-28 |
| [#133](pr-133-test-workflow-binance-dev.md) | [M132] Test workflow binance-dev-auto — vérification déclenchement workflow_dispatch | 2026-05-28 |
| [#134](pr-134-qualifier-les-except-generiques.md) | [M27] Qualifier les except génériques par des types spécifiques | 2026-05-28 |
| [#135](pr-135-add-trigger-heartbeat.md) | [M31] Add trigger field to JSONL heartbeat logs | 2026-05-28 |
| [#140](pr-140-post-review-trigger-binance-dev-auto.md) | feat(ci): post-review déclenche binance-dev-auto sur tickets [REC] | 2026-05-28 |
| [#141](pr-141-documenter-skip-types.md) | [M128] Documenter les TYPE_A/B/C/D de skip_type en CLAUDE.md | 2026-05-28 |
| [#142](pr-142-clarify-date-format.md) | [M124] Clarifier le format date en Phase 8 du trade_prompt | 2026-05-28 |
| [#144](pr-144-verify-variable-definitions.md) | [M125] Vérifier la définition des variables Phase 3/5/6 en trade_prompt | 2026-05-28 |
| [#122](pr-122-cycle-log-jsonl.md) | [M121] Générer state/cycle_log.jsonl après chaque cycle et le pousser | 2026-05-28 |

---
*Source de vérité : ce dossier `docs/technique/`. Miroir disponible sur le [GitHub Wiki](../../wiki).*
