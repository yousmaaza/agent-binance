"""Filtrage USDC et vérification volume Kraken — phase 1.

Lit la liste de candidats depuis /tmp/cycle_{CYCLE_ID}_phase1_input.json
(champ "candidates") ou depuis config.json si le fichier est absent.

Exécuté par Claude en Phase 1 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase1_scan.py __CYCLE_ID__

Stdout : PHASE1_SCAN_DONE|tradable=N|coins=BTC,SOL,...
Output : /tmp/cycle_{CYCLE_ID}_phase1_output.json
"""
import sys
import os
import json

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance, _load_config  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

STABLECOINS = {"USDT", "BUSD", "FDUSD", "USDC", "TUSD", "DAI", "USDP"}

in_path = f"/tmp/cycle_{CYCLE_ID}_phase1_input.json"
if os.path.exists(in_path):
    with open(in_path) as f:
        inp = json.load(f)
    candidates = inp.get("candidates", [])
else:
    cfg = _load_config()
    candidates = cfg.get("portfolio_coins", []) + cfg.get("universe_extra", [])

candidates = [c for c in candidates if c.upper() not in STABLECOINS]

tradable = []
non_tradable = []

for coin in candidates:
    try:
        ticker_raw = binance("ticker", f"{coin}USDC", "-o", "json")
        ticker_data = json.loads(ticker_raw)
        pair_data = ticker_data.get(f"{coin}USDC")
        if pair_data and pair_data.get("c"):
            price = float(pair_data["c"][0])
            vol_base = float(pair_data["v"][1])  # volume 24h en base asset
            vol = vol_base * price  # volume 24h en USDC
            if vol >= 5_000_000:
                tradable.append({"coin": coin, "price": price, "volume_24h": vol})
            else:
                non_tradable.append({"coin": coin, "reason": f"volume {vol / 1e6:.1f}M USDC < 5M"})
        else:
            non_tradable.append({"coin": coin, "reason": "paire USDC introuvable"})
    except Exception:
        non_tradable.append({"coin": coin, "reason": "paire USDC introuvable"})

coins_str = ",".join(c["coin"] for c in tradable)
print(f"PHASE1_SCAN_DONE|tradable={len(tradable)}|coins={coins_str}")

out = {"tradable": tradable, "non_tradable": non_tradable}
with open(f"/tmp/cycle_{CYCLE_ID}_phase1_output.json", "w") as f:
    json.dump(out, f)
