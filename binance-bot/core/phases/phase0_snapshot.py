"""Snapshot des positions ouvertes et leur P&L — extrait de phase0_snapshot.txt.

Exécuté par Claude en début de Phase 0 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase0_snapshot.py __CYCLE_ID__

Stdout : PHASE0_SNAPSHOT_DONE|open_positions=N
Output : /tmp/cycle_{CYCLE_ID}_phase0_snapshot_output.json
"""
import sys
import os
import json

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

try:
    with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
        history = json.load(f)
    open_positions_list = [t for t in history if t.get("status") == "open"]

    if open_positions_list:
        snapshot_lines = ["📊 SNAPSHOT POSITIONS OUVERTES"]
        snapshot_lines.append(f"Positions actives : {len(open_positions_list)}")
        snapshot_lines.append("")

        for pos in open_positions_list:
            coin = pos.get("coin")
            entry_price = float(pos.get("entry_price", 0))
            qty = float(pos.get("quantity", 0))
            entry_usdc = entry_price * qty

            try:
                ticker_data = json.loads(
                    binance("spot", "ticker-price", "--symbol", f"{coin}USDC", "--profile", "agent-profile")
                )
                current_price = float(ticker_data.get("price", entry_price))
            except Exception:
                current_price = entry_price

            current_usdc = current_price * qty
            pnl_usdc = current_usdc - entry_usdc
            pnl_pct = (pnl_usdc / entry_usdc * 100) if entry_usdc > 0 else 0

            pos_type = "bot" if pos.get("side") == "BUY" else "unknown"
            if not pos.get("entry_order_id"):
                pos_type = "manuel"

            snapshot_lines.append(
                f"{coin}: entrée {entry_price:.4g} → prix {current_price:.4g}"
                f" | P&L {pnl_pct:+.1f}% ({pnl_usdc:+.2f} USDC) [{pos_type}]"
            )

        tg("\n".join(snapshot_lines))
    else:
        tg("📊 Aucune position ouverte actuellement")

    open_positions = len(open_positions_list)
    print(f"PHASE0_SNAPSHOT_DONE|open_positions={open_positions}")
    with open(f"/tmp/cycle_{CYCLE_ID}_phase0_snapshot_output.json", "w") as f:
        json.dump({"open_positions": open_positions}, f)

except Exception as e:
    tg(f"⚠️ Snapshot positions échoué : {e}")
    print(f"PHASE0_SNAPSHOT_ERROR|{e}")
    sys.exit(1)
