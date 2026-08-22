"""Tests pour core/maker_watcher.py — arbre de décision du watcher d'entrée maker (#388).

is_locked/acquire_lock/release_lock, load_trade_history/save_trade_history,
load_maker_pending_orders/save_maker_pending_orders, send_telegram et _write_watcher_state sont
mockés (jamais le vrai state/*.json ni un vrai curl). binance() (alias _cli) est mocké via un
dispatcheur configurable par test, sur le même principe que tests/test_tp_watcher.py et
tests/fixtures/fake_kraken.py (clés order_<sub>_<pair>_<type>, order_amend_<txid>) mais in-process
(_maker_watcher_tick() n'est pas un script top-level, le harness exec_phase_script ne s'applique
pas ici).
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core import maker_watcher  # noqa: E402

BASE_CONFIG = {
    "price_deviation_max_pct": 0.02,
    "maker_max_concession_pct": 0.003,
    "maker_timeout_seconds": 3600,
}


def _pending(**overrides):
    base = {
        "coin": "ETH",
        "pair": "ETHUSDC",
        "txid": "TX1",
        "quantity": 0.1,
        "montant_ordre": 200.0,
        "risk_usdc": 20.0,
        "stop_distance_pct": 0.05,
        "reward_risk_ratio": 2,
        "score": 8,
        "scan_price": 2000.0,
        "initial_limit_price": 1999.5,
        "current_limit_price": 1999.5,
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": "c1",
    }
    base.update(overrides)
    return base


class _FakeCli:
    """Dispatcheur configurable pour core.maker_watcher._cli, clés alignées sur fake_kraken.py."""

    def __init__(self, **responses):
        self.responses = responses
        self.calls = []

    def __call__(self, *args, **_kwargs):
        self.calls.append(args)
        if args[0] == "query-orders":
            txid = args[1]
            return json.dumps({txid: self.responses.get(f"query-orders_{txid}", {})})
        if args[0] == "ticker":
            pair = args[1]
            return json.dumps({pair: self.responses.get(f"ticker_{pair}", {})})
        if args[0] == "pairs":
            pair = args[args.index("--pair") + 1]
            return json.dumps({pair: self.responses.get(f"pairs_{pair}", {})})
        if args[0] == "order":
            sub = args[1]
            if sub == "amend":
                txid = args[args.index("--txid") + 1]
                return json.dumps(self.responses.get(f"order_amend_{txid}", {}))
            if sub == "cancel":
                return json.dumps({})
            pair = args[2]
            order_type = args[args.index("--type") + 1] if "--type" in args else ""
            typed_key = f"order_{sub}_{pair}_{order_type}"
            plain_key = f"order_{sub}_{pair}"
            resp = self.responses[typed_key] if typed_key in self.responses else self.responses.get(plain_key, {})
            return json.dumps(resp)
        return "{}"

    def calls_with(self, cmd, sub=None):
        return [c for c in self.calls if c[0] == cmd and (sub is None or (len(c) > 1 and c[1] == sub))]


def _run_tick(pending_orders, fake_cli, config=None, history=None):
    """Exécute _maker_watcher_tick() avec tous les I/O mockés. Retourne
    (history, saved_pending, mock_save_trade_history, mock_send_telegram)."""
    history = history if history is not None else []
    with patch("core.maker_watcher.is_locked", return_value=False), \
         patch("core.maker_watcher.acquire_lock"), \
         patch("core.maker_watcher.release_lock"), \
         patch("core.maker_watcher.send_telegram") as mock_tg, \
         patch("core.maker_watcher._write_watcher_state"), \
         patch("core.maker_watcher.load_trade_history", return_value=history), \
         patch("core.maker_watcher.save_trade_history") as mock_save_history, \
         patch("core.maker_watcher.load_maker_pending_orders", return_value=pending_orders), \
         patch("core.maker_watcher.save_maker_pending_orders") as mock_save_pending, \
         patch("core.maker_watcher._cli", side_effect=fake_cli):
        maker_watcher._maker_watcher_tick(config or BASE_CONFIG)

    saved_pending = mock_save_pending.call_args[0][0] if mock_save_pending.call_args else None
    return history, saved_pending, mock_save_history, mock_tg


class TestOrderFilledRegistersPositionAndPlacesStopLoss(unittest.TestCase):
    def test_full_fill_registers_open_position_with_maker_label_and_sl(self):
        pending = _pending()
        fake_cli = _FakeCli(**{
            "query-orders_TX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1", "fee": "0.3"},
            "pairs_ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["SLTX1"]},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli)

        mock_save_history.assert_called_once()
        self.assertEqual(len(history), 1)
        pos = history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["entry_order_id"], "TX1")
        self.assertEqual(pos["sl_order_txid"], "SLTX1")
        self.assertEqual(pos["maker_or_taker"], "maker")
        self.assertAlmostEqual(pos["entry_price"], 2000.0)
        self.assertAlmostEqual(pos["quantity"], 0.1)
        self.assertAlmostEqual(pos["entry_fee_usdc"], 0.3)
        self.assertEqual(saved_pending, [])


class TestBudgetExhaustedTriggersMarketFallback(unittest.TestCase):
    def test_concession_budget_exceeded_cancels_and_falls_back_to_market(self):
        pending = _pending()
        fake_cli = _FakeCli(**{
            "query-orders_TX1": {"status": "open", "vol_exec": "0"},
            # bid = 2007.0 -> concession = (2007-1999.5)/1999.5 = 0.375% > 0.30%
            "ticker_ETHUSDC": {"b": ["2007.0", "0.01"], "c": ["2005.0", "0.01"]},
            "order_buy_ETHUSDC_market": {"txid": ["MARKETTX1"]},
            "query-orders_MARKETTX1": {"status": "closed", "cost": "201.0", "vol_exec": "0.1", "fee": "0.4"},
            "pairs_ETHUSDC": {"lot_decimals": 8},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["SLTX2"]},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli)

        mock_save_history.assert_called_once()
        pos = history[0]
        self.assertEqual(pos["entry_order_id"], "MARKETTX1")
        self.assertEqual(pos["maker_or_taker"], "taker")
        self.assertAlmostEqual(pos["entry_price"], 2010.0)
        self.assertEqual(saved_pending, [])
        self.assertTrue(fake_cli.calls_with("order", "cancel"))


class TestTimeoutTriggersMarketFallback(unittest.TestCase):
    def test_timeout_elapsed_cancels_and_falls_back_to_market_even_within_budget(self):
        placed_at = (datetime.now(timezone.utc) - timedelta(seconds=4000)).isoformat()
        pending = _pending(placed_at=placed_at)
        fake_cli = _FakeCli(**{
            "query-orders_TX1": {"status": "open", "vol_exec": "0"},
            # bid quasi inchangé -> budget de concession non atteint, seul le timeout déclenche
            "ticker_ETHUSDC": {"b": ["1999.6", "0.01"], "c": ["1999.6", "0.01"]},
            "order_buy_ETHUSDC_market": {"txid": ["MARKETTX1"]},
            "query-orders_MARKETTX1": {"status": "closed", "cost": "200.0", "vol_exec": "0.1", "fee": "0.3"},
            "pairs_ETHUSDC": {"lot_decimals": 8},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["SLTX2"]},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick(
            [pending], fake_cli, config={**BASE_CONFIG, "maker_timeout_seconds": 3600},
        )

        mock_save_history.assert_called_once()
        self.assertEqual(history[0]["entry_order_id"], "MARKETTX1")
        self.assertEqual(history[0]["maker_or_taker"], "taker")
        self.assertEqual(saved_pending, [])


class TestPriceInvalidatedAbandonsWithoutMarketBuy(unittest.TestCase):
    def test_price_deviation_exceeded_cancels_without_market_fallback(self):
        pending = _pending()
        fake_cli = _FakeCli(**{
            "query-orders_TX1": {"status": "open", "vol_exec": "0"},
            # last price 2100 vs scan_price 2000 -> drift 5% > price_deviation_max_pct 2%
            "ticker_ETHUSDC": {"b": ["2000.0", "0.01"], "c": ["2100.0", "0.01"]},
        })

        history, saved_pending, mock_save_history, mock_tg = _run_tick([pending], fake_cli)

        mock_save_history.assert_not_called()
        self.assertEqual(history, [])
        self.assertEqual(saved_pending, [])
        self.assertFalse(fake_cli.calls_with("order", "buy"))
        alert_calls = [c.args[0] for c in mock_tg.call_args_list if c.args]
        self.assertTrue(any("invalidé" in msg for msg in alert_calls))


class TestBidMovedTriggersAmend(unittest.TestCase):
    def test_bid_moved_within_budget_amends_and_updates_current_limit_price(self):
        pending = _pending()
        fake_cli = _FakeCli(**{
            "query-orders_TX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"b": ["2000.5", "0.01"], "c": ["2000.0", "0.01"]},
            "order_amend_TX1": {},  # pas de clé "error" -> amend réussi
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli)

        mock_save_history.assert_not_called()
        self.assertEqual(len(saved_pending), 1)
        self.assertAlmostEqual(saved_pending[0]["current_limit_price"], 2000.5)
        self.assertTrue(fake_cli.calls_with("order", "amend"))


class TestAmendRejectedIsNonFatal(unittest.TestCase):
    def test_post_only_amend_rejection_keeps_order_pending_unchanged(self):
        pending = _pending()
        fake_cli = _FakeCli(**{
            "query-orders_TX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"b": ["2000.5", "0.01"], "c": ["2000.0", "0.01"]},
            "order_amend_TX1": {"error": ["EOrder:Post only order"]},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli)

        mock_save_history.assert_not_called()
        self.assertEqual(len(saved_pending), 1)
        # Le prix n'est pas mis à jour puisque l'amend a été rejeté -> réessai au tick suivant.
        self.assertAlmostEqual(saved_pending[0]["current_limit_price"], 1999.5)


class TestPartialFillOnRepliRegistersPartialPositionWithoutMarketBuy(unittest.TestCase):
    def test_partial_fill_detected_after_cancel_is_registered_without_extra_market_buy(self):
        pending = _pending()
        fake_cli = _FakeCli(**{
            # Rempli à 40% (0.04/0.1) au moment où le budget de concession est atteint et où
            # l'annulation est déclenchée -> vol_exec constaté après le cancel.
            "query-orders_TX1": {"status": "open", "vol_exec": "0.04", "cost": "80.0", "fee": "0.12"},
            "ticker_ETHUSDC": {"b": ["2007.0", "0.01"], "c": ["2005.0", "0.01"]},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli)

        mock_save_history.assert_called_once()
        pos = history[0]
        self.assertEqual(pos["entry_order_id"], "TX1")
        self.assertEqual(pos["maker_or_taker"], "maker")
        self.assertAlmostEqual(pos["quantity"], 0.04)
        self.assertAlmostEqual(pos["entry_price"], 2000.0)
        self.assertEqual(saved_pending, [])
        self.assertFalse(fake_cli.calls_with("order", "buy"))  # pas de repli marché sur le reliquat


class TestExternallyCanceledOrderWithZeroFillIsAbandoned(unittest.TestCase):
    def test_order_canceled_outside_watcher_with_no_fill_is_dropped_without_market_buy(self):
        pending = _pending()
        fake_cli = _FakeCli(**{
            "query-orders_TX1": {"status": "canceled", "vol_exec": "0"},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli)

        mock_save_history.assert_not_called()
        self.assertEqual(history, [])
        self.assertEqual(saved_pending, [])
        self.assertFalse(fake_cli.calls_with("order", "buy"))
        self.assertFalse(fake_cli.calls_with("order", "cancel"))  # déjà terminé, pas de cancel à renvoyer


if __name__ == "__main__":
    unittest.main()
