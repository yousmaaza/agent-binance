"""Orchestration du cycle de trading : sous-processus Claude, streaming."""
import os
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone

from config.llm import CLAUDE_CLI_FLAGS
from core.env import BINANCE_CLI_PATH, LOGS_DIR, PROJECT_DIR, PROMPT_VERSION, TRADE_PROMPT, get_cycle_phases_log_path
from core.lock import acquire_lock, is_locked, release_lock
from core.telegram import send_telegram
from core.timing import fmt_local
from orchestration.stream_parser import is_resource_error, parse_stream_event
from orchestration.watchdog import WatchdogThread
from botlogging.cycle_logger import CycleLogger
from storage.mongo import mongo_repo

CLAUDE_PROCESS_TIMEOUT_S = 3600  # 1h max par cycle — tuer le processus si dépassé


def run_trade_workflow(trigger: str = "manual", fmt_next_fn=None) -> None:
    """Lance un cycle complet d'analyse et d'exécution.

    fmt_next_fn : callable() -> str optionnel, fourni par main_loop pour afficher
    l'heure du prochain cycle. Si absent, on affiche '--'.
    """
    if is_locked():
        send_telegram("⏳ Un cycle est déjà en cours. Réessaie dans quelques minutes.")
        return

    acquire_lock()
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    started_at = datetime.now(timezone.utc)
    cycle_log = CycleLogger(cycle_id)
    cycle_log.info(f"Démarrage (trigger={trigger})")

    fmt_next = fmt_next_fn() if fmt_next_fn else "–"
    _send_start_notification(cycle_id, trigger, started_at, fmt_next)

    try:
        helpers_fd, helpers_path = tempfile.mkstemp(suffix=".py", prefix=f"cycle_{cycle_id}_")
    except OSError as e:
        send_telegram(f"❌ Cycle {cycle_id} — impossible de créer le fichier helpers (disque plein ?) : {e}")
        cycle_log.error(f"mkstemp helpers échoué : {e}")
        release_lock()
        return

    prompt = (
        TRADE_PROMPT
        .replace("__CYCLE_ID__", cycle_id)
        .replace("__HELPERS_PATH__", helpers_path)
        .replace("__PROMPT_VERSION__", PROMPT_VERSION)
        .replace("__TRIGGER__", trigger)
    )

    _write_helpers_file(helpers_fd, helpers_path, cycle_id, trigger)

    stdout_path = f"{LOGS_DIR}/stdout/cycle_{cycle_id}.log"
    stderr_path = f"{LOGS_DIR}/stderr/cycle_{cycle_id}.log"
    exit_code = -1

    watchdog = WatchdogThread(cycle_log)
    watchdog.start()

    try:
        exit_code = _run_claude(prompt, stdout_path, stderr_path, cycle_log)

        # Quota abonnement épuisé — pas de fallback API (abonnement uniquement)
        if exit_code != 0 and is_resource_error(stdout_path):
            send_telegram(
                "⛔ Quota abonnement Claude épuisé — cycle annulé.\n"
                "Réessaie dans quelques heures (reset automatique de l'abonnement)."
            )
            cycle_log.error(f"[Cycle {cycle_id}] Quota abonnement épuisé — pas de fallback API configuré")

        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        cycle_log.info(f"Terminé exit={exit_code} en {duration:.0f}s")

        _update_cost_in_mongo(cycle_id, stdout_path, cycle_log)
        _update_billing_mode_in_mongo(cycle_id, "abonnement", cycle_log)

        if exit_code != 0:
            _handle_error(cycle_id, trigger, started_at, duration, stderr_path, stdout_path, cycle_log)

    except Exception as e:
        send_telegram(f"❌ Cycle {cycle_id} — erreur inattendue : {e}")
        cycle_log.error(f"Exception inattendue : {e}")
    finally:
        watchdog.stop()
        release_lock()
        try:
            os.unlink(helpers_path)
        except OSError:
            pass


