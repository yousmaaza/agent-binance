"""Helpers pour le cycle de gestion des positions ouvertes.

Module symétrique : ré-exporte depuis core.trade_helpers pour éviter la duplication.
Importé via :
    from core.position_helpers import tg, binance, _load_config, _save_trade_history_atomic, _save_config_atomic
"""
from core.trade_helpers import (
    binance,
    tg,
    _load_config,
    _save_trade_history_atomic,
    _save_config_atomic,
)

def fold_partial_trades(closed: list) -> list:
    """Une position = un trade pour les compteurs (nombre, taux de gagnants, séries) (#514) : replie
    chaque enregistrement `partial_tp` dans son parent clôturé (copies, l'historique n'est jamais
    modifié). Un partiel dont le parent est encore ouvert reste un trade à part entière."""
    copies = [dict(t) for t in closed]
    parents = {t["trade_id"]: t for t in copies if t.get("trade_id") and not t.get("parent_trade_id")}
    result = []
    for t in copies:
        parent = parents.get(t.get("parent_trade_id"))
        if parent is None:
            result.append(t)
            continue
        for k in ("pnl_usdc", "pnl_gross_usdc", "fees_usdc", "entry_fee_usdc", "exit_fee_usdc", "quantity"):
            parent[k] = (parent.get(k) or 0) + (t.get(k) or 0)
        notional = float(parent.get("entry_price") or 0) * parent["quantity"]
        if notional:
            parent["pnl_pct"] = parent["pnl_usdc"] / notional * 100
            parent["pnl_gross_pct"] = parent["pnl_gross_usdc"] / notional * 100
    return result


__all__ = [
    "fold_partial_trades",
    "tg",
    "binance",
    "_load_config",
    "_save_trade_history_atomic",
    "_save_config_atomic",
]
