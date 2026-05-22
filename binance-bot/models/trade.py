"""Schéma d'un trade dans trade_history.json."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradeRecord:
    trade_id: str
    date: str                    # ISO-8601 UTC
    coin: str
    side: str                    # "BUY"
    signal_score: float
    entry_price: float
    stop_price: float
    tp_price: float
    quantity: float
    risk_usdc: float
    entry_order_id: str = ""
    stop_order_id: str = ""
    tp_order_id: str = ""
    status: str = "open"         # "open" | "closed"
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None
    pnl_usdc: Optional[float] = None
    pnl_pct: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "TradeRecord":
        valid = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in valid})
