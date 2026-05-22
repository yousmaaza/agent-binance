"""Commande /cout — retourne une str (compatible Telegram et CLI)."""
from storage.mongo import mongo_repo


def run_cout() -> str:
    db = mongo_repo._db()
    if db is None:
        return "⚠️ MongoDB non configuré (MONGODB_URI absent ou invalide dans .env)."

    try:
        pipeline = [
            {"$match": {"api_cost_usd": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": None, "total": {"$sum": "$api_cost_usd"}, "count": {"$sum": 1}, "avg": {"$avg": "$api_cost_usd"}}},
        ]
        agg = list(db.cycles.aggregate(pipeline))
        if not agg:
            return "📭 Aucun cycle avec coût API enregistré. Lance /trade pour commencer."

        total, count, avg = agg[0]["total"], agg[0]["count"], agg[0]["avg"]

        top5 = list(
            db.cycles.find(
                {"api_cost_usd": {"$exists": True, "$ne": None}},
                {"cycle_id": 1, "api_cost_usd": 1, "orders_placed": 1},
            ).sort("api_cost_usd", -1).limit(5)
        )
        last = db.cycles.find_one(
            {"api_cost_usd": {"$exists": True, "$ne": None}},
            sort=[("timestamp", -1)],
        )

        lines = [f"💸 Coût API Claude — {count} cycle(s)\n"]
        lines.append(f"Total cumulé  : ${total:.4f}")
        lines.append(f"Coût moyen    : ${avg:.4f} / cycle")
        if last:
            lines.append(f"Dernier cycle : ${last.get('api_cost_usd', 0):.4f} ({last.get('cycle_id', '?')})")
        if top5:
            lines.append("\nTop 5 cycles les plus chers :")
            for doc in top5:
                nb = len(doc.get("orders_placed") or [])
                lines.append(f"  {doc.get('cycle_id', '?')} — ${doc.get('api_cost_usd', 0):.4f} ({nb} ordre(s))")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Erreur /cout : {e}"
