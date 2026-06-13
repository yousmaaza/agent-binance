"""Commande /status — retourne une str (compatible Telegram et CLI)."""
import json
import subprocess

from core.env import PROJECT_DIR
from config.app import APP_CONFIG


def _fetch_account_data(binance_profile: str) -> dict | None:
    """Récupère les données du compte Binance."""
    try:
        result = subprocess.run(
            ["binance-cli", "spot", "get-account", "--profile", binance_profile],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        return json.loads(result.stdout)
    except Exception:
        return None


def _fetch_open_orders(binance_profile: str) -> list:
    """Récupère les ordres ouverts."""
    try:
        result = subprocess.run(
            ["binance-cli", "spot", "get-open-orders", "--profile", binance_profile],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        return json.loads(result.stdout) if result.stdout.strip() else []
    except Exception:
        return []


def _format_usdc_section(balances: list, alloc_pct: float) -> list[str]:
    """Formate la section USDC."""
    usdc = next((b for b in balances if b["asset"] == "USDC"), {"free": "0", "locked": "0"})
    free = float(usdc["free"])
    budget = round(free * alloc_pct, 2)
    return [
        f"💵 USDC libre : <code>{free:.2f}</code> (budget {int(alloc_pct*100)}% = <code>{budget:.2f}</code>)",
        f"🔒 USDC lockés : <code>{float(usdc['locked']):.2f}</code>\n",
    ]


def _format_positions_section(balances: list) -> list[str]:
    """Formate la section des positions."""
    lines = []
    non_usdc = [b for b in balances if b["asset"] not in ("USDC", "LDUSDC") and not b["asset"].startswith("LD")]
    if non_usdc:
        lines.append("<b>Positions :</b>")
        for b in non_usdc:
            if float(b["locked"]) > 0:
                lines.append(f"  <code>{b['asset']}</code> : {b['locked']} (locked)")
    return lines


def _format_orders_section(open_orders: list) -> list[str]:
    """Formate la section des ordres ouverts."""
    lines = []
    if open_orders:
        lines.append(f"\n<b>Ordres ouverts ({len(open_orders)}) :</b>")
        for o in open_orders[:8]:
            side_emoji = "🟢" if o["side"] == "BUY" else "🔴"
            lines.append(f"  {side_emoji} {o['symbol']} {o['type']} @ {float(o['price']):.4g} × {float(o['origQty']):.4g}")
    return lines


def _format_trades_section(fmt_next: str) -> list[str]:
    """Formate la section des trades actifs."""
    lines = []
    try:
        with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
            history = json.load(f)
        open_trades = [t for t in history if t.get("status") == "open"]
        if open_trades:
            lines.append(f"\n<b>Trades agent actifs ({len(open_trades)}) :</b>")
            for t in open_trades:
                lines.append(f"  🎯 {t['coin']} @ {t['entry_price']:.4g} | Stop: {t['stop_price']:.4g} | TP: {t['tp_price']:.4g}")
    except Exception:
        pass  # File not found is okay
    lines.append(f"\n⏰ <b>Prochain cycle auto</b> : <code>{fmt_next}</code>")
    return lines


def run_status(fmt_next_fn=None) -> str:
    fmt_next = fmt_next_fn() if fmt_next_fn else "–"
    alloc_pct = APP_CONFIG.get("usdc_allocation_pct", 0.40)
    binance_profile = APP_CONFIG.get("binance_profile", "agent-profile")

    data = _fetch_account_data(binance_profile)
    if data is None:
        return "❌ Erreur /status : impossible de récupérer les données du compte"

    balances = [b for b in data["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]
    open_orders = _fetch_open_orders(binance_profile)

    lines = ["📊 <b>Portfolio actuel</b>\n"]
    lines.extend(_format_usdc_section(balances, alloc_pct))
    lines.extend(_format_positions_section(balances))
    lines.extend(_format_orders_section(open_orders))
    lines.extend(_format_trades_section(fmt_next))

    return "\n".join(lines)