def _send_start_notification(cycle_id: str, trigger: str, started_at: datetime, fmt_next: str) -> None:
    _model_idx = CLAUDE_CLI_FLAGS.index("--model") + 1 if "--model" in CLAUDE_CLI_FLAGS else -1
    _model = CLAUDE_CLI_FLAGS[_model_idx] if _model_idx > 0 else "claude (défaut)"
    if trigger == "auto":
        send_telegram(
            f"🤖 Cycle auto 4h démarré ({fmt_local(started_at)})\n"
            f"🧠 Modèle : {_model} (abonnement)\n"
            f"⏰ Prochain cycle auto : {fmt_next}"
        )
    else:
        send_telegram(
            f"🔧 Cycle manuel {cycle_id} démarré\n"
            f"🧠 Modèle : {_model} (abonnement)\n"
            f"⏰ Prochain cycle auto : {fmt_next}"
        )


def _write_helpers_file(fd: int, helpers_path: str, cycle_id: str, trigger: str) -> None:
    """Écrit le fichier helpers via fd issu de tempfile.mkstemp.

    Permissions 0o600 garanties par mkstemp. Aucun secret baked — lus depuis os.environ au runtime.
    """
    hb_path = get_cycle_phases_log_path(cycle_id)
    helpers_content = f"""import subprocess, json, time as _t, datetime as _hb_dt, os as _hb_os, tempfile as _hb_tempfile, math

BINANCE_CLI = {repr(BINANCE_CLI_PATH)}
PYTHON_BIN  = {repr(sys.executable)}
PROJECT_DIR = {repr(PROJECT_DIR)}
CYCLE_ID    = {repr(cycle_id)}
MONGO_URI   = _hb_os.environ.get("MONGODB_URI", "")
MONGO_DB    = _hb_os.environ.get("MONGODB_DB", "agent-binance")
_HB_PATH    = {repr(hb_path)}
_trigger    = {repr(trigger)}

_hb_os.makedirs(_hb_os.path.dirname(_HB_PATH), exist_ok=True)
_hb_phase_start = {{}}

def tg(text):
    _tok = _hb_os.environ.get("TELEGRAM_TOKEN", "")
    _cid = _hb_os.environ.get("TELEGRAM_CHAT_ID", "")
    payload = json.dumps({{"chat_id": _cid, "text": text}})
    subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"https://api.telegram.org/bot{{_tok}}/sendMessage",
         "-H", "Content-Type: application/json",
         "-d", payload, "--max-time", "20"],
        capture_output=True)

def binance(*args, _retries=3):
    for _attempt in range(_retries):
        _r = subprocess.run([BINANCE_CLI] + list(args), capture_output=True, text=True, timeout=30)
        raw = _r.stdout.strip()
        if raw.startswith("Invalid symbol"):
            raise ValueError("Invalid symbol")
        if raw and not raw.startswith("Request failed") and not raw.startswith("Usage:"):
            return raw
        if _attempt < _retries - 1:
            _t.sleep(2 * (_attempt + 1))
    raise RuntimeError(f"binance-cli failed after {{_retries}} retries: {{raw[:120]}}")

def _hb_start(phase):
    _hb_phase_start[phase] = _hb_dt.datetime.utcnow().timestamp()

def hb(phase, status="ok", summary=""):
    t0 = _hb_phase_start.pop(phase, None)
    duration_s = round(_hb_dt.datetime.utcnow().timestamp() - t0, 1) if t0 is not None else None
    _entry = json.dumps({{
        "ts": _hb_dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": phase, "status": status,
        "duration_s": duration_s, "summary": summary, "trigger": _trigger
    }})
    _lines = []
    if _hb_os.path.exists(_HB_PATH):
        with open(_HB_PATH) as _rf:
            for _ln in _rf:
                _ln = _ln.strip()
                if _ln:
                    try:
                        if json.loads(_ln).get("phase") != phase:
                            _lines.append(_ln)
                    except Exception:
                        _lines.append(_ln)
    _lines.append(_entry)
    with open(_HB_PATH, "w") as _f:
        _f.write("\\n".join(_lines) + "\\n")
        _f.flush()

def _save_trade_history_atomic(data, path_override=None):
    _th_path = path_override or f"{{PROJECT_DIR}}/state/trade_history.json"
    _th_parent = _hb_os.path.dirname(_th_path)
    _hb_os.makedirs(_th_parent, exist_ok=True)
    _fd, _th_temp = _hb_tempfile.mkstemp(dir=_th_parent, text=True, suffix=".tmp")
    try:
        with _hb_os.fdopen(_fd, "w") as _f:
            json.dump(data, _f, indent=2)
        _hb_os.replace(_th_temp, _th_path)
    except Exception as _e:
        try:
            _hb_os.unlink(_th_temp)
        except OSError:
            pass
        raise _e
"""
    with os.fdopen(fd, "w") as f:
        f.write(helpers_content)


