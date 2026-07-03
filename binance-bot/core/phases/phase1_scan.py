"""Univers USDC depuis Kraken + filtre volume — phase 1.

Appelle `kraken pairs -o json` pour récupérer toutes les paires USDC disponibles,
calcule le volume 24h via `kraken ticker` (batches de 10), filtre au-dessus du seuil
min_volume_usdc (config.json, défaut 1M). Les coins de portfolio_coins sont toujours
inclus même si sous le seuil.

Exécuté par Claude en Phase 1 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase1_scan.py __CYCLE_ID__

Stdout : PHASE1_SCAN_DONE|tradable=N|coins=XBT,SOL,...
Output : /tmp/cycle_{CYCLE_ID}_phase1_output.json
"""
import sys
import os
import json

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance, _load_config  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

# Mapping Kraken coin → symbole TradingView/Binance (pour les appels coin_analysis Phase 2)
# Seuls les coins dont le ticker Kraken diffère de celui de TradingView/Binance
TV_MAP = {
    "XBT": "BTC",   # Kraken utilise XBT, TradingView utilise BTC
    "XDG": "DOGE",  # Kraken utilise XDG, TradingView utilise DOGE
}

cfg = _load_config()
MIN_VOLUME_USDC = cfg.get("min_volume_usdc", 1_000_000)
portfolio_coins = set(cfg.get("portfolio_coins", []))

# Étape 1 : récupérer toutes les paires USDC disponibles sur Kraken
pairs_raw = binance("pairs", "-o", "json")
pairs_data = json.loads(pairs_raw)

usdc_pairs = [k for k in pairs_data if k.endswith("USDC") and ".d" not in k]
# Extraire le coin depuis le nom de la paire : XBTUSDC → XBT, SOLUSDC → SOL
usdc_coins = {pair: pair[:-4] for pair in usdc_pairs}  # {"XBTUSDC": "XBT", ...}

# Étape 2 : appels ticker par batch de 10 paires — collecter prix et volume
ticker_by_pair = {}  # {"XBTUSDC": {"price": 61000.0, "volume_24h": 19000000.0}, ...}

batch_size = 10
pairs_list = list(usdc_coins.keys())
for i in range(0, len(pairs_list), batch_size):
    batch = pairs_list[i:i + batch_size]
    try:
        ticker_raw = binance("ticker", *batch, "-o", "json")
        ticker_data = json.loads(ticker_raw)
        for pair, data in ticker_data.items():
            if data.get("c") and data.get("v"):
                price = float(data["c"][0])
                vol_base = float(data["v"][1])
                ticker_by_pair[pair] = {"price": price, "volume_24h": vol_base * price}
    except Exception as e:
        print(f"batch ticker error (batch {i // batch_size + 1}): {e}", file=sys.stderr)

# Étape 3 : filtrer par volume, toujours inclure portfolio_coins
tradable = []
non_tradable = []

for pair, coin in usdc_coins.items():
    info = ticker_by_pair.get(pair)
    if info is None:
        non_tradable.append({"coin": coin, "reason": "ticker indisponible"})
        continue

    vol = info["volume_24h"]
    price = info["price"]

    if vol >= MIN_VOLUME_USDC or coin in portfolio_coins:
        tradable.append({"coin": coin, "price": price, "volume_24h": vol, "tv_symbol": TV_MAP.get(coin, coin)})
    else:
        non_tradable.append({"coin": coin, "reason": f"volume {vol / 1e6:.1f}M USDC < {MIN_VOLUME_USDC / 1e6:.0f}M"})

coins_str = ",".join(c["coin"] for c in tradable)
print(f"PHASE1_SCAN_DONE|tradable={len(tradable)}|coins={coins_str}")

out = {"tradable": tradable, "non_tradable": non_tradable}
with open(f"/tmp/cycle_{CYCLE_ID}_phase1_output.json", "w") as f:
    json.dump(out, f)
