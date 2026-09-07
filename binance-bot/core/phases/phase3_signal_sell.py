"""Vente sur signal (sell_candidates, score <= 3) — phase 3 (#472).

Le seuil (score <= 3) et la décision de vendre restent dans phase3_scoring.py:148 — ce script
exécute seulement la vente pour les candidats déjà décidés, il ne recalcule rien.

Lit sell_candidates depuis /tmp/cycle_{CYCLE_ID}_phase3_signal_sell_input.json :
{
  "sell_candidates": [{"coin": "ETH", "score": 1}, ...],
  "config": {...}
}

Séquence par candidat, reproduite à l'identique du comportement improvisé constaté en prod (#472,
cf. commentaire de l'issue) :
1. Retrouver le trade "open" du coin -> sinon passer.
2. Annuler le stop actif (sl_order_txid) s'il existe (contrainte hold_trade de Kraken, cf. #390) —
   si l'annulation échoue, le stop reste en place, rien d'autre à faire.
3. Vendre au marché min(quantity trade_history, solde réel) tronqué au pas de la paire (#472,
   incident XRP du 18/08 : la quantité brute de trade_history a produit deux
   EOrder:Insufficient funds).
4. Query du fill (3 tentatives, 2s) :
   - SELL échoué, fill introuvable après 3 tentatives, ou remplissage partiel -> jamais de prix
     fabriqué (#469) ni de position nue laissée après annulation du stop : reprotection via
     _repose_stop_and_alert() (core/maker_exit_watcher.py), le trade n'est pas clôturé.
   - Remplissage complet -> PnL net (compute_net_pnl), close_reason=f"signal_sell_score{score}",
     cycle_id=CYCLE_ID.
5. Notification Telegram, sauvegarde atomique de l'historique dès qu'un état a changé.

Exécuté par Claude en Phase 3, après phase3_scoring.py :
    python3 __PROJECT_DIR__/binance-bot/core/phases/phase3_signal_sell.py __CYCLE_ID__

Stdout : PHASE3_SIGNAL_SELL_DONE|closed=N
Output : /tmp/cycle_{CYCLE_ID}_phase3_signal_sell_output.json
"""
import sys
import os
import json
import math
import time
import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core.maker_exit_watcher import _repose_stop_and_alert  # noqa: E402
from core.trade_helpers import tg, binance, _load_config, _save_trade_history_atomic, compute_net_pnl, kraken_coin_balance  # noqa: E402

CYCLE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

_QTY_EPSILON = 1e-9

# Chemin fixe volontaire (contrat avec prompts/phases/phase3_scoring.txt) : neutralisation
# bandit temporaire, à lever avec le déplacement /tmp -> state/ (#392, #403)
in_path = f"/tmp/cycle_{CYCLE_ID}_phase3_signal_sell_input.json"  # nosec B108
with open(in_path) as f:
    inp = json.load(f)

sell_candidates = inp.get("sell_candidates", [])
cfg = inp.get("config") or _load_config()

with open(os.path.join(PROJECT_DIR, "state", "trade_history.json")) as f:
    history = json.load(f)

closed_count = 0
history_changed = False

