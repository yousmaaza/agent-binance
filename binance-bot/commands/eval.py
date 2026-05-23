"""Commande /eval — rapport hebdomadaire : performance, fiabilité, coût abonnement vs API."""
import json
from datetime import datetime, timedelta, timezone

from core.env import PROJECT_DIR
from storage.mongo import mongo_repo

_SUBSCRIPTION_COST_EUR_MONTH = 20.0


def run_eval(period_days: int = 7) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)

    trades_section = _trades_section(cutoff)
    cycles_section, cost_section = _cycles_and_cost_section(cutoff, period_days)
    risk_section = _risk_section()
    note = _stat_note(trades_section["n_closed"], period_days)

    lines = [f"📊 <b>Évaluation bot — {period_days} derniers jours</b>\n"]
    if cycles_section:
        lines.append(cycles_section)
    lines.append(trades_section["text"])
    if cost_section:
        lines.append(cost_section)
    lines.append(risk_section)
    if note:
        lines.append(note)

    return "\n".join(lines)


def _trades_section(cutoff: datetime) -> dict:
    try:
        with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
            history = json.load(f)
    except Exception:
        history = []

    closed = [
        t for t in history
        if t.get("status") == "closed"
        and t.get("exit_date")
        and _parse_dt(t["exit_date"]) >= cutoff
    ]
    open_pos = [t for t in history if t.get("status") == "open"]

    wins = [t for t in closed if (t.get("pnl_usdc") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl_usdc") or 0) <= 0]
    pnl_net = sum(t.get("pnl_usdc") or 0 for t in closed)
    avg_win = sum(t["pnl_usdc"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usdc"] for t in losses) / len(losses) if losses else 0
    ratio = abs(avg_win / avg_loss) if avg_loss != 0 else None
    win_rate = len(wins) / len(closed) * 100 if closed else None

    lines = [f"📈 <b>Performance</b> ({len(closed)} trades fermés)"]
    if closed:
        wr_str = f"{len(wins)}/{len(closed)} ({win_rate:.1f}%)"
        lines.append(f"  Win rate       : {wr_str}")
        lines.append(f"  Gain moyen     : +{avg_win:.2f} USDC")
        lines.append(f"  Perte moyenne  : {avg_loss:.2f} USDC")
        ratio_str = f"{ratio:.2f}x" if ratio is not None else "n/a (aucune perte)"
        lines.append(f"  Ratio G/P      : {ratio_str}")
        pnl_icon = "✅" if pnl_net > 0 else "❌"
        lines.append(f"  PnL net        : {pnl_net:+.2f} USDC {pnl_icon}")
    else:
        lines.append("  Aucun trade fermé sur la période")
    if open_pos:
        lines.append(f"  Positions ouvertes : {len(open_pos)}")

    return {"text": "\n".join(lines), "n_closed": len(closed), "pnl_net": pnl_net}


def _cycles_and_cost_section(cutoff: datetime, period_days: int) -> tuple[str, str]:
    db = mongo_repo._db()
    if db is None:
        return "", ""

    try:
        cycles = list(db.cycles.find({"timestamp": {"$gte": cutoff.isoformat()}}))
    except Exception:
        return "", ""

    if not cycles:
        return "", ""

    total = len(cycles)
    ok = sum(1 for c in cycles if c.get("status") == "completed")
    err = total - ok
    rate = ok / total * 100 if total else 0
    reliability = (
        f"🔄 <b>Fiabilité</b> : {total} cycles | {ok} OK | {err} erreur(s) ({rate:.0f}%)"
    )

    abo = [c for c in cycles if c.get("billing_mode", "abonnement") == "abonnement"]
    api = [c for c in cycles if c.get("billing_mode") == "api"]
    api_cost = sum(c.get("api_cost_usd") or 0 for c in api)
    abo_cost = _SUBSCRIPTION_COST_EUR_MONTH / 30 * period_days

    cost_lines = [f"💳 <b>Coût réel</b> (abonnement 20€/mois fixe)"]
    cost_lines.append(f"  Abonnement proratisé : ~{abo_cost:.2f}€ pour {period_days}j")
    cost_lines.append(f"  ├─ {len(abo)} cycle(s) abonnement — surcoût : 0€")
    if api:
        cost_lines.append(f"  └─ {len(api)} cycle(s) API — coût réel : ${api_cost:.4f}")
    else:
        cost_lines.append(f"  └─ 0 cycle API — aucun surcoût")
    api_str = f" + ${api_cost:.4f}" if api_cost > 0 else ""
    cost_lines.append(f"  Total période : ~{abo_cost:.2f}€{api_str}")

    return reliability, "\n".join(cost_lines)


def _risk_section() -> str:
    try:
        with open(f"{PROJECT_DIR}/state/trade_history.json") as f:
            history = json.load(f)
    except Exception:
        history = []

    pf = [t for t in history if t.get("status") == "open" and t.get("protection_failed")]
    icon = "⚠️" if pf else "✅"
    return f"🛡️ <b>Risque</b>\n  Positions sans stop-loss : {len(pf)} {icon}"


def _stat_note(n_closed: int, period_days: int) -> str:
    if n_closed < 30:
        return (
            f"\n📌 <i>{n_closed} trades sur {period_days}j — échantillon trop petit pour "
            f"conclure sur la stratégie. Attendre 4-8 semaines (~30 trades min).</i>"
        )
    return ""


def _parse_dt(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)
