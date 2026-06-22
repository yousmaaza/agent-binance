#!/usr/bin/env python3
"""Telegram polling bot — point d'entrée. Dispatch les commandes vers les handlers."""
import os
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.env  # noqa: F401  — bootstrap loguru + .env + prompt

from loguru import logger

from commands.cout import run_cout
from commands.eval import run_eval
from commands.perf import run_perf
from commands.raisonnement import run_raisonnement
from commands.status import run_status
from core.lock import release_lock
from core.state_manager import validate_and_repair_boot
from core.telegram import get_offset, handle_callback, save_offset, send_telegram, tg_post
from core.timing import fmt_local, next_4h_slot, next_1h_slot
from orchestration.runner import run_trade_workflow, run_position_check_workflow

NEXT_AUTO_TRADE = None
NEXT_AUTO_POSITION = None


def fmt_next() -> str:
    return fmt_local(NEXT_AUTO_TRADE) if NEXT_AUTO_TRADE else "–"


def main_loop():
    global NEXT_AUTO_TRADE, NEXT_AUTO_POSITION

    tg_post("deleteWebhook", {})
    NEXT_AUTO_TRADE = next_4h_slot()
    NEXT_AUTO_POSITION = next_1h_slot()
    offset = get_offset()

    from core.env import TRADE_PROMPT, POSITION_PROMPT  # noqa: F401 — vérifie que les prompts sont bien chargés

    is_valid, error = validate_and_repair_boot()
    if not is_valid:
        logger.warning(f"trade_history.json était corrompu — repaired : {error}")
        send_telegram(
            f"⚠️ trade_history.json détecté corrompu au boot : {error}\n"
            f"Backup créé, fichier réinitialisé. Cycles précédents non affectés."
        )

    logger.info(f"Bot v2 démarre en mode polling (offset={offset})")
    logger.info(f"Prochain cycle auto : {fmt_next()}")

    send_telegram(
        f"🤖 Bot v2 démarré (workflow test 2026-05-28)\n"
        f"Commandes : /trade /status /perf /raisonnement /cout /eval /reset\n"
        f"⏰ Prochain cycle auto : {fmt_next()}",
        parse_mode=None,
    )

    while True:
        try:
            if NEXT_AUTO_POSITION and datetime.now(timezone.utc) >= NEXT_AUTO_POSITION:
                NEXT_AUTO_POSITION = next_1h_slot()
                logger.info(f"[Scheduler] Auto-position → prochain slot {fmt_local(NEXT_AUTO_POSITION)}")
                threading.Thread(
                    target=run_position_check_workflow,
                    kwargs={"trigger": "auto", "fmt_next_fn": lambda: fmt_local(NEXT_AUTO_POSITION)},
                    daemon=True,
                ).start()

            if NEXT_AUTO_TRADE and datetime.now(timezone.utc) >= NEXT_AUTO_TRADE:
                NEXT_AUTO_TRADE = next_4h_slot()
                logger.info(f"[Scheduler] Auto-trade → prochain slot {fmt_next()}")
                threading.Thread(
                    target=run_trade_workflow,
                    kwargs={"trigger": "auto", "fmt_next_fn": fmt_next},
                    daemon=True,
                ).start()

            data = tg_post("getUpdates", {
                "offset": offset,
                "timeout": 10,
                "allowed_updates": ["message", "callback_query"],
            })
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                save_offset(offset)

                cq = update.get("callback_query")
                if cq:
                    handle_callback(cq)
                    continue

                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                from core.env import CHAT_ID
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if chat_id != CHAT_ID:
                    logger.warning(f"[Security] Ignoré chat_id={chat_id}")
                    continue

                logger.info(f"[Bot] Commande: {text!r}")

                if text.startswith("/trade"):
                    NEXT_AUTO_TRADE = next_4h_slot()
                    threading.Thread(
                        target=run_trade_workflow,
                        kwargs={"trigger": "manual", "fmt_next_fn": fmt_next},
                        daemon=True,
                    ).start()
                elif text.startswith("/status"):
                    threading.Thread(
                        target=lambda: send_telegram(run_status(fmt_next_fn=fmt_next), parse_mode="HTML"),
                        daemon=True,
                    ).start()
                elif text.startswith("/perf"):
                    threading.Thread(
                        target=lambda: send_telegram(run_perf(), parse_mode="HTML"),
                        daemon=True,
                    ).start()
                elif text.startswith("/raisonnement"):
                    threading.Thread(
                        target=lambda: send_telegram(run_raisonnement(), parse_mode="HTML"),
                        daemon=True,
                    ).start()
                elif text.startswith("/cout"):
                    threading.Thread(
                        target=lambda: send_telegram(run_cout()),
                        daemon=True,
                    ).start()
                elif text.startswith("/eval"):
                    threading.Thread(
                        target=lambda: send_telegram(run_eval(), parse_mode="HTML"),
                        daemon=True,
                    ).start()
                elif text.startswith("/reset"):
                    release_lock()
                    send_telegram(f"🔓 Lock réinitialisé.\n⏰ Prochain cycle auto : {fmt_next()}")
                elif text:
                    send_telegram(
                        f"Commandes : /trade /status /perf /raisonnement /cout /eval /reset\n"
                        f"⏰ Prochain cycle : {fmt_next()}"
                    )

        except Exception as e:
            logger.error(f"[Polling] Erreur: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main_loop()