for sc in sell_candidates:
    coin = sc["coin"]
    score = sc["score"]
    pair = f"{coin}USDC"

    open_trade = next((t for t in history if t.get("status") == "open" and t.get("coin") == coin), None)
    if not open_trade:
        continue

    sl_txid = open_trade.get("sl_order_txid")
    entry_price = float(open_trade.get("entry_price", 0))
    entry_fee_usdc = float(open_trade.get("entry_fee_usdc", 0) or 0)
    trade_qty = float(open_trade.get("quantity", 0))
    pending = {
        "trade_id": open_trade.get("trade_id"),
        "coin": coin,
        "pair": pair,
        "stop_price": open_trade.get("stop_price"),
    }

    # Step 1 : annuler le stop actif avant de vendre (contrainte hold_trade Kraken, cf. #390). À
    # partir d'ici la position peut être sans stop : tout `except` de ce script reste volontairement
    # large (`Exception`, jamais un sous-ensemble de types précis) -- sur ce chemin, une exception
    # non rattrapée coûte une position non protégée, la précision du typage passe après (#476 review).
    if sl_txid:
        try:
            binance("order", "cancel", sl_txid, "-o", "json", "--yes")
        except Exception as e:
            tg(f"⚠️ {coin} : annulation SL échouée avant vente sur signal — stop conservé, {e}")
            continue

    # Step 2 : quantité = min(trade_history, solde réel) tronquée au pas Kraken (#472, XRP 18/08).
    # kraken_coin_balance résout les actifs historiques préfixés (ETH -> XETH, etc., #476) ; si
    # l'actif reste introuvable dans le solde, on retombe sur trade_qty comme pour un échec Kraken
    # -- jamais sur 0, pour ne pas confondre une clé introuvable avec un solde réellement nul.
    # Panne de l'appel Kraken (réseau, JSON invalide) vs alias manquant pour un solde pourtant reçu
    # sont distingués (#476 review) : le second signale un défaut de code (table incomplète), pas un
    # aléa réseau -- il doit être visible, pas avalé en silence comme le bug initial.
    try:
        balance_raw = binance("balance", "-o", "json")
        balance = json.loads(balance_raw)
    except Exception:
        coin_balance = trade_qty
    else:
        try:
            coin_balance = kraken_coin_balance(balance, coin)
        except KeyError:
            tg(f"⚠️ {coin} : actif introuvable dans le solde Kraken — alias manquant, vente sur trade_qty")
            coin_balance = trade_qty

    try:
        pairs_raw = binance("pairs", "--pair", pair, "-o", "json")
        pair_data = json.loads(pairs_raw).get(pair, {})
        lot_dec = int(pair_data.get("lot_decimals", 8))
        ordermin = float(pair_data.get("ordermin", 0) or 0)
    except Exception:
        lot_dec = 8
        ordermin = 0.0
    step = 10 ** (-lot_dec)
    sell_qty = round(math.floor(min(trade_qty, coin_balance) / step) * step, lot_dec)
    # Un reliquat plus petit que le pas de la paire (ou son ordermin) n'est de toute façon pas
    # vendable ni protégeable par un nouvel ordre -> pas économiquement significatif (#472 review).
    untradeable_threshold = max(step, ordermin)

    if sell_qty <= 0:
        tg(f"⚠️ {coin} : solde disponible nul pour la vente sur signal — position reprotégée")
        _repose_stop_and_alert(pending, history, trade_qty, reason="solde disponible nul avant vente sur signal", context="vente sur signal")
        history_changed = True
        continue

    # Step 3 : SELL MARKET. Le stop est déjà annulé (Step 1) : `except Exception` large et non un
    # sous-ensemble de types précis (ValueError, RuntimeError...) est délibéré ici -- ça inclut
    # notamment subprocess.TimeoutExpired et OSError levés par binance() (#476 review), pour
    # garantir que toute panne à cet endroit déclenche la reprotection plutôt que de laisser le
    # script planter avec la position vendue-en-doute et sans stop.
    try:
        sell_raw = binance("order", "sell", pair, str(sell_qty), "--type", "market", "-o", "json", "--yes")
        sell_resp = json.loads(sell_raw) if sell_raw.strip() else {}
        sell_txid = (sell_resp.get("txid") or [None])[0]
        if not sell_txid:
            raise RuntimeError("pas de txid")
    except Exception as e:
        tg(f"⚠️ Échec SELL MARKET signal {coin}: {e}")
        _repose_stop_and_alert(pending, history, sell_qty, reason=f"vente au marché échouée : {e}", context="vente sur signal")
        history_changed = True
        continue

    # Step 4 : query du fill, 3 tentatives / 2s (identique au comportement constaté en prod, #472)
    vol_exec = 0.0
    cost = 0.0
    fee = 0.0
    for attempt in range(3):
        time.sleep(2)
        try:
            q_raw = binance("query-orders", sell_txid, "-o", "json")
            order_info = json.loads(q_raw).get(sell_txid, {})
            vol_exec = float(order_info.get("vol_exec", 0) or 0)
            cost = float(order_info.get("cost", 0) or 0)
            fee = float(order_info.get("fee", 0) or 0)
            if vol_exec > 0:
                break
        except Exception:
            pass

    if vol_exec <= _QTY_EPSILON:
        # Fill introuvable après 3 tentatives : jamais de prix fabriqué (#469, règle « marquer,
        # jamais réécrire ») -> le trade n'est pas clôturé, la position est reprotégée comme un
        # échec de vente. Si la vente a réellement eu lieu, le repose échouera (solde insuffisant)
        # et rendra le problème visible plutôt que de l'enterrer sous un PnL inventé.
        tg(f"⚠️ {coin} : fill introuvable après 3 tentatives (vente sur signal) — position reprotégée")
        _repose_stop_and_alert(pending, history, sell_qty, reason="fill introuvable après 3 tentatives (signal_sell)", context="vente sur signal")
        history_changed = True
        continue

    # Reliquat mesuré contre la position (trade_qty), pas contre l'ordre (sell_qty) : sell_qty
    # est déjà plafonné au solde réel (Step 2), donc un reliquat mesuré contre sell_qty masque la
    # partie de la position que ce plafonnement a exclue de la vente (#472 review).
    remaining_qty = trade_qty - vol_exec
    if remaining_qty > untradeable_threshold:
        # Remplissage partiel : le reliquat reste une position suivie et protégée, pas de trade
        # clôturé sur une quantité qui n'a pas été réellement vendue (#472).
        tg(f"⚠️ {coin} : remplissage partiel signal_sell ({vol_exec}/{trade_qty}) — reliquat reprotégé")
        _repose_stop_and_alert(pending, history, remaining_qty, reason=f"remplissage partiel signal_sell (vol_exec={vol_exec})", context="vente sur signal")
        history_changed = True
        continue

    # Step 5 : PnL net sur la quantité RÉELLEMENT vendue (vol_exec), jamais sur trade_qty — un
    # reliquat inférieur à untradeable_threshold n'est pas vendable, il est absorbé silencieusement
    # (#472 review) plutôt que de gonfler artificiellement le PnL enregistré.
    exit_price = cost / vol_exec
    exit_fee_usdc = fee
    net = compute_net_pnl(entry_price, exit_price, vol_exec, entry_fee_usdc, exit_fee_usdc)

    open_trade.update({
        "status": "closed",
        "quantity": vol_exec,
        "exit_price": exit_price,
        "exit_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "entry_fee_usdc": entry_fee_usdc,
        "exit_fee_usdc": exit_fee_usdc,
        "fees_usdc": net["fees_usdc"],
        "pnl_gross_usdc": net["pnl_gross_usdc"],
        "pnl_usdc": net["pnl_usdc"],
        "pnl_gross_pct": net["pnl_gross_pct"],
        "pnl_pct": net["pnl_pct"],
        "close_reason": f"signal_sell_score{score}",
        "cycle_id": CYCLE_ID,
    })
    closed_count += 1
    history_changed = True

    emoji = "✅" if net["pnl_usdc"] >= 0 else "📉"
    tg(
        f"{emoji} Signal SELL {coin} (score {score}/10)\n"
        f"Prix sortie : {exit_price:.4f} USDC\n"
        f"PnL net : {net['pnl_usdc']:+.2f} USDC ({net['pnl_pct']:+.1f}%)"
    )

if history_changed:
    _save_trade_history_atomic(history)

print(f"PHASE3_SIGNAL_SELL_DONE|closed={closed_count}")
# Chemin fixe volontaire (contrat avec prompts/phases/phase3_scoring.txt) : neutralisation
# bandit temporaire, à lever avec le déplacement /tmp -> state/ (#392, #403)
out_path = f"/tmp/cycle_{CYCLE_ID}_phase3_signal_sell_output.json"  # nosec B108
with open(out_path, "w") as f:
    json.dump({"closed": closed_count}, f)
