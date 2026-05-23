"""Orchestration du cycle de trading : sous-processus Claude, streaming, fallback API."""
import os
import re
import subprocess
import threading
from datetime import datetime, timezone

from loguru import logger

from config.llm import CLAUDE_CLI_FLAGS, CLAUDE_MODEL_FALLBACK
from core.env import LOGS_DIR, PROJECT_DIR, PROMPT_VERSION, TRADE_PROMPT
from core.lock import acquire_lock, is_locked, release_lock
from core.telegram import send_telegram
from core.timing import fmt_local
from orchestration.stream_parser import is_resource_error, parse_stream_event
from orchestration.watchdog import WatchdogThread
from botlogging.cycle_logger import CycleLogger
from storage.mongo import mongo_repo


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

    prompt = (
        TRADE_PROMPT
        .replace("__CYCLE_ID__", cycle_id)
        .replace("__PROMPT_VERSION__", PROMPT_VERSION)
        .replace('"trigger": "manual"', f'"trigger": "{trigger}"')
    )

    stdout_path = f"{LOGS_DIR}/stdout/cycle_{cycle_id}.log"
    stderr_path = f"{LOGS_DIR}/stderr/cycle_{cycle_id}.log"
    exit_code = -1

    watchdog = WatchdogThread(cycle_log)
    watchdog.start()

    try:
        fallback_used = False
        exit_code = _run_claude(prompt, stdout_path, stderr_path, cycle_log)

        # Fallback API Sonnet si quota abonnement épuisé
        if exit_code != 0 and is_resource_error(stdout_path):
            if os.environ.get("ANTHROPIC_API_KEY"):
                fallback_used = True
                cycle_log.info("Ressource insuffisante — retry API Sonnet")
                send_telegram(f"⚠️ Abonnement insuffisant — retry via API ({CLAUDE_MODEL_FALLBACK}) (cycle {cycle_id})...")
                exit_code = _run_claude(
                    prompt, stdout_path, stderr_path, cycle_log,
                    extra_flags=["--model", CLAUDE_MODEL_FALLBACK],
                    keep_api_key=True,
                )
                cycle_log.info(f"Mode fallback API Sonnet — exit={exit_code}")
            else:
                logger.warning(f"[Cycle {cycle_id}] Ressource insuffisante — ANTHROPIC_API_KEY absent")

        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        cycle_log.info(f"Terminé exit={exit_code} en {duration:.0f}s")

        _update_cost_in_mongo(cycle_id, stdout_path, cycle_log)
        _update_billing_mode_in_mongo(cycle_id, "api" if fallback_used else "abonnement", cycle_log)

        if exit_code != 0:
            _handle_error(cycle_id, trigger, started_at, duration, stderr_path, stdout_path, cycle_log)

    except Exception as e:
        send_telegram(f"❌ Cycle {cycle_id} — erreur inattendue : {e}")
        cycle_log.error(f"Exception inattendue : {e}")
    finally:
        watchdog.stop()
        release_lock()


def _run_claude(
    prompt: str,
    stdout_path: str,
    stderr_path: str,
    cycle_log: CycleLogger,
    extra_flags: list | None = None,
    keep_api_key: bool = False,
) -> int:
    """Lance le sous-processus claude et streame stdout vers stdout_path. Retourne l'exit code."""
    flags = CLAUDE_CLI_FLAGS + (extra_flags or [])
    env = os.environ.copy()
    if not keep_api_key:
        env.pop("ANTHROPIC_API_KEY", None)

    with open(stdout_path, "w", buffering=1) as out_f, open(stderr_path, "w", buffering=1) as err_f:
        process = subprocess.Popen(
            ["claude"] + flags + [prompt],
            stdout=subprocess.PIPE, stderr=err_f,
            text=True, cwd=PROJECT_DIR, bufsize=1, env=env,
        )
        timer = threading.Timer(3600, process.kill)
        timer.start()
        try:
            for raw_line in process.stdout:
                formatted = parse_stream_event(raw_line.rstrip("\n"))
                if formatted:
                    out_f.write(formatted + "\n")
            return process.wait()
        finally:
            timer.cancel()


def _update_cost_in_mongo(cycle_id: str, stdout_path: str, cycle_log: CycleLogger) -> None:
    cost_usd = None
    try:
        with open(stdout_path) as f:
            for line in f:
                m = re.search(r"cost=\$([0-9]+\.[0-9]+)", line)
                if m:
                    cost_usd = float(m.group(1))
    except Exception:
        pass

    if cost_usd is not None:
        db = mongo_repo._db()
        if db is not None:
            try:
                db.cycles.update_one({"_id": cycle_id}, {"$set": {"api_cost_usd": cost_usd}})
            except Exception as e:
                cycle_log.error(f"Mongo cost update échec : {e}")


def _update_billing_mode_in_mongo(cycle_id: str, billing_mode: str, cycle_log: CycleLogger) -> None:
    db = mongo_repo._db()
    if db is not None:
        try:
            db.cycles.update_one({"_id": cycle_id}, {"$set": {"billing_mode": billing_mode}})
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
    try:
        with open(stderr_path) as f:
            err_extract = f.read()[:400] or "(vide)"
    except Exception:
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
