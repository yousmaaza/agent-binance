"""Commande /raisonnement — retourne une str (compatible Telegram et CLI)."""
from storage.mongo import mongo_repo


def run_raisonnement() -> str:
    db = mongo_repo._db()
    if db is None:
        return "⚠️ MongoDB non configuré (MONGODB_URI absent ou invalide dans .env)."

    try:
        doc = db.cycles.find_one(sort=[("timestamp", -1)])
    except Exception as e:
        return f"❌ Erreur Mongo : {e}"

    if not doc:
        return "📭 Aucun cycle en base. Lance /trade pour générer le premier."

    cycle_id = doc.get("cycle_id", "?")
    lines = [f"🧠 <b>Raisonnement — cycle {cycle_id}</b>"]
    lines.append(f"<i>{doc.get('timestamp', '?')} · status: {doc.get('status', '?')}</i>\n")

    p = doc.get("portfolio") or {}
    if p:
        lines.append(f"💼 Portfolio : <code>{p.get('total_usdc', 0):.2f}</code> USDC")
        lines.append(f"   Budget dispo : <code>{p.get('budget_disponible', 0):.2f}</code>")
        lines.append(f"   Positions ouvertes : {p.get('positions_ouvertes', 0)}\n")

    m = doc.get("market_context") or {}
    if m:
        lines.append(f"📊 Sentiment : <b>{m.get('sentiment', '?')}</b>")
        lines.append(f"   Coins analysés : {m.get('universe_size', 0)}\n")

    explanation = doc.get("explanation_fr", "")
    if explanation:
        lines.append("💬 <b>Explication</b>")
        lines.append(explanation)

    orders = doc.get("orders_placed") or []
    if orders:
        lines.append(f"\n✅ <b>{len(orders)} ordre(s) placé(s)</b>")
        for o in orders[:5]:
            lines.append(f"  • {o.get('coin')} score {o.get('score', '?')}/10")
    else:
        lines.append("\n🚫 <b>Aucun ordre placé ce cycle</b>")

    return "\n".join(lines)