def _run_claude(
    prompt: str,
    stdout_path: str,
    stderr_path: str,
    cycle_log: CycleLogger,
) -> int:
    """Lance le sous-processus claude et streame stdout vers stdout_path. Retourne l'exit code."""
    flags = CLAUDE_CLI_FLAGS
    env = os.environ.copy()

    with open(stdout_path, "w", buffering=1) as out_f, open(stderr_path, "w", buffering=1) as err_f:
        # flags from CLAUDE_CLI_FLAGS (config), prompt from TRADE_PROMPT (env) — no user input
        process = subprocess.Popen(
            ["claude"] + flags + [prompt],
            stdout=subprocess.PIPE, stderr=err_f,
            text=True, cwd=PROJECT_DIR, bufsize=1, env=env,
        )
        timer = threading.Timer(CLAUDE_PROCESS_TIMEOUT_S, process.kill)
        timer.start()
        try:
            # Mypy type guard: stdout=PIPE garantit que stdout n'est pas None
            assert process.stdout is not None
            for raw_line in process.stdout:
                formatted = parse_stream_event(raw_line.rstrip("\n"))
                if formatted:
                    out_f.write(formatted + "\n")
            return process.wait()
        finally:
            timer.cancel()


def _update_cost_in_mongo(cycle_id: str, stdout_path: str, cycle_log: CycleLogger) -> None:
    # Cost extraction is optional; skip silently if file unreadable or regex fails.
    # This ensures a malformed log or missing file doesn't crash the cycle.
    cost_usd = None
    try:
        with open(stdout_path) as f:
            for line in f:
                m = re.search(r"cost=\$([0-9]+\.[0-9]+)", line)
                if m:
                    cost_usd = float(m.group(1))
    except (OSError, ValueError) as e:
        cycle_log.warning(f"Erreur lecture cost depuis {stdout_path}: {e}")

    if cost_usd is not None:
        db = mongo_repo._db()
        if db is not None:
            try:
                db.cycles.update_one({"_id": cycle_id}, {"$set": {"api_cost_usd": cost_usd}})
                cycle_log.info(f"Cost updated in MongoDB: {cost_usd} USD")
            except Exception as e:
                cycle_log.error(f"Mongo cost update échec : {e}")


def _update_billing_mode_in_mongo(cycle_id: str, billing_mode: str, cycle_log: CycleLogger) -> None:
    db = mongo_repo._db()
    if db is not None:
        try:
            db.cycles.update_one({"_id": cycle_id}, {"$set": {"billing_mode": billing_mode}})
            cycle_log.info(f"Billing mode updated in MongoDB: {billing_mode}")
        except Exception as e:
            cycle_log.error(f"Mongo billing_mode update échec : {e}")


def _handle_error(
    cycle_id: str,
    trigger: str,
    started_at: datetime,
    duration: float,
    stderr_path: str,
    stdout_path: str,
    cycle_log: CycleLogger,
) -> None:
    # If stderr file is unreadable, show placeholder instead of crashing.
    # Error is logged at warning level for observability; user still gets
    # a Telegram notification with a fallback message.
    try:
        with open(stderr_path) as f:
            err_extract = f.read()[:400] or "(vide)"
    except OSError as e:
        cycle_log.warning(f"Erreur lecture {stderr_path}: {e}")
        err_extract = "(illisible)"

    send_telegram(
        f"❌ <b>Cycle {cycle_id}</b> — erreur\n"
        f"<code>{err_extract}</code>\n\n"
        f"📋 Logs : logs/stderr/cycle_{cycle_id}.log",
        parse_mode="HTML",
    )

    db = mongo_repo._db()
    if db is not None:
        try:
            db.cycles.update_one(
                {"_id": cycle_id},
                {"$set": {
                    "cycle_id": cycle_id,
                    "timestamp": started_at.isoformat(),
                    "status": "error",
                    "trigger": trigger,
                    "prompt_version": PROMPT_VERSION,
                    "duration_seconds": duration,
                    "explanation_fr": "Le cycle a échoué avant de produire un résultat exploitable.",
                }},
                upsert=True,
            )
        except Exception as e:
            cycle_log.error(f"Mongo fallback erreur : {e}")
