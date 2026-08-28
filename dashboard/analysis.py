"""Analyses recalculées à chaque affichage — jamais de phrase d'interprétation figée en dur
(#432) : la maquette contient des constats déduits des données, ils doivent rester vrais quand
les données changent."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from timeutil import parse_iso

# Vulgarisation des skip_type (même mapping que binance-bot/commands/perf.py, cf. CLAUDE.md).
SKIP_LABELS = {
    "TYPE_A": "score de signal trop faible",
    "TYPE_B": "montant trop petit pour trader",
    "TYPE_C": "conditions de marché dégradées",
    "TYPE_D": "crypto indisponible ou peu liquide",
}


def blocking_reasons(cycles: list) -> dict:
    """Répartition des skip_type sur les décisions des cycles fournis, avec le motif dominant."""
    counts: Counter = Counter()
    for c in cycles:
        for d in (c.get("decisions") or []):
            st = d.get("skip_type")
            if st:
                counts[st] += 1

    total = sum(counts.values())
    breakdown = [
        {
            "type": t,
            "label": SKIP_LABELS.get(t, t),
            "count": n,
            "pct": round(n / total * 100) if total else 0,
        }
        for t, n in counts.most_common()
    ]

    if not breakdown:
        comment = "Aucun skip enregistré sur cette période."
    else:
        top = breakdown[0]
        comment = f"{top['label'].capitalize()} est le principal frein ({top['pct']}% des skips)."

    return {"breakdown": breakdown, "total": total, "comment": comment}


def _success_rate(cycles: list) -> Optional[float]:
    if not cycles:
        return None
    ok = sum(1 for c in cycles if c.get("status") not in ("error",) and c.get("error_type") is None)
    return round(ok / len(cycles) * 100)


def reliability_by_period(cycles: list, now: Optional[datetime] = None) -> dict:
    """Taux de cycles sans erreur sur 7j / 30j / au-delà, avec une phrase de tendance recalculée
    (jamais "la fiabilité progresse" en dur : ça se vérifie à chaque fois sur les deux fenêtres)."""
    now = now or datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    recent_7d, recent_30d = [], []
    for c in cycles:
        dt = parse_iso(c.get("timestamp"))
        if dt is None:
            continue
        if dt >= cutoff_7d:
            recent_7d.append(c)
        if dt >= cutoff_30d:
            recent_30d.append(c)

    rate_7d = _success_rate(recent_7d)
    rate_30d = _success_rate(recent_30d)

    if rate_7d is None or rate_30d is None:
        trend_comment = "Pas assez de cycles récents pour évaluer une tendance."
    elif rate_7d > rate_30d:
        trend_comment = f"La fiabilité progresse : {rate_7d}% sur 7 jours contre {rate_30d}% sur 30 jours."
    elif rate_7d < rate_30d:
        trend_comment = f"La fiabilité recule : {rate_7d}% sur 7 jours contre {rate_30d}% sur 30 jours."
    else:
        trend_comment = f"La fiabilité est stable, à {rate_7d}%."

    return {
        "rate_7d": rate_7d,
        "rate_30d": rate_30d,
        "count_7d": len(recent_7d),
        "count_30d": len(recent_30d),
        "comment": trend_comment,
    }
