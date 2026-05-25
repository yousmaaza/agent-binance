# Journal quotidien — agent-binance

Récaps quotidiens auto-générés par l'agent `daily-recap` (PR mergées, issues fermées, nouveaux tickets, angles narratifs). Matière première pour des articles Medium réguliers.

**Trigger 1** : slash command `/journal` lancée manuellement par l'utilisateur (mode interactif, pas de commit auto).

**Trigger 2** : routine Claude Code remote (cron `0 21 * * *` UTC = 23h Europe/Paris) qui tourne chaque soir et commit+push le récap du jour sur la branche dédiée `doc/medium-report` (pas main). Pilotée depuis https://claude.ai/code/routines.

Les entrées les plus récentes sont en haut. Le fichier de référence chronologique du projet reste `docs/medium-recap.md` (récap des 9 étapes structurantes du POC à v2).

---

<!-- Les entrées daily-recap seront insérées ci-dessous, plus récente en tête. -->
