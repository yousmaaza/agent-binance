"""Parse les lignes stream-json émises par Claude CLI."""
import json
from datetime import datetime

from config.llm import RESOURCE_ERROR_PATTERNS


def _format_system_event(event: dict, ts: str) -> str | None:
    """Format system event (init)."""
    if event.get("subtype") == "init":
        sid = event.get("session_id", "")
        return f"[{ts}] 🚀 init | model={event.get('model', '?')} | session={sid[:8] if sid else '?'}"
    return None


def _format_assistant_event(event: dict, ts: str) -> str | None:
    """Format assistant event (text and tool_use)."""
    out = []
    for block in event.get("message", {}).get("content", []):
        btype = block.get("type")
        if btype == "text":
            text = (block.get("text") or "").strip().replace("\n", " ")
            if text:
                out.append(f"[{ts}] 💬 {text[:500]}")
        elif btype == "tool_use":
            name = block.get("name", "?")
            inp = json.dumps(block.get("input") or {}, ensure_ascii=False)
            out.append(f"[{ts}] 🔧 {name} {inp[:300]}")
    return "\n".join(out) if out else None


def _format_user_event(event: dict, ts: str) -> str | None:
    """Format user event (tool_result)."""
    out = []
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_result":
            content = block.get("content")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            txt = str(content or "").replace("\n", " ")
            out.append(f"[{ts}] ✅ tool_result → {txt[:300]}")
    return "\n".join(out) if out else None


def _format_result_event(event: dict, ts: str) -> str | None:
    """Format result event (done)."""
    dur = event.get("duration_ms", 0) / 1000.0
    cost = event.get("total_cost_usd")
    final = (event.get("result") or "").replace("\n", " ")[:500]
    cost_str = f" | cost=${cost:.4f}" if isinstance(cost, (int, float)) else ""
    return f"[{ts}] 🏁 done | {dur:.1f}s{cost_str}\n{final}"


_EVENT_HANDLERS = {
    "system": _format_system_event,
    "assistant": _format_assistant_event,
    "user": _format_user_event,
    "result": _format_result_event,
}


def parse_stream_event(line: str) -> str | None:
    """Transforme une ligne stream-json de Claude en log humain lisible (ou None à ignorer)."""
    try:
        e = json.loads(line)
    except Exception:
        return None
    ts = datetime.now().strftime("%H:%M:%S")
    etype = e.get("type")

    handler = _EVENT_HANDLERS.get(etype)
    return handler(e, ts) if handler else None


def is_resource_error(stdout_path: str) -> bool:
    """Retourne True si stdout contient un pattern d'erreur de quota Anthropic."""
    try:
        with open(stdout_path) as f:
            content = f.read()
        return any(p in content for p in RESOURCE_ERROR_PATTERNS)
    except (OSError, ValueError):
        return False
