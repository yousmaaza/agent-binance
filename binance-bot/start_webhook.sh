#!/bin/bash
# Démarre le serveur webhook + Cloudflare Tunnel
# Usage: ./scripts/start_webhook.sh

set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Charger les secrets depuis .env
set -a; source "$PROJECT_DIR/.env"; set +a
TOKEN="$TELEGRAM_TOKEN"

echo "🚀 Démarrage du serveur webhook Telegram..."

# 1. Démarrer le serveur webhook en arrière-plan
python3 "$PROJECT_DIR/scripts/webhook_server.py" &
WEBHOOK_PID=$!
echo "   Serveur démarré (PID: $WEBHOOK_PID)"

# 2. Attendre que le serveur soit prêt
sleep 2

# 3. Démarrer Cloudflare Tunnel et capturer l'URL publique
echo "🌐 Démarrage du tunnel Cloudflare..."
TUNNEL_LOG=$(mktemp)
cloudflared tunnel --url http://localhost:8080 --no-autoupdate 2>"$TUNNEL_LOG" &
TUNNEL_PID=$!

# 4. Attendre et extraire l'URL publique
echo "   Attente de l'URL publique..."
PUBLIC_URL=""
for i in $(seq 1 30); do
    PUBLIC_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
    if [ -n "$PUBLIC_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
    echo "❌ Impossible d'obtenir l'URL Cloudflare. Vérifie cloudflared."
    kill $WEBHOOK_PID $TUNNEL_PID 2>/dev/null
    exit 1
fi

echo "   URL publique : $PUBLIC_URL"

# 5. Enregistrer le webhook Telegram
WEBHOOK_URL="${PUBLIC_URL}/webhook"
echo "📡 Enregistrement du webhook Telegram..."
RESULT=$(curl -s -X POST "https://api.telegram.org/bot${TOKEN}/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"${WEBHOOK_URL}\", \"allowed_updates\": [\"message\", \"callback_query\"]}")

if echo "$RESULT" | grep -q '"ok":true'; then
    echo "   ✅ Webhook enregistré : $WEBHOOK_URL"
else
    echo "   ❌ Erreur enregistrement webhook: $RESULT"
fi

# 6. Notification Telegram
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "{\"chat_id\": \"$TELEGRAM_CHAT_ID\", \"text\": \"✅ *Bot connecté et prêt*\\n\\nCommandes disponibles :\\n/trade — Lancer une analyse\\n/status — Voir le portfolio\", \"parse_mode\": \"Markdown\"}" > /dev/null

echo ""
echo "✅ Tout est en place !"
echo "   Webhook : $WEBHOOK_URL"
echo "   /trade et /status répondront instantanément depuis Telegram"
echo ""
echo "   PIDs : webhook=$WEBHOOK_PID tunnel=$TUNNEL_PID"
echo "   Pour arrêter : kill $WEBHOOK_PID $TUNNEL_PID"
echo ""

# Sauvegarder les PIDs
echo "{\"webhook\": $WEBHOOK_PID, \"tunnel\": $TUNNEL_PID, \"url\": \"$PUBLIC_URL\"}" > "$PROJECT_DIR/state/webhook_pids.json"

# Attendre (garder le script actif)
wait $WEBHOOK_PID
