"""Dashboard web du bot (#432) — app Flask indépendante, lecture seule sur MongoDB Atlas
(`cycles`, `dashboard_state`) + appel direct à l'API publique Kraken pour les prix courants.

Ne touche jamais à state/ ni n'écrit en base : c'est le bot (Phase 7) qui alimente Mongo."""
import os

import analysis
import settings
import viewdata
from auth import check_password, is_configured, login_required, safe_next_path
from flask import Flask, redirect, render_template, request, session, url_for
from kraken_client import KrakenUnavailable, get_prices
from mongo_client import (
    DashboardStateMissing,
    MongoUnavailable,
    get_cycles_for_grid,
    get_dashboard_state,
    get_latest_weekly_analysis,
    get_recent_cycles,
)
from timeutil import to_local

app = Flask(__name__)
app.secret_key = settings.DASHBOARD_SECRET_KEY or "dev-insecure-key-set-DASHBOARD_SECRET_KEY"
app.jinja_env.filters["price"] = viewdata.format_price
app.jinja_env.filters["localtime"] = lambda dt, tz: to_local(dt, tz) if dt else "n/d"


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
            return redirect(safe_next_path(request.args.get("next")) or url_for("dashboard_home"))
        error = "Mot de passe incorrect."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _load_state():
    try:
        return get_dashboard_state(), None
    except MongoUnavailable as e:
        return None, ("mongo_unavailable", str(e))
    except DashboardStateMissing as e:
        return None, ("state_missing", str(e))


def _load_prices(coins):
    prices = {}
    kraken_error = None
    if coins:
        try:
            prices = get_prices(coins)
        except KrakenUnavailable as e:
            kraken_error = str(e)
    return prices, kraken_error


def _load_cycles():
    try:
        cycles = get_recent_cycles(settings.CYCLES_JOURNAL_LIMIT)
        return cycles, None
    except MongoUnavailable as e:
        return [], str(e)


def _load_grid_cycles():
    # 6 créneaux par jour, plus une marge pour les cycles lancés à la main
    limit = settings.CYCLE_GRID_DAYS * len(viewdata.SLOT_HOURS_UTC) + 40
    try:
        return get_cycles_for_grid(limit)
    except MongoUnavailable:
        return []


def _load_weekly_analysis():
    try:
        return get_latest_weekly_analysis()
    except MongoUnavailable:
        return None


def _build_results_view(state, prices, cycles, tz_name):
    open_positions = state.get("open_positions") or []
    financials = state.get("financials") or {}
    by_period = financials.get("by_period") or {}
    maker = viewdata.build_maker_summary(state.get("watchers") or {})
    cadence = viewdata.build_cadence_band(cycles)
    weekly_note = analysis.weekly_note(by_period, cadence, maker)

    return {
        "financials": financials,
        "periods": viewdata.build_periods_table(by_period),
        "equity_points": viewdata.equity_curve_points(financials.get("equity_curve") or []),
        "equity": viewdata.equity_curve_geometry(financials.get("equity_curve") or []),
        "positions": viewdata.build_positions(open_positions, prices[0]),
        "maker": maker,
        "kraken_error": prices[1],
        "weekly_note": weekly_note,
        "weekly_analysis": viewdata.build_weekly_analysis_view(_load_weekly_analysis(), weekly_note, tz_name),
        "pnl_day": viewdata.pnl_bars(viewdata.pnl_by_period(financials.get("equity_curve") or [], "day")),
        "pnl_month": viewdata.pnl_bars(viewdata.pnl_by_period(financials.get("equity_curve") or [], "month")),
    }


def _build_cycles_view(cycles, cycles_error, tz_name):
    cadence = viewdata.build_cadence_band(cycles)

    return {
        "grid": viewdata.build_cycle_grid(
            _load_grid_cycles(), settings.CYCLE_GRID_DAYS, tz_name),
        "journal": [viewdata.build_cycle_row(c, tz_name) for c in cycles],
        "cadence": cadence,
        "cadence_summary": viewdata.cadence_summary(cadence),
        "blocking": analysis.blocking_reasons(cycles),
        "reliability": analysis.reliability_by_period(cycles),
        "error": cycles_error,
    }


@app.route("/")
@login_required
def dashboard_home():
    state, state_error = _load_state()
    if state_error:
        kind, detail = state_error
        return render_template("degraded.html", kind=kind, detail=detail)

    tz_name = viewdata.resolve_timezone(state, settings.DEFAULT_DISPLAY_TIMEZONE)
    fresh = viewdata.freshness(state, settings.STALE_THRESHOLD_MINUTES)

    open_positions = state.get("open_positions") or []
    coins = [p["coin"] for p in open_positions if p.get("coin")]
    prices = _load_prices(coins)
    cycles, cycles_error = _load_cycles()

    results_view = _build_results_view(state, prices, cycles, tz_name)
    cycles_view = _build_cycles_view(cycles, cycles_error, tz_name)

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
