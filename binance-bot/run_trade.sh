#!/bin/bash
# Wrapper script called by n8n Execute Command node
# Runs the Claude trading agent with the full workflow prompt

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Charger les secrets depuis .env (script legacy v1 — remplacé par webhook_server.py)
set -a; source "$PROJECT_DIR/.env"; set +a
LOCK_FILE="$PROJECT_DIR/state/agent_lock.json"

# Check lock
RUNNING=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    with open('$LOCK_FILE') as f:
        lock = json.load(f)
    if not lock.get('running'):
        print('false')
    else:
        started = lock.get('started_at')
        if started:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(started.replace('Z', '+00:00'))).total_seconds()
            print('false' if age >= 7200 else 'true')
        else:
            print('false')
except:
    print('false')
" 2>/dev/null)

if [ "$RUNNING" = "true" ]; then
    echo "LOCKED: Agent already running, skipping"
    exit 0
fi

# Acquire lock
python3 -c "
import json
from datetime import datetime, timezone
with open('$LOCK_FILE', 'w') as f:
    json.dump({'running': True, 'started_at': datetime.now(timezone.utc).isoformat()}, f)
"

claude --print --dangerously-skip-permissions --cwd "$PROJECT_DIR" \
"Tu es un agent de trading Binance automatisé. Lis config.json pour la configuration.

PHASE 1 — SNAPSHOT PORTFOLIO
- Lis config.json : binance_profile, usdc_allocation_pct, tracked_coins, quote_asset
- binance-cli spot get-account --profile agent-profile
- binance-cli spot get-open-orders --profile agent-profile
- budget = USDC_free × usdc_allocation_pct

PHASE 2 — ANALYSE MARCHÉ (en parallèle)
- mcp__tradingview__coin_analysis pour BTC, STX, XRP, SOL, SUI (exchange: BINANCE, timeframe: 4h)
- mcp__tradingview__market_sentiment (symbol: BTC, category: crypto)
- mcp__tradingview__volume_breakout_scanner (exchange: BINANCE, timeframe: 4h)

PHASE 3 — STRATÉGIE HYBRIDE
- Positions existantes : HOLD / RENFORCER / VENDRE selon RSI, MACD, ADX
- Nouvelles opportunités dans la limite de max_single_position_pct du budget
- Prix BUY = prix × (1 - limit_offset_pct), SELL = prix × (1 + limit_offset_pct)
- Exclure ordres < min_order_usdc

PHASE 4 — APPROBATION TELEGRAM
Formate le rapport et envoie-le avec boutons [✅ CONFIRMER] [❌ ANNULER] via Python :

import urllib.request, json, time
import os
TOKEN = os.environ.get(\"TELEGRAM_TOKEN\", \"\")
CHAT_ID = os.environ.get(\"TELEGRAM_CHAT_ID\", \"\")
BASE = f\"https://api.telegram.org/bot{TOKEN}\"

def post(endpoint, body):
    req = urllib.request.Request(f\"{BASE}/{endpoint}\", data=json.dumps(body).encode(), headers={\"Content-Type\": \"application/json\"}, method=\"POST\")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

post(\"sendMessage\", {\"chat_id\": CHAT_ID, \"text\": RAPPORT_MARKDOWN, \"parse_mode\": \"Markdown\",
    \"reply_markup\": {\"inline_keyboard\": [[{\"text\": \"✅ CONFIRMER\", \"callback_data\": \"CONFIRM\"}, {\"text\": \"❌ ANNULER\", \"callback_data\": \"CANCEL\"}]]}})

try:
    with open(\"state/telegram_offset.json\") as f:
        offset = json.load(f).get(\"offset\", 0)
except:
    offset = 0

start = time.time()
action = \"TIMEOUT\"
while time.time() - start < 1800:
    data = post(\"getUpdates\", {\"offset\": offset, \"timeout\": 10})
    for u in data.get(\"result\", []):
        offset = u[\"update_id\"] + 1
        cq = u.get(\"callback_query\")
        if cq:
            action = cq[\"data\"]
            post(\"answerCallbackQuery\", {\"callback_query_id\": cq[\"id\"], \"text\": \"✅ Confirmé — exécution en cours...\" if action == \"CONFIRM\" else \"❌ Annulé.\"})
            break
    if action != \"TIMEOUT\":
        break

with open(\"state/telegram_offset.json\", \"w\") as f:
    json.dump({\"offset\": offset}, f)
print(f\"ACTION={action}\")

PHASE 5 — EXÉCUTION si ACTION=CONFIRM
Pour chaque ordre :
1. Re-fetch solde : binance-cli spot get-account --profile agent-profile
2. Re-fetch prix : binance-cli spot get-symbol-price-ticker --symbol {SYMBOL} --profile agent-profile
3. Si drift > price_deviation_max_pct → skip + warning
4. binance-cli spot post-order --symbol {COIN}USDC --side BUY/SELL --type LIMIT --quantity {qty} --price {price} --timeInForce GTC --profile agent-profile

PHASE 6 — RAPPORT FINAL
- Génère reports/YYYY-MM-DD_HH-MM_trade.md
- Envoie confirmation Telegram avec ordres exécutés et IDs
- Écris state/agent_lock.json : {\"running\": false, \"started_at\": null}"

EXIT_CODE=$?

# Release lock
python3 -c "
import json
with open('$LOCK_FILE', 'w') as f:
    json.dump({'running': False, 'started_at': None}, f)
"

exit $EXIT_CODE
