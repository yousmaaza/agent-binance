"""I/O Telegram via curl subprocess (jamais urllib — DNS IPv6 incompatible nohup)."""
import json
import subprocess

from loguru import logger

from core.env import BASE_URL, CHAT_ID, PROJECT_DIR


def tg_post(endpoint, body):
    payload = json.dumps(body)
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{BASE_URL}/{endpoint}",
             "-H", "Content-Type: application/json",
             "-d", payload, "--max-time", "15"],
            capture_output=True, text=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except Exception as e:
        logger.error(f"[Telegram] {endpoint} erreur: {e}")
        return {}


def send_telegram(text, parse_mode=None):
    body = {"chat_id": CHAT_ID, "text": text}
    if parse_mode:
        body["parse_mode"] = parse_mode
    tg_post("sendMessage", body)


def handle_callback(cq):
    cq_chat_id = str(
        cq.get("from", {}).get("id", "") or
        cq.get("message", {}).get("chat", {}).get("id", "")
    )
    if cq_chat_id != CHAT_ID:
        return
    action = cq.get("data", "")
    logger.info(f"[Bot] Callback: {action!r}")
    answer_text = "✅ Confirmé" if action == "CONFIRM" else "❌ Annulé."
    tg_post("answerCallbackQuery", {"callback_query_id": cq["id"], "text": answer_text})


def get_offset() -> int:
    try:
        with open(f"{PROJECT_DIR}/state/telegram_offset.json") as f:
            return json.load(f).get("offset", 0)
    except Exception:
        return 0


def save_offset(offset: int) -> None:
    with open(f"{PROJECT_DIR}/state/telegram_offset.json", "w") as f:
        json.dump({"offset": offset}, f)
