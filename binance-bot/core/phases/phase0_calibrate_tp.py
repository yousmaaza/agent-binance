"""Recalibrage du TP des positions ouvertes (Phase 0) — résistance = plus haut des bougies 4h
Kraken clôturées, même règle que la cible d'entrée (#516, core.trade_helpers.compute_tp_target).

Exécuté par Claude en Phase 0 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase0_calibrate_tp.py __CYCLE_ID__

Stdout : PHASE0_CALIBRATE_TP_DONE|updated=N
Kraken indisponible pour un coin -> TP existant conservé.
"""
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import (  # noqa: E402
    tg, _load_config, _save_trade_history_atomic, compute_tp_target, fetch_resistance_4h, initial_stop_price,
)

TP_CHANGE_THRESHOLD = 0.005


def recalibrate_tps(history: list, cfg: dict, resistance_fn=fetch_resistance_4h) -> list:
    """Met à jour tp_price des trades ouverts dans `history` ; retourne [(coin, ancien, nouveau)]."""
    reward_risk_ratio = cfg.get("reward_risk_ratio", 1.5)
    fee_round_trip_pct = cfg.get("fee_round_trip_pct", 0.009)
    max_tp_pct = cfg.get("max_tp_pct", 0.06)
    lookback = cfg.get("resistance_lookback_4h", 30)

    changes = []
    for trade in history:
        if trade.get("status") != "open":
            continue
        entry = float(trade.get("entry_price") or 0)
        tp_actuel = float(trade.get("tp_price") or 0)
        if entry <= 0 or tp_actuel <= 0:
            continue
        resistance = resistance_fn(trade["coin"], lookback)
        if resistance is None:
            continue
        # Stop d'ORIGINE (#513) : le stop courant a pu être remonté (break-even, trailing)
        stop_distance_pct = (entry - initial_stop_price(trade, fee_round_trip_pct)) / entry
        tp_smart = compute_tp_target(entry, stop_distance_pct, reward_risk_ratio, fee_round_trip_pct,
                                     max_tp_pct, resistance)
        if abs(tp_smart - tp_actuel) / tp_actuel > TP_CHANGE_THRESHOLD:
            trade["tp_price"] = tp_smart
            changes.append((trade["coin"], tp_actuel, tp_smart))
    return changes


def main() -> None:
    import json
    with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
        history = json.load(f)
    changes = recalibrate_tps(history, _load_config())
    if changes:
        _save_trade_history_atomic(history)
        for coin, old_tp, new_tp in changes:
            tg(f"📐 TP {coin} recalibré : {old_tp:.6f} → {new_tp:.6f}")
    print(f"PHASE0_CALIBRATE_TP_DONE|updated={len(changes)}")


if __name__ == "__main__":
    main()
