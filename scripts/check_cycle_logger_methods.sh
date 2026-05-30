#!/usr/bin/env bash
# Vérifie que tous les appels cycle_log.xxx() utilisent des méthodes définies dans CycleLogger.
# Usage : bash scripts/check_cycle_logger_methods.sh
# Intégrable en pre-commit hook ou CI check.
set -euo pipefail

DEFINED="info|error|warning|heartbeat|read_last_phase"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

bad=$(grep -rn "cycle_log\." "$REPO_ROOT/binance-bot/" --include="*.py" \
    | grep -v "^[^:]*:#" \
    | grep -v "_cycle_log" \
    | grep -vE "cycle_log\.(${DEFINED})\(" \
    || true)

if [[ -n "$bad" ]]; then
    echo "❌ Appel(s) cycle_log avec méthode non définie dans CycleLogger :"
    echo "$bad"
    echo ""
    echo "Méthodes valides : $DEFINED"
    exit 1
fi

echo "✅ Tous les appels cycle_log utilisent des méthodes définies."
exit 0
