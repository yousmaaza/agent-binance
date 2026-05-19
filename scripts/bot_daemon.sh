#!/bin/bash
# Bot daemon : démarre le webhook server + tunnel, surveille et redémarre si besoin
# Lancé automatiquement par le LaunchAgent macOS

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Charger les secrets depuis .env
set -a; source "$PROJECT_DIR/.env"; set +a
TOKEN="$TELEGRAM_TOKEN"
CHAT_ID="$TELEGRAM_CHAT_ID"
LOG="$PROJECT_DIR/state/daemon.log"

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"; }

notify() {
    curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": \"$CHAT_ID\", \"text\": \"$1\"}" > /dev/null 2>&1
}

start_stack() {
    log "Démarrage du webhook server..."
    python3 "$PROJECT_DIR/scripts/webhook_server.py" >> "$LOG" 2>&1 &
    WEBHOOK_PID=$!
    sleep 2

    log "Démarrage du tunnel Cloudflare..."
    TUNNEL_LOG=$(mktemp)
    cloudflared tunnel --url http://localhost:5678 --no-autoupdate >> "$LOG" 2>"$TUNNEL_LOG" &
    TUNNEL_PID=$!

    # Attente URL
    PUBLIC_URL=""
    for i in $(seq 1 40); do
        PUBLIC_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
        [ -n "$PUBLIC_URL" ] && break
        sleep 1
    done

    if [ -z "$PUBLIC_URL" ]; then
        log "ERREUR: impossible d'obtenir l'URL publique"
        kill $WEBHOOK_PID $TUNNEL_PID 2>/dev/null
        return 1
    fi

    log "URL: $PUBLIC_URL"

    # Enregistrement webhook Telegram
    RESULT=$(curl -s -X POST "https://api.telegram.org/bot${TOKEN}/setWebhook" \
        -H "Content-Type: application/json" \
        -d "{\"url\": \"${PUBLIC_URL}/webhook\", \"allowed_updates\": [\"message\", \"callback_query\"]}")

    if echo "$RESULT" | grep -q '"ok":true'; then
        log "Webhook enregistré: ${PUBLIC_URL}/webhook"
        notify "✅ Bot démarré\n${PUBLIC_URL}/webhook"
    else
        log "ERREUR webhook: $RESULT"
    fi

    # Sauver les PIDs et l'URL
    python3 -c "
import json
with open('$PROJECT_DIR/state/webhook_pids.json', 'w') as f:
    json.dump({'webhook': $WEBHOOK_PID, 'tunnel': $TUNNEL_PID, 'url': '$PUBLIC_URL'}, f)
"
    echo "$TUNNEL_LOG"
    export CURRENT_WEBHOOK_PID=$WEBHOOK_PID
    export CURRENT_TUNNEL_PID=$TUNNEL_PID
    export CURRENT_URL=$PUBLIC_URL
}

stop_stack() {
    log "Arrêt du stack..."
    [ -n "$CURRENT_WEBHOOK_PID" ] && kill $CURRENT_WEBHOOK_PID 2>/dev/null
    [ -n "$CURRENT_TUNNEL_PID" ] && kill $CURRENT_TUNNEL_PID 2>/dev/null
    sleep 2
}

# Nettoyage au démarrage
pkill -f "webhook_server.py" 2>/dev/null
pkill -f "cloudflared tunnel --url" 2>/dev/null
sleep 2

# Démarrage initial
start_stack

# Boucle de surveillance (vérifie toutes les 60s)
FAIL_COUNT=0
while true; do
    sleep 60

    # Vérifie si le tunnel répond
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${CURRENT_URL}/webhook" 2>/dev/null)

    if [ "$HTTP_CODE" = "000" ] || [ -z "$HTTP_CODE" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        log "Tunnel injoignable (tentative $FAIL_COUNT/3) — HTTP: $HTTP_CODE"

        if [ $FAIL_COUNT -ge 3 ]; then
            log "Redémarrage du stack..."
            notify "🔄 Tunnel tombé, redémarrage en cours..."
            stop_stack
            sleep 3
            start_stack
            FAIL_COUNT=0
        fi
    else
        FAIL_COUNT=0
    fi
done
