"""Analyse hebdomadaire rédigée par Claude pour le dashboard (#453) — une fois par semaine ISO,
déclenchée depuis main_loop() comme l'auto-scheduler 4h (cf. CLAUDE.md règle 7).

Le garde-fou central : après génération, tout nombre du texte produit doit être retrouvé dans
la charge utile transmise (`data_snapshot`), tel quel ou dérivé par une opération simple (somme,
pourcentage, différence). Un nombre non rattachable fait échouer la génération — l'absence de
preuve ne vaut jamais preuve de conformité. En cas d'échec (contrôle numérique, quota, timeout,
Mongo absent), aucun document n'est écrit : le dashboard retombe sur analysis.weekly_note()."""
import json
import math
import os
import re
import statistics
import subprocess
from datetime import datetime, timedelta, timezone

from loguru import logger

from config.llm import WEEKLY_ANALYSIS_CLI_FLAGS, WEEKLY_ANALYSIS_TIMEOUT_S
from core.env import MONGO_URI, PROJECT_DIR
from core.timing import iso_week_key, parse_dt
from storage.mongo import mongo_repo

_HISTORY_PATH = os.path.join(PROJECT_DIR, "state", "trade_history.json")

# Sous ce seuil de trades clôturés sur 7 jours, la fenêtre est élargie à 30 jours (#453) —
# 6 trades/semaine est le régime observé au cadrage, largement sous tout seuil raisonnable.
MIN_TRADES_7D = 10
WIDE_WINDOW_DAYS = 30

# Ne sont vérifiés que les nombres qui constituent une AFFIRMATION FINANCIÈRE (#458) : ceux
# qui portent une décimale, ou qui sont suivis d'un marqueur d'unité. Un entier nu — une date
# (« le 31 août »), une durée (« sur 7 jours »), un ordinal — relève de la prose et n'affirme
# rien sur l'argent. L'ancienne regex les capturait tous, ce qui faisait échouer toute
# génération citant une date : aucune analyse n'a jamais été publiée à cause de cela.
_NUMBER_RE = re.compile(
    r"-?\d+\.\d+"                                  # tout décimal : 3.81, -11.87
    r"|-?\d+(?=\s*(?:%|USDC|USD|\$|€|EUR))"          # entier suivi d'une unité : 64 %, 45 USDC
)
_MONEY_TOLERANCE = 0.015  # arrondi flottant à 2 décimales, pas plus
_PCT_TOLERANCE = 1.0      # un pourcentage cité en prose est généralement arrondi à l'entier


# ---------------------------------------------------------------------------
# Sélection de la fenêtre + données
# ---------------------------------------------------------------------------

