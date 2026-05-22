"""Schéma de la collection MongoDB `cycles`."""
from typing import Any, Dict, List, Optional
from typing import TypedDict


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
    decisions: List[Dict[str, Any]]   # [{coin, score, decision, reason, ...}]
    orders: List[Dict[str, Any]]      # [{coin, side, entry_price, qty, ...}]
    phases: List[PhaseHeartbeat]
    error: Optional[str]
    api_cost_usd: Optional[float]
    explanation_fr: Optional[str]     # explication vulgarisée pour /raisonnement
