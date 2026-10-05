"""Dimensionnement de position et filtres Kraken (lot_decimals/ordermin/costmin) — phase 4.

Lit les buy_candidates depuis /tmp/cycle_{CYCLE_ID}_phase4_input.json :
{
  "buy_candidates": [{coin, score, signal_4h, prix_actuel, atr_pct}],
  "portfolio_total": X,
  "budget_disponible": X,
  "config": {...}
}

Exécuté par Claude en Phase 4 :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase4_sizing.py __CYCLE_ID__

Stdout : PHASE4_DONE|orders=N|skipped=M
Output : /tmp/cycle_{CYCLE_ID}_phase4_output.json
"""
import sys
import os
import json
import math

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.trade_helpers import tg, binance, _load_config, compute_tp_target, fetch_resistance_4h  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

# Chemin fixe volontaire (contrat avec prompts/phases/phase4_sizing.txt) : neutralisation
# bandit temporaire, à lever avec le déplacement /tmp -> state/ (#392, #403)
in_path = f"/tmp/cycle_{CYCLE_ID}_phase4_input.json"  # nosec B108
with open(in_path) as f:
    inp = json.load(f)

buy_candidates = inp.get("buy_candidates", [])
portfolio_total = inp.get("portfolio_total", 0)
budget_disponible = inp.get("budget_disponible", 0)
cfg = inp.get("config") or _load_config()

risk_per_trade_pct = cfg.get("risk_per_trade_pct", 0.01)
atr_stop_multiplier = cfg.get("atr_stop_multiplier", 2)
# max_stop_distance_pct : plafond sur la distance de stop, au-delà écarte le coin en TYPE_B (#508)
# — protège contre la queue volatile (ATR 4h > 4.8%, cf. TRUMP 22-23/08/2026, volume x27) sans
# bloquer le flux normal (10.9% de trades bloqués mesurés à ce seuil, n=110 trades réels).
max_stop_distance_pct = cfg.get("max_stop_distance_pct", 0.12)
# reward_risk_ratio : chargé depuis config.json, détermine le rapport TP/SL, net de frais (#411)
# Si absent : défaut 1.5. Affecte le calcul du prix_tp en phase 4 (ligne ~62)
reward_risk_ratio = cfg.get("reward_risk_ratio", 1.5)
# fee_round_trip_pct : estimation du coût aller-retour (entrée+sortie), utilisée pour que le TP
# et le dimensionnement reflètent le gain/perte réel net plutôt que brut (#411)
fee_round_trip_pct = cfg.get("fee_round_trip_pct", 0.009)
# max_tp_pct : plafond absolu sur la cible, indépendant de la résistance 4h (#428) — mesure MFE
# (mouvement réellement offert pendant la détention) sur 19 trades (bougies Kraken 30j, #508,
# 28/09/2026) : médiane +1.52%, très en-dessous des cibles mécaniques que produit un stop large
# (atr_stop_multiplier élevé).
max_tp_pct = cfg.get("max_tp_pct", 0.06)
# resistance_lookback_4h : nombre de bougies 4h clôturées pour la résistance de plafonnement (#516)
resistance_lookback_4h = cfg.get("resistance_lookback_4h", 30)
limit_offset_pct = cfg.get("limit_offset_pct", 0.001)
min_order_usdc = cfg.get("min_order_usdc", 9)
max_single_position_pct = cfg.get("max_single_position_pct", 0.3)

risk_usdc = portfolio_total * risk_per_trade_pct
ordres_prepares = []
skipped = []

