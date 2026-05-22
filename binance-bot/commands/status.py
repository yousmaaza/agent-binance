"""Commande /status — retourne une str (compatible Telegram et CLI)."""
import json
import subprocess

from core.env import PROJECT_DIR
from config.app import APP_CONFIG


def run_status(fmt_next_fn=None) -> str:
    fmt_next = fmt_next_fn() if fmt_next_fn else "–"
    alloc_pct = APP_CONFIG.get("usdc_allocation_pct", 0.40)
    binance_profile = APP_CONFIG.get("binance_profile", "agent-profile")
    try:
        account = subprocess.run(
            ["binance-cli", "spot", "get-account", "--profile", binance_profile],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        orders = subprocess.run(
            ["binance-cli", "spot", "get-open-orders", "--profile", binance_profile],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        data = json.loads(account.stdout)
        balances = [b for b in data["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]
        usdc = next((b for b in balances if b["asset"] == "USDC"), {"free": "0", "locked": "0"})
        free = float(usdc["free"])
        budget = round(free * alloc_pct, 2)

        lines = ["📊 <b>Portfolio actuel</b>\n"]
        lines.append(f"💵 USDC libre : <code>{free:.2f}</code> (budget {int(alloc_pct*100)}% = <code>{budget:.2f}</code>)")
        lines.append(f"🔒 USDC lockés : <code>{float(usdc['locked']):.2f}</code>\n")

        non_usdc = [b for b in balances if b["asset"] not in ("USDC", "LDUSDC") and not b["asset"].startswith("LD")]
        if non_usdc:
            lines.append("<b>Positions :</b>")
            for b in non_usdc:
                if float(b["locked"]) > 0:
                    lines.append(f"  <code>{b['asset']}</code> : {b['locked']} (locked)")

        open_orders = json.loads(orders.stdout) if orders.stdout.strip() else []
        if open_orders:
            lines.append(f"\n<b>Ordres ouverts ({len(open_orders)}) :</b>")
            for o in open_orders[:8]:
                side_emoji = "🟢" if o["side"] == "BUY" else "🔴"
                lines.append(f"  {side_emoji} {o['symbol']} {o['type']} @ {float(o['price']):.4g} × {float(o['origQty']):.4g}")

        try:
            with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
                history = json.load(f)
            open_trades = [t for t in history if t.get("status") == "open"]
            if open_trades:
                lines.append(f"\n<b>Trades agent actifs ({len(open_trades)}) :</b>")
                for t in open_trades:
                    lines.append(f"  🎯 {t['coin']} @ {t['entry_price']:.4g} | Stop: {t['stop_price']:.4g} | TP: {t['tp_price']:.4g}")
        except Exception:
            pass

        lines.append(f"\n⏰ <b>Prochain cycle auto</b> : <code>{fmt_next}</code>")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Erreur /status : {e}"
