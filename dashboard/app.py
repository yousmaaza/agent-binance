"""Dashboard web du bot (#432) — app Flask indépendante, lecture seule sur MongoDB Atlas
(`cycles`, `dashboard_state`) + appel direct à l'API publique Kraken pour les prix courants.

Ne touche jamais à state/ ni n'écrit en base : c'est le bot (Phase 7) qui alimente Mongo."""
import os

from flask import Flask, redirect, render_template, request, session, url_for

import analysis
import settings
import viewdata
from auth import check_password, is_configured, login_required
from kraken_client import KrakenUnavailable, get_prices
from mongo_client import DashboardStateMissing, MongoUnavailable, get_dashboard_state, get_recent_cycles

app = Flask(__name__)
app.secret_key = settings.DASHBOARD_SECRET_KEY or "dev-insecure-key-set-DASHBOARD_SECRET_KEY"


@app.before_request
def _require_configuration():
    if request.endpoint in ("static",):
        return None
    if not is_configured():
        return render_template("not_configured.html"), 503
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if check_password(request.form.get("password", "")):
            session["authenticated"] = True
            return redirect(request.args.get("next") or url_for("dashboard_home"))
        error = "Mot de passe incorrect."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard_home():
    try:
        state = get_dashboard_state()
    except MongoUnavailable as e:
        return render_template("degraded.html", kind="mongo_unavailable", detail=str(e))
    except DashboardStateMissing as e:
        return render_template("degraded.html", kind="state_missing", detail=str(e))

    tz_name = viewdata.resolve_timezone(state, settings.DEFAULT_DISPLAY_TIMEZONE)
    fresh = viewdata.freshness(state, settings.STALE_THRESHOLD_MINUTES)

    open_positions = state.get("open_positions") or []
    coins = [p["coin"] for p in open_positions if p.get("coin")]
    kraken_error = None
    prices = {}
    if coins:
        try:
            prices = get_prices(coins)
        except KrakenUnavailable as e:
            kraken_error = str(e)

    financials = state.get("financials") or {}

    try:
        cycles = get_recent_cycles(settings.CYCLES_JOURNAL_LIMIT)
        cycles_error = None
    except MongoUnavailable as e:
        cycles = []
        cycles_error = str(e)

    results_view = {
        "financials": financials,
        "periods": viewdata.build_periods_table(financials.get("by_period") or {}),
        "equity_points": viewdata.equity_curve_points(financials.get("equity_curve") or []),
        "positions": viewdata.build_positions(open_positions, prices),
        "maker": viewdata.build_maker_summary(state.get("watchers") or {}),
        "kraken_error": kraken_error,
    }

    cycles_view = {
        "journal": [viewdata.build_cycle_row(c, tz_name) for c in cycles],
        "cadence": viewdata.build_cadence_band(cycles),
        "blocking": analysis.blocking_reasons(cycles),
        "reliability": analysis.reliability_by_period(cycles),
        "error": cycles_error,
    }

    return render_template(
        "dashboard.html",
        fresh=fresh,
        results=results_view,
        cycles=cycles_view,
        settings=state.get("config") or {},
        tz_name=tz_name,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))  # nosec B104 -- Railway route le trafic via un proxy, bind 0.0.0.0 requis
