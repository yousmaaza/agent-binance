# Documentation technique — agent-binance

Documentation technique du projet, mise à jour automatiquement par l'agent `binance-doc-tech`.

## Documents

| Document | Description | Dernière mise à jour |
|---|---|---|
| [SPEC.md](SPEC.md) | Spécification technique globale du projet | 2026-05-29 (PR #166) |

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
