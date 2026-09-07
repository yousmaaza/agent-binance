"""Schéma de la collection MongoDB `cycles`."""
from typing import Any, TypedDict


class PhaseHeartbeat(TypedDict):
    phase: int
    ts: str       # ISO-8601 UTC
    summary: str


class CycleDocument(TypedDict, total=False):
    cycle_id: str
    trigger: str                      # "manual" | "auto"
    started_at: str                   # ISO-8601 UTC
    status: str                       # "success" | "error" | "no_trade"
    prompt_version: str               # SHA1 8 chars
    decisions: list[dict[str, Any]]   # [{coin, score, decision, reason, ...}]
    orders: list[dict[str, Any]]      # [{coin, side, entry_price, qty, ...}]
    phases: list[PhaseHeartbeat]
    error: str | None
    api_cost_usd: float | None
    explanation_fr: str | None     # explication vulgarisée pour /raisonnement
