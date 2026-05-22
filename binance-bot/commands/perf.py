"""Commande /perf — retourne une str (compatible Telegram et CLI)."""
import json
import math

from core.env import PROJECT_DIR


def run_perf() -> str:
    try:
        with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
            history = json.load(f)
    except Exception:
        return "❌ Pas encore de données de trading."

    closed = [t for t in history if t.get("status") == "closed" and t.get("pnl_pct") is not None]

    if len(closed) < 2:
        open_count = len([t for t in history if t.get("status") == "open"])
        return (
            f"📈 Pas encore assez de trades fermés pour les stats.\n"
            f"Trades fermés : {len(closed)}\nTrades ouverts : {open_count}\n"
            f"(minimum 2 requis)"
        )

    returns = [t["pnl_pct"] for t in closed]
    pnl_usdc = [t["pnl_usdc"] for t in closed]

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_rate = len(wins) / len(returns) * 100
    expectancy = sum(returns) / len(returns)
    total_pnl = sum(pnl_usdc)

    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0001
        sharpe = (mean_r / std_r) * math.sqrt(2190) if std_r > 0 else 0
    else:
        sharpe = 0

    cumulative = peak = max_dd = 0
    for r in pnl_usdc:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    n = len(returns)
    mean_r = sum(returns) / n
    if n > 1:
        variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_err = math.sqrt(variance / n)
        t_stat = mean_r / std_err if std_err > 0 else 0
        abs_t = abs(t_stat)
        if n >= 30:
            z = abs_t / math.sqrt(2)
            t_val = 1 / (1 + 0.3275911 * z)
            poly = t_val * (0.254829592 + t_val * (-0.284496736 + t_val * (1.421413741 + t_val * (-1.453152027 + t_val * 1.061405429))))
            p_approx = max(0.001, min(2 * poly * math.exp(-z * z), 1.0))
        else:
            p_approx = None
    else:
        t_stat = p_approx = 0

    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    lines = [f"📈 <b>Performance — {len(closed)} trades fermés</b>\n"]
    lines.append(f"Win rate    : <code>{win_rate:.1f}%</code>  ({len(wins)}W / {len(losses)}L)")
    lines.append(f"Expectancy  : <code>{expectancy:+.2f}%</code> / trade")
    lines.append(f"Profit factor : <code>{profit_factor:.2f}</code>")
    lines.append(f"Moy. gain   : <code>{avg_win:+.2f}%</code>  |  Moy. perte : <code>{avg_loss:.2f}%</code>")
    lines.append(f"Sharpe      : <code>{sharpe:.2f}</code> (annualisé)")
    lines.append(f"Max drawdown: <code>-{max_dd:.2f} USDC</code>")
    lines.append(f"PnL total   : <code>{total_pnl:+.2f} USDC</code>\n")
    lines.append("📊 <b>Significativité statistique</b>")
    lines.append(f"t-stat : <code>{t_stat:.2f}</code>  |  n = {n}")
    if p_approx is not None:
        sig = "✅ Edge significatif (p &lt; 0.05)" if p_approx < 0.05 else "⚠️ Pas encore significatif"
        lines.append(f"p-value ≈ <code>{p_approx:.3f}</code>  →  {sig}")
    else:
        lines.append(f"⚠️ p-value : besoin de 30+ trades (progression : {n}/30)")

    open_trades = [t for t in history if t.get("status") == "open"]
    if open_trades:
        lines.append(f"\n🔓 Positions ouvertes : {len(open_trades)}")

    return "\n".join(lines)
