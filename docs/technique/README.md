# Documentation technique — agent-binance

Documentation technique du projet, mise à jour automatiquement par l'agent `binance-doc-tech`.

## Documents

| Document | Description | Dernière mise à jour |
|---|---|---|
| [SPEC.md](SPEC.md) | Spécification technique globale du projet | 2026-05-21 |

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
| [#39](pr-39-phase5-buy-market-oco-protection.md) | [BUG] Phase 5 — Remplacer OTOCO par BUY MARKET + OCO immédiat | 2026-05-21 |

---
*Source de vérité : ce dossier `docs/technique/`. Miroir disponible sur le [GitHub Wiki](../../wiki).*
