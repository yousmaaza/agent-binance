"""Univers USDC depuis Kraken + filtre volume/spread/persistance — phase 1.

Appelle `kraken pairs -o json` pour récupérer toutes les paires USDC disponibles,
calcule le volume 24h et le spread via `kraken ticker` (batches de 10), filtre au-dessus
du seuil min_volume_usdc et en-dessous de max_spread_pct (config.json). Les paires qui
passent ces deux filtres doivent en plus tenir le volume sur plusieurs périodes
consécutives (`kraken ohlc`, appelé uniquement sur les candidats déjà retenus, pas sur
les 46 paires) pour écarter un pic isolé (cf. incident TRUMP du 22-23/08/2026 : volume
x27 en une nuit, spread douze fois plus large que XBT/SOL, stop-loss glissé de 2,3 %
à l'exécution). Les coins de portfolio_coins sont toujours inclus même si sous le seuil.

Exécuté par Claude en Phase 1 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase1_scan.py __CYCLE_ID__

Stdout : PHASE1_SCAN_DONE|tradable=N|coins=XBT,SOL,...
Output : $TMPDIR/cycle_{CYCLE_ID}_phase1_output.json
"""
import sys
import os
import json
import subprocess
import tempfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import binance, _load_config

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

# Mapping Kraken coin → symbole TradingView/Binance (pour les appels coin_analysis Phase 2)
# Seuls les coins dont le ticker Kraken diffère de celui de TradingView/Binance
TV_MAP = {
    "XBT": "BTC",   # Kraken utilise XBT, TradingView utilise BTC
    "XDG": "DOGE",  # Kraken utilise XDG, TradingView utilise DOGE
}

cfg = _load_config()
MIN_VOLUME_USDC = cfg.get("min_volume_usdc", 1_000_000)
MAX_SPREAD_PCT = cfg.get("max_spread_pct", 0.0008)
VOLUME_PERSISTENCE_PERIODS = cfg.get("volume_persistence_periods", 6)
portfolio_coins = set(cfg.get("portfolio_coins", []))

# 4h aligné sur les slots auto-scheduler (cf. CLAUDE.md convention horaire)
PERSISTENCE_INTERVAL_MIN = 240
PERSISTENCE_REQUIRED = VOLUME_PERSISTENCE_PERIODS // 2 + 1  # majorité des périodes doivent tenir le seuil

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
            if data.get("c") and data.get("v") and data.get("a") and data.get("b"):
                price = float(data["c"][0])
                vol_base = float(data["v"][1])
                ask = float(data["a"][0])
                bid = float(data["b"][0])
                spread_pct = (ask - bid) / ask if ask else 1.0
                ticker_by_pair[pair] = {"price": price, "volume_24h": vol_base * price, "spread_pct": spread_pct}
    except (json.JSONDecodeError, subprocess.CalledProcessError, ValueError) as e:
        print(f"batch ticker error (batch {i // batch_size + 1}): {e}", file=sys.stderr)


def _volume_is_persistent(pair):
    """Vérifie que le volume tient sur plusieurs périodes consécutives (kraken ohlc), pas
    seulement sur un pic isolé — appelé uniquement sur les candidats déjà filtrés volume+spread."""
    try:
        ohlc_raw = binance("ohlc", pair, "--interval", str(PERSISTENCE_INTERVAL_MIN), "-o", "json")
        candles = json.loads(ohlc_raw).get(pair, [])[-VOLUME_PERSISTENCE_PERIODS:]
        threshold = MIN_VOLUME_USDC / VOLUME_PERSISTENCE_PERIODS
        ok_periods = sum(1 for c in candles if float(c[6]) * float(c[5]) >= threshold)
        return ok_periods >= PERSISTENCE_REQUIRED
    except (json.JSONDecodeError, subprocess.CalledProcessError, ValueError) as e:
        print(f"ohlc error {pair}: {e}", file=sys.stderr)
        return False


# Étape 3 : filtrer par volume, spread, puis persistance du volume — toujours inclure portfolio_coins
tradable = []
non_tradable = []

for pair, coin in usdc_coins.items():
    info = ticker_by_pair.get(pair)
    if info is None:
        non_tradable.append({"coin": coin, "reason": "ticker indisponible"})
        continue

    vol = info["volume_24h"]
    price = info["price"]
    spread_pct = info["spread_pct"]

    if coin in portfolio_coins:
        tradable.append({"coin": coin, "price": price, "volume_24h": vol, "tv_symbol": TV_MAP.get(coin, coin)})
    elif vol < MIN_VOLUME_USDC:
        non_tradable.append({"coin": coin, "reason": f"volume {vol / 1e6:.1f}M USDC < {MIN_VOLUME_USDC / 1e6:.0f}M"})
    elif spread_pct > MAX_SPREAD_PCT:
        non_tradable.append({"coin": coin, "reason": f"spread {spread_pct * 100:.3f}% > {MAX_SPREAD_PCT * 100:.3f}%"})
    elif not _volume_is_persistent(pair):
        non_tradable.append({"coin": coin, "reason": "volume non soutenu (pic isolé)"})
    else:
        tradable.append({"coin": coin, "price": price, "volume_24h": vol, "tv_symbol": TV_MAP.get(coin, coin)})

coins_str = ",".join(c["coin"] for c in tradable)
print(f"PHASE1_SCAN_DONE|tradable={len(tradable)}|coins={coins_str}")

out = {"tradable": tradable, "non_tradable": non_tradable}
out_path = os.path.join(tempfile.gettempdir(), f"cycle_{CYCLE_ID}_phase1_output.json")  # contract-dynamic: gettempdir() == /tmp sur macOS/Linux, dépendance implicite non littérale (#414, #403)
with open(out_path, "w") as f:
    json.dump(out, f)