def _load_history() -> list:
    try:
        with open(_HISTORY_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _closed_since(history: list, since: datetime) -> list:
    out = []
    for t in history:
        if t.get("status") != "closed":
            continue
        dt = parse_dt(t.get("exit_date"))
        if dt is not None and dt >= since:
            out.append(t)
    return out


def _select_window(history: list, now: datetime) -> dict:
    trades_7d = _closed_since(history, now - timedelta(days=7))
    if len(trades_7d) >= MIN_TRADES_7D:
        return {"days": 7, "trades": trades_7d, "widened": False}
    trades_30d = _closed_since(history, now - timedelta(days=WIDE_WINDOW_DAYS))
    return {"days": WIDE_WINDOW_DAYS, "trades": trades_30d, "widened": True}


def _aggregate(trades: list) -> dict:
    net = sum((t.get("pnl_usdc") or 0) for t in trades)
    fees = sum(f for t in trades if (f := t.get("fees_usdc")) is not None)
    return {
        "count": len(trades),
        "gross_usdc": round(net + fees, 2),
        "fees_usdc": round(fees, 2),
        "net_usdc": round(net, 2),
        "wins": sum(1 for t in trades if (t.get("pnl_usdc") or 0) > 0),
        "losses": sum(1 for t in trades if (t.get("pnl_usdc") or 0) < 0),
    }


def _significance(trades: list) -> dict:
    """Verdict statistique sur la moyenne par trade — transmis à Claude pour qu'il puisse écrire
    « rien de concluant » plutôt que fabriquer un récit sur un échantillon insuffisant (#453)."""
    pnls = [round(t.get("pnl_usdc") or 0, 2) for t in trades]
    n = len(pnls)
    if n < 2:
        return {
            "n": n, "mean_usdc": round(pnls[0], 2) if n == 1 else None,
            "stdev_usdc": None, "ci95_low": None, "ci95_high": None,
            "conclusive": False, "n_required_for_significance": None,
        }
    mean = statistics.mean(pnls)
    stdev = statistics.stdev(pnls)
    half_width = 1.96 * stdev / math.sqrt(n)
    ci_low, ci_high = mean - half_width, mean + half_width
    n_required = math.ceil((1.96 * stdev / mean) ** 2) if mean != 0 else None
    return {
        "n": n,
        "mean_usdc": round(mean, 2),
        "stdev_usdc": round(stdev, 2),
        "ci95_low": round(ci_low, 2),
        "ci95_high": round(ci_high, 2),
        "conclusive": not (ci_low <= 0 <= ci_high),
        "n_required_for_significance": n_required,
    }


def _cycles_summary(cycles: list) -> dict:
    with_trade = sum(
        1 for c in cycles
        if ((c.get("execution") or {}).get("executed", c.get("executed", 0)) or 0) > 0
    )
    errors = sum(1 for c in cycles if c.get("status") == "error" or c.get("error_type") is not None)
    return {"total": len(cycles), "with_trade": with_trade, "errors": errors}


def _previous_week_key(week_key: str) -> str:
    year, week = week_key.split("-W")
    monday = datetime.fromisocalendar(int(year), int(week), 1).replace(tzinfo=timezone.utc)
    return iso_week_key(monday - timedelta(days=7))


def _previous_week_summary(week_key: str) -> dict | None:
    """Contexte de la semaine précédente — la fenêtre élargie ramène souvent les mêmes constats
    plusieurs semaines de suite : Claude doit pouvoir dire ce qui a changé (#453, piège)."""
    doc = mongo_repo.find_weekly_analysis(_previous_week_key(week_key))
    if not doc:
        return None
    snapshot = doc.get("data_snapshot") or {}
    return {"window_days": snapshot.get("window_days"), "aggregate": snapshot.get("aggregate")}


def _net_by(trades: list, key_fn) -> dict:
    """Net et effectif regroupés par une clé — les deux ensemble : un total sans son effectif
    laisse croire à une tendance là où il n'y a parfois qu'un seul trade."""
    grouped: dict = {}
    for trade in trades:
        bucket = grouped.setdefault(key_fn(trade), {"net_usdc": 0.0, "count": 0})
        bucket["net_usdc"] += trade.get("pnl_usdc") or 0
        bucket["count"] += 1
    for bucket in grouped.values():
        bucket["net_usdc"] = round(bucket["net_usdc"], 2)
    return grouped


def _build_payload(window: dict, cycles: list, now: datetime, week_key: str) -> dict:
    trades = window["trades"]
    return {
        "week": week_key,
        "generated_at": now.isoformat(),
        "window_days": window["days"],
        "window_widened": window["widened"],
        "trades": [
            {
                "coin": t.get("coin"),
                "pnl_usdc": round(t.get("pnl_usdc") or 0, 2),
                "fees_usdc": round(t["fees_usdc"], 2) if t.get("fees_usdc") is not None else None,
                "close_reason": t.get("close_reason"),
                "exit_date": t.get("exit_date"),
            }
            for t in trades
        ],
        "aggregate": _aggregate(trades),
        # Sous-totaux par motif de sortie et par crypto (#465). Une analyse cite naturellement
        # « les stops ont coûté X » ou « TRUMP pèse Y » : sans ces valeurs dans la charge utile,
        # le modèle les recalcule depuis la liste des trades et le contrôle numérique les rejette
        # comme non rattachables. C'est ce qui a bloqué la génération du 05/09 sur -33.04, le net
        # réel des sorties au stop. Les fournir sert deux fois : le modèle n'a plus à les dériver,
        # et le garde-fou les reconnaît.
        "by_close_reason": _net_by(trades, lambda t: t.get("close_reason") or "non renseignée"),
        "by_coin": _net_by(trades, lambda t: t.get("coin") or "?"),
        "significance": _significance(trades),
        "cycles": _cycles_summary(cycles),
        "previous_week": _previous_week_summary(week_key),
    }


# ---------------------------------------------------------------------------
# Appel Claude
# ---------------------------------------------------------------------------

def _build_prompt(payload: dict) -> str:
    widened_note = (
        ", et précise explicitement qu'elle a été élargie car trop peu de trades sur 7 jours"
        if payload["window_widened"] else ""
    )
    return (
        "Tu rédiges la note d'analyse hebdomadaire du dashboard d'un bot de trading crypto, "
        "pour un lecteur francophone non-spécialiste.\n\n"
        "Données de la période (JSON, chiffres déjà calculés) :\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Consignes :\n"
        "- Analyse librement : ce qui mérite attention, incidents isolés, écart entre réglage et "
        "réel, ce qui a changé depuis `previous_week` s'il est présent.\n"
        f"- Indique toujours la période couverte ({payload['window_days']} jours){widened_note}.\n"
        "- `significance` donne le verdict statistique sur la moyenne par trade : si `conclusive` "
        "est faux, dis explicitement qu'aucune conclusion sur la stratégie n'est possible à ce "
        "stade (échantillon trop petit), sans fabriquer de récit de performance.\n"
        "- N'écris QUE des nombres présents tels quels dans le JSON ci-dessus. Ne calcule rien "
        "toi-même : les sous-totaux utiles y figurent déjà (`aggregate` pour la période, "
        "`by_close_reason` par motif de sortie, `by_coin` par crypto, `significance` pour la "
        "statistique). Un nombre que tu calcules, même exactement, fera échouer la publication — "
        "un contrôle automatique rejette tout chiffre qu'il ne retrouve pas dans ces données.\n"
        "- Écris les nombres avec un point comme séparateur décimal (ex: 12.50), jamais de "
        "virgule : un contrôle automatique doit pouvoir les relire.\n"
        "- Réponds uniquement par le texte de la note (3 à 6 phrases), sans titre ni markdown."
    )


def _call_claude(prompt: str) -> tuple[str | None, float | None]:
    env = os.environ.copy()
    for k in ("CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
              "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH"):
        env.pop(k, None)

    try:
        result = subprocess.run(
            ["claude"] + WEEKLY_ANALYSIS_CLI_FLAGS + [prompt],
            capture_output=True, text=True, cwd=PROJECT_DIR, env=env,
            timeout=WEEKLY_ANALYSIS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[WeeklyAnalysis] Timeout appel Claude")
        return None, None

    if result.returncode != 0:
        logger.warning(f"[WeeklyAnalysis] Claude exit={result.returncode} : {result.stderr[:300]}")
        return None, None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("[WeeklyAnalysis] Sortie Claude non-JSON")
        return None, None

    if data.get("is_error"):
        logger.warning(f"[WeeklyAnalysis] Claude is_error : {str(data.get('result'))[:300]}")
        return None, None

    text = (data.get("result") or "").strip()
    return (text or None), data.get("total_cost_usd")


# ---------------------------------------------------------------------------
# Contrôle numérique a posteriori — le garde-fou central de #453
# ---------------------------------------------------------------------------

def _extract_numbers(text: str) -> list[float]:
    """Les nombres du texte qui affirment quelque chose sur l'argent ou les taux (#458).

    Assouplir ici ne rouvre pas la faille de #453 : ce qui y était démontré — un taux de
    réussite fabriqué, des pourcentages libres, un montant inventé — porte toujours une unité
    ou une décimale, et reste donc vérifié.

    LIMITE ASSUMÉE : un effectif écrit sans unité (« 27 trades clôturés ») n'est plus vérifié.
    Un entier nu sous 31 est indistinguable d'un quantième en prose ; il faut choisir entre
    laisser passer les comptes ou rejeter toute date, et rejeter les dates bloquait 100 % des
    générations. Les effectifs restent des faits de moindre portée qu'un montant ou un taux."""
    return [float(m) for m in _NUMBER_RE.findall(text)]


def _base_numbers(payload: dict) -> set[float]:
    """Tout nombre présent tel quel dans la charge utile (valeur signée + valeur absolue)."""
    numbers: set[float] = set()

    def _walk(value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            numbers.add(round(float(value), 2))
            numbers.add(round(abs(float(value)), 2))
        elif isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for v in value:
                _walk(v)

    _walk(payload)
    return numbers


_AGGREGATE_KEYS = ("gross_usdc", "fees_usdc", "net_usdc", "count", "wins", "losses")
_SIGNIFICANCE_KEYS = ("mean_usdc", "stdev_usdc", "ci95_low", "ci95_high", "n_required_for_significance")


def _aggregate_values(payload: dict) -> list[float]:
    """Le sous-ensemble « agrégats » utilisé pour dériver sommes/différences/pourcentages —
    volontairement restreint (pas les trades individuels entre eux) pour que le contrôle reste
    strict : croiser tous les nombres deux à deux rendrait presque n'importe quel nombre acceptable."""
    values = []
    agg = payload.get("aggregate") or {}
    for k in _AGGREGATE_KEYS:
        if agg.get(k) is not None:
            values.append(float(agg[k]))
    prev_agg = (payload.get("previous_week") or {}).get("aggregate") or {}
    for k in _AGGREGATE_KEYS:
        if prev_agg.get(k) is not None:
            values.append(float(prev_agg[k]))
    sig = payload.get("significance") or {}
    for k in _SIGNIFICANCE_KEYS:
        if sig.get(k) is not None:
            values.append(float(sig[k]))
    return values


# Un « incident isolé » (cf. #453, exemple TRUMP) désigne les mouvements les plus marquants de
# la période, pas un trade quelconque parmi la fenêtre — sinon le catalogue de ratios nommés
# grossirait avec le nombre de trades et retomberait dans le même travers que le produit croisé.
_NOTABLE_TRADES_COUNT = 3


def _notable_trades(trades: list) -> list:
    with_pnl = [t for t in trades if t.get("pnl_usdc") is not None]
    return sorted(with_pnl, key=lambda t: abs(t["pnl_usdc"]), reverse=True)[:_NOTABLE_TRADES_COUNT]


def _named_percentages(payload: dict) -> set[float]:
    """Pourcentages autorisés dans le texte — uniquement des ratios nommables, pas un produit
    croisé de toutes les paires de nombres (#453, durci après audit : le produit croisé
    recouvrait ~90% des entiers 0-100, rendant le contrôle décoratif sur la moitié des chiffres
    d'une analyse). Chaque valeur correspond à une grandeur désignable : taux de trades
    gagnants/perdants, frais rapportés au brut, part de cycles avec ordre/en erreur, part des
    mouvements les plus marquants dans le résultat net/brut — même catalogue pour la semaine
    précédente. Le catalogue reste borné (quelques dizaines de valeurs) quel que soit le nombre
    de trades de la fenêtre : un pourcentage qui n'en dérive pas n'a rien à faire dans le texte."""
    values: set[float] = set()

    def _rate_pair(part_a, part_b, total):
        if not total:
            return
        if part_a is not None:
            values.add(part_a / total * 100)
        if part_b is not None:
            values.add(part_b / total * 100)

    def _share_of(agg: dict) -> None:
        count = agg.get("count") or 0
        _rate_pair(agg.get("wins"), agg.get("losses"), count)
        gross = agg.get("gross_usdc")
        if gross:
            if agg.get("fees_usdc") is not None:
                values.add(agg["fees_usdc"] / gross * 100)
            if agg.get("net_usdc") is not None:
                values.add(agg["net_usdc"] / gross * 100)

    _share_of(payload.get("aggregate") or {})
    _share_of((payload.get("previous_week") or {}).get("aggregate") or {})

    cyc = payload.get("cycles") or {}
    _rate_pair(cyc.get("with_trade"), cyc.get("errors"), cyc.get("total") or 0)

    agg = payload.get("aggregate") or {}
    gross, net = agg.get("gross_usdc"), agg.get("net_usdc")
    for t in _notable_trades(payload.get("trades", [])):
        pnl = t["pnl_usdc"]
        if gross:
            values.add(pnl / gross * 100)  # part de ce mouvement dans le résultat brut
        if net:
            values.add(pnl / net * 100)    # part de ce mouvement dans le résultat net (ex: #453, TRUMP)

    rounded = {round(v, 2) for v in values}
    return rounded | {round(abs(v), 2) for v in rounded}


def _allowed_numbers(payload: dict) -> tuple[set[float], set[float]]:
    """Retourne (montants, pourcentages) — tolérances différentes : un pourcentage cité en
    prose est arrondi à l'entier, un montant ne devrait dévier que d'une erreur de flottant."""
    money = _base_numbers(payload)
    aggregates = _aggregate_values(payload)

    for a in aggregates:
        for b in aggregates:
            if a == b:
                continue
            money.add(round(a + b, 2))
            money.add(round(a - b, 2))

    return money, _named_percentages(payload)


def _verify_numbers(text: str, payload: dict) -> bool:
    extracted = _extract_numbers(text)
    if not extracted:
        return True
    money, percentages = _allowed_numbers(payload)
    for n in extracted:
        if any(abs(n - m) <= _MONEY_TOLERANCE for m in money):
            continue
        if any(abs(n - p) <= _PCT_TOLERANCE for p in percentages):
            continue
        logger.warning(f"[WeeklyAnalysis] Nombre non rattaché aux données : {n}")
        return False
    return True


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def _run(now: datetime, week_key: str, trigger: str) -> None:
    if mongo_repo.find_weekly_analysis(week_key) is not None:
        logger.info(f"[WeeklyAnalysis] {week_key} déjà généré — idempotence.")
        return

    history = _load_history()
    window = _select_window(history, now)
    cycles = mongo_repo.find_cycles_since(now - timedelta(days=window["days"]))

    if not window["trades"] and not cycles:
        logger.info("[WeeklyAnalysis] Aucun trade ni cycle sur la fenêtre élargie — pas de génération.")
        return

    payload = _build_payload(window, cycles, now, week_key)
    text, cost_usd = _call_claude(_build_prompt(payload))
    if not text:
        logger.warning("[WeeklyAnalysis] Appel Claude sans résultat exploitable — repli déterministe.")
        return

    if not _verify_numbers(text, payload):
        logger.warning("[WeeklyAnalysis] Contrôle numérique échoué — repli déterministe.")
        return

    mongo_repo.save_weekly_analysis({
        "_id": week_key,
        "generated_at": now.isoformat(),
        "window_days": window["days"],
        "window_widened": window["widened"],
        "text": text,
        "data_snapshot": payload,
        "cost_usd": cost_usd,
        "trigger": trigger,
    })
    logger.info(f"[WeeklyAnalysis] {week_key} généré ({window['days']}j, {len(window['trades'])} trades).")


def run_weekly_analysis(trigger: str = "auto", fmt_next_fn=None) -> None:
    """Point d'entrée appelé par main_loop() (#453). fmt_next_fn accepté par compatibilité avec
    _check_and_run_scheduled (même contrat que run_trade_workflow), non utilisé ici.

    Ne lève jamais : l'analyse est accessoire, un échec ne doit jamais toucher le cycle de
    trading (cf. CLAUDE.md, piège #453)."""
    if not MONGO_URI:
        return
    now = datetime.now(timezone.utc)
    week_key = iso_week_key(now)
    try:
        _run(now, week_key, trigger)
    except Exception as e:
        logger.error(f"[WeeklyAnalysis] Erreur inattendue : {e}")