for candidate in buy_candidates:
    coin = candidate["coin"]
    prix_actuel = candidate.get("prix_actuel", 0)
    atr_pct = candidate.get("atr_pct", 0.02)

    stop_distance_pct = atr_pct * atr_stop_multiplier

    # Plafond distance de stop (#508) : un stop au-delà de max_stop_distance_pct signale une
    # volatilité extrême — skip avant de calculer prix_stop/prix_tp plutôt que de dimensionner
    # une position sur un ATR aberrant.
    if stop_distance_pct > max_stop_distance_pct:
        skipped.append({
            "coin": coin,
            "reason": f"Stop {stop_distance_pct * 100:.1f}% > plafond {max_stop_distance_pct * 100:.1f}% "
                      f"(volatilité extrême, ATR 4h {atr_pct * 100:.1f}%)",
        })
        continue

    prix_entry = prix_actuel * (1 - limit_offset_pct)
    prix_stop = prix_entry * (1 - stop_distance_pct)
    # Même règle que le recalibrage Phase 0 (#516) : TP net de frais (#411) plafonné par max_tp_pct
    # (#428) et par la résistance 4h Kraken (plus haut des bougies clôturées) ; Kraken indisponible
    # -> plafond max_tp_pct seul.
    resistance_4h = fetch_resistance_4h(coin, resistance_lookback_4h)
    prix_tp = compute_tp_target(prix_entry, stop_distance_pct, reward_risk_ratio, fee_round_trip_pct,
                                max_tp_pct, resistance_4h)

    if prix_stop <= 0:
        skipped.append({"coin": coin, "reason": "prix_stop négatif (volatilité extrême)"})
        continue

    if stop_distance_pct > 0:
        # Perte réelle = distance stop + frais aller-retour (#411) : la quantité doit rentrer
        # dans le budget de risque une fois les frais comptés, pas seulement le glissement au stop.
        quantite = risk_usdc / (prix_entry * (stop_distance_pct + fee_round_trip_pct))
    else:
        skipped.append({"coin": coin, "reason": "stop_distance_pct nul"})
        continue
    montant_ordre = quantite * prix_entry

    if montant_ordre < min_order_usdc:
        skipped.append({"coin": coin, "reason": f"Montant {montant_ordre:.2f} USDC < seuil {min_order_usdc}"})
        continue

    budget_max = budget_disponible * max_single_position_pct
    if montant_ordre > budget_max:
        quantite = budget_max / prix_entry
        montant_ordre = budget_max

    try:
        pairs_raw = binance("pairs", "--pair", f"{coin}USDC", "-o", "json")
        pair_data = json.loads(pairs_raw).get(f"{coin}USDC", {})
        lot_dec = int(pair_data.get("lot_decimals", 8))
        step = 10 ** (-lot_dec)
        min_qty = float(pair_data.get("ordermin", "0"))
        costmin = float(pair_data.get("costmin", "5.0"))
        quantite = math.floor(quantite / step) * step
        quantite = round(quantite, lot_dec)
        if quantite < min_qty:
            skipped.append({"coin": coin, "reason": f"qty {quantite} < ordermin {min_qty}"})
            continue
        if quantite * prix_entry < costmin:
            skipped.append({"coin": coin, "reason": f"montant {quantite * prix_entry:.2f} USDC < costmin {costmin}"})
            continue
    except Exception as e:
        tg(f"⚠️ {coin} kraken pairs échoué : {e}")

    ordres_prepares.append({
        "coin": coin,
        "quantite": quantite,
        "prix_entry": prix_entry,
        "prix_stop": prix_stop,
        "prix_tp": prix_tp,
        "montant_ordre": montant_ordre,
        "risk_usdc": risk_usdc,
        "stop_distance_pct": stop_distance_pct,
        "resistance_4h": resistance_4h,
        "score": candidate.get("score", 0),
    })

if ordres_prepares:
    tg(
        "💰 Phase 4 — Ordres préparés\n"
        + "\n".join(
            f"{o['coin']} {o['quantite']:.4g} @ {o['prix_entry']:.4g}"
            f" | Stop: {o['prix_stop']:.4g} | TP: {o['prix_tp']:.4g} | Risque: {o['risk_usdc']:.2f} USDC"
            for o in ordres_prepares
        )
    )

out = {"ordres_prepares": ordres_prepares, "skipped": skipped}
# Chemin fixe volontaire (contrat avec prompts/phases/phase4_sizing.txt) : neutralisation
# bandit temporaire, à lever avec le déplacement /tmp -> state/ (#392, #403)
with open(f"/tmp/cycle_{CYCLE_ID}_phase4_output.json", "w") as f:  # nosec B108
    json.dump(out, f)

print(f"PHASE4_DONE|orders={len(ordres_prepares)}|skipped={len(skipped)}")
