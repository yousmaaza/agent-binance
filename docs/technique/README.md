# Documentation technique — agent-binance

Documentation technique du projet, mise à jour automatiquement par l'agent `binance-doc-tech`.

## Documents

| Document | Description | Dernière mise à jour |
|---|---|---|
| [SPEC.md](SPEC.md) | Spécification technique globale du projet | 2026-05-23 |

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

---
*Source de vérité : ce dossier `docs/technique/`. Miroir disponible sur le [GitHub Wiki](../../wiki).*
