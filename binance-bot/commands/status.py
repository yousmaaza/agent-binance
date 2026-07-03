"""Commande /status — retourne une str (compatible Telegram et CLI)."""
import json
import subprocess

from core.env import PROJECT_DIR, KRAKEN_CLI_PATH
from config.app import APP_CONFIG


def _fetch_account_data() -> dict | None:
    """Récupère les soldes Kraken. Retourne dict {asset: amount_str} ou None."""
    try:
        result = subprocess.run(
            [str(KRAKEN_CLI_PATH), "balance", "-o", "json"],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        return json.loads(result.stdout)
    except Exception:
        return None


def _fetch_open_orders() -> dict:
    """Récupère les ordres ouverts Kraken. Retourne {"open": {...}} ou {}."""
    try:
        result = subprocess.run(
            [str(KRAKEN_CLI_PATH), "open-orders", "-o", "json"],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except Exception:
        return {}


def _format_usdc_section(balance_data: dict, alloc_pct: float) -> list[str]:
    """Formate la section USDC."""
    usdc = float(balance_data.get("USDC", 0))
    budget = round(usdc * alloc_pct, 2)
    return [
        f"💵 USDC disponible : <code>{usdc:.2f}</code> (budget {int(alloc_pct*100)}% = <code>{budget:.2f}</code>)\n",
    ]


_STABLECOINS = {"USDC", "USDT", "BUSD", "FDUSD", "TUSD", "DAI", "USDP"}


def _format_positions_section(balance_data: dict) -> list[str]:
    """Formate la section des positions (actifs non-stablecoin avec solde > 0)."""
    lines = []
    non_stable = {a: v for a, v in balance_data.items()
                  if a not in _STABLECOINS and float(v) > 0}
    if non_stable:
        lines.append("<b>Positions :</b>")
        for asset, amount in non_stable.items():
            lines.append(f"  <code>{asset}</code> : {float(amount):.6g}")
    return lines


def _format_orders_section(open_orders: dict) -> list[str]:
    """Formate la section des ordres ouverts."""
    lines = []
    orders = open_orders.get("open", {})
    if orders:
        lines.append(f"\n<b>Ordres ouverts ({len(orders)}) :</b>")
        for o in list(orders.values())[:8]:
            descr = o.get("descr", {})
            side = descr.get("type", "?")
            side_emoji = "🟢" if side == "buy" else "🔴"
            pair = descr.get("pair", "?")
            order_type = descr.get("ordertype", "?").upper()
            price = float(descr.get("price", 0))
            qty = float(o.get("vol", 0))
            lines.append(f"  {side_emoji} {pair} {order_type} @ {price:.4g} × {qty:.4g}")
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
        pass
    lines.append(f"\n⏰ <b>Prochain cycle auto</b> : <code>{fmt_next}</code>")
    return lines


def run_status(fmt_next_fn=None) -> str:
    fmt_next = fmt_next_fn() if fmt_next_fn else "–"
    alloc_pct = APP_CONFIG.get("usdc_allocation_pct", 0.40)

    balance_data = _fetch_account_data()
    if balance_data is None:
        return "❌ Erreur /status : impossible de récupérer les données du compte"

    open_orders = _fetch_open_orders()

    lines = ["📊 <b>Portfolio actuel</b>\n"]
    lines.extend(_format_usdc_section(balance_data, alloc_pct))
    lines.extend(_format_positions_section(balance_data))
    lines.extend(_format_orders_section(open_orders))
    lines.extend(_format_trades_section(fmt_next))

    return "\n".join(lines)
