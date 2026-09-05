"""Tests pour core/maker_exit_watcher.py — arbre de décision du watcher de sortie maker (#390).

is_locked/acquire_lock/release_lock, load_trade_history/save_trade_history, send_telegram et
_write_watcher_state sont mockés (jamais le vrai state/*.json ni un vrai curl). binance() (alias
_cli) est mocké via un dispatcheur configurable par test, sur le même principe que
tests/test_maker_watcher.py (in-process, _maker_exit_watcher_tick() n'est pas un script
top-level).

Garde-fous mis à l'épreuve délibérément (cf. issue #390) : chaque scénario d'échec (annulation
de la limite, vente au marché) est vérifié en cassant explicitement l'opération concernée et en
confirmant que le stop est reposé plutôt que de laisser la position nue.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from core import maker_exit_watcher  # noqa: E402

BASE_CONFIG = {
    "maker_exit_max_concession_pct": 0.003,
    "maker_exit_timeout_seconds": 600,
}


def _position(**overrides):
    base = {
        "trade_id": "T1",
        "coin": "ETH",
        "status": "open",
        "entry_price": 1000.0,
        "quantity": 1.0,
        "entry_fee_usdc": 0.5,
        "stop_price": 950.0,
        "sl_order_txid": "SLTX0",
        "tp_price": 1100.0,
    }
    base.update(overrides)
    return base


def _pending(**overrides):
    base = {
        "trade_id": "T1",
        "coin": "ETH",
        "pair": "ETHUSDC",
        "txid": "SELLTX1",
        "quantity": 1.0,
        "stop_price": 950.0,
        "close_reason": "tp_watcher",
        "initial_limit_price": 1100.0,
        "current_limit_price": 1100.0,
        "adjustments": 0,
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


class _FakeCli:
    """Dispatcheur configurable pour core.maker_exit_watcher._cli, clés alignées sur
    tests/fixtures/fake_kraken.py."""

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
                txid = args[2]
                key = f"order_cancel_{txid}"
                if key in self.responses and self.responses[key] is None:
                    raise OSError("cancel failed")
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


def _run_tick(pending_orders, fake_cli, history, config=None):
    """Exécute _maker_exit_watcher_tick() avec tous les I/O mockés. Retourne
    (history, saved_pending, mock_save_history, mock_send_telegram)."""
    with patch("core.maker_exit_watcher.is_locked", return_value=False), \
         patch("core.maker_exit_watcher.acquire_lock"), \
         patch("core.maker_exit_watcher.release_lock"), \
         patch("core.maker_exit_watcher.send_telegram") as mock_tg, \
         patch("core.maker_exit_watcher._write_watcher_state"), \
         patch("core.maker_exit_watcher.load_trade_history", return_value=history), \
         patch("core.maker_exit_watcher.save_trade_history") as mock_save_history, \
         patch("core.maker_exit_watcher.load_maker_exit_pending_orders", return_value=pending_orders), \
         patch("core.maker_exit_watcher.save_maker_exit_pending_orders") as mock_save_pending, \
         patch("core.maker_exit_watcher._cli", side_effect=fake_cli):
        maker_exit_watcher._maker_exit_watcher_tick(config or BASE_CONFIG)

    saved_pending = mock_save_pending.call_args[0][0] if mock_save_pending.call_args else None
    return history, saved_pending, mock_save_history, mock_tg


class TestAttemptMakerExitPostsPostOnlySellOrder(unittest.TestCase):
    """L'ordre posé par attempt_maker_exit() est bien un SELL LIMIT post-only."""

    def test_places_post_only_sell_limit_at_current_ask(self):
        pos = _position()
        fake_cli = _FakeCli(**{
            "ticker_ETHUSDC": {"a": ["1105.0", "0.01"], "c": ["1100.0", "0.01"]},
            "order_sell_ETHUSDC_limit": {"txid": ["SELLTX1"]},
        })

        with patch("core.maker_exit_watcher._cli", side_effect=fake_cli):
            record = maker_exit_watcher.attempt_maker_exit(pos, "tp_watcher", BASE_CONFIG, notify=lambda *_a, **_k: None)

        self.assertIsNotNone(record)
        self.assertEqual(record["txid"], "SELLTX1")
        self.assertAlmostEqual(record["initial_limit_price"], 1105.0)
        sell_calls = fake_cli.calls_with("order", "sell")
        self.assertEqual(len(sell_calls), 1)
        call = sell_calls[0]
        self.assertIn("limit", call)
        self.assertIn("post", call)
        self.assertTrue(fake_cli.calls_with("order", "cancel"))  # SL annulé avant la pose


class TestFullFillClosesPositionAsMaker(unittest.TestCase):
    def test_fill_closes_position_maker_label_no_stop_reposed(self):
        pending = _pending()
        pos = _position()
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "closed", "cost": "1100.0", "vol_exec": "1.0", "fee": "0.4"},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_called_once()
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["close_reason"], "tp_watcher")
        self.assertEqual(pos["exit_maker_or_taker"], "maker")
        self.assertAlmostEqual(pos["exit_price"], 1100.0)
        self.assertEqual(saved_pending, [])
        self.assertFalse(fake_cli.calls_with("order", "sell"))  # aucune vente marché
        self.assertFalse(fake_cli.calls_with("order", "cancel"))  # pas de stop reposé


class TestTimeoutTriggersMarketFallback(unittest.TestCase):
    def test_timeout_elapsed_cancels_limit_and_sells_at_market(self):
        placed_at = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        pending = _pending(placed_at=placed_at)
        pos = _position()
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"a": ["1100.5", "0.01"], "c": ["1100.0", "0.01"]},
            "order_sell_ETHUSDC_market": {"txid": ["MARKETTX1"]},
            "query-orders_MARKETTX1": {"status": "closed", "cost": "1099.0", "vol_exec": "1.0", "fee": "0.4"},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_called_once()
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["exit_maker_or_taker"], "taker")
        self.assertAlmostEqual(pos["exit_price"], 1099.0)
        self.assertEqual(saved_pending, [])
        self.assertTrue(fake_cli.calls_with("order", "cancel"))
        self.assertTrue(fake_cli.calls_with("order", "sell"))


class TestPriceRedescendedTriggersImmediateMarketFallback(unittest.TestCase):
    """Garde-fou central (#390) : le cours redescend au niveau où était le stop -> bascule
    immédiate au marché, sans attendre le délai ni le budget de concession."""

    def test_price_at_stop_level_falls_back_to_market_before_timeout(self):
        placed_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()  # tout juste posé
        pending = _pending(placed_at=placed_at, stop_price=950.0)
        pos = _position(stop_price=950.0)
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            # last price au niveau du stop (950) alors que le délai (600s) et le budget de
            # concession (0.3%) sont loin d'être atteints
            "ticker_ETHUSDC": {"a": ["1099.0", "0.01"], "c": ["949.0", "0.01"]},
            "order_sell_ETHUSDC_market": {"txid": ["MARKETTX1"]},
            "query-orders_MARKETTX1": {"status": "closed", "cost": "949.0", "vol_exec": "1.0", "fee": "0.3"},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_called_once()
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["exit_maker_or_taker"], "taker")
        self.assertTrue(fake_cli.calls_with("order", "cancel"))
        self.assertTrue(fake_cli.calls_with("order", "sell"))

    def test_price_still_above_stop_does_not_trigger_early(self):
        """Casse le garde-fou dans l'autre sens : au-dessus du stop, ni le délai ni le budget ne
        sont atteints -> l'ordre reste en chasse (amend), pas de repli marché."""
        placed_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        pending = _pending(placed_at=placed_at, stop_price=950.0)
        pos = _position(stop_price=950.0)
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"a": ["1100.2", "0.01"], "c": ["1100.0", "0.01"]},  # bien au-dessus du stop
            "order_amend_SELLTX1": {},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_not_called()
        self.assertEqual(len(saved_pending), 1)
        self.assertFalse(fake_cli.calls_with("order", "cancel"))
        self.assertFalse(fake_cli.calls_with("order", "sell"))


class TestLimitCancelFailureReposesStop(unittest.TestCase):
    """Casse délibérément l'annulation de la limite en fin de chasse -> le stop doit être reposé,
    jamais de position non protégée et non vendue."""

    def test_cancel_failure_reposes_stop_and_never_sells_at_market(self):
        placed_at = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        pending = _pending(placed_at=placed_at)
        pos = _position()
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"a": ["1100.5", "0.01"], "c": ["1100.0", "0.01"]},
            "order_cancel_SELLTX1": None,  # déclenche l'exception dans _FakeCli
            "pairs_ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["SLTXNEW"]},
        })

        history, saved_pending, mock_save_history, mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_called_once()
        self.assertEqual(pos["status"], "open")  # jamais vendue
        self.assertEqual(pos["sl_order_txid"], "SLTXNEW")  # stop reposé
        self.assertFalse(pos.get("protection_failed"))
        self.assertEqual(saved_pending, [])  # sortie du suivi, la chasse est abandonnée
        market_sells = [c for c in fake_cli.calls_with("order", "sell") if "market" in c]
        self.assertFalse(market_sells)  # jamais de vente marché tentée
        alert_calls = [c.args[0] for c in mock_tg.call_args_list if c.args]
        self.assertTrue(any("reposé" in msg for msg in alert_calls))


class TestMarketSellFailureReposesStop(unittest.TestCase):
    """Casse délibérément la vente au marché de repli -> le stop doit être reposé."""

    def test_market_sell_failure_reposes_stop(self):
        placed_at = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        pending = _pending(placed_at=placed_at)
        pos = _position()
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"a": ["1100.5", "0.01"], "c": ["1100.0", "0.01"]},
            # pas de clé order_sell_ETHUSDC_market -> fake_kraken renvoie {} -> pas de txid marché
            "pairs_ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["SLTXNEW"]},
        })

        history, saved_pending, mock_save_history, mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_called_once()
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["sl_order_txid"], "SLTXNEW")
        self.assertFalse(pos.get("protection_failed"))
        self.assertEqual(saved_pending, [])
        alert_calls = [c.args[0] for c in mock_tg.call_args_list if c.args]
        self.assertTrue(any("reposé" in msg for msg in alert_calls))

    def test_market_sell_and_repose_both_fail_marks_protection_failed(self):
        """Si le repose du stop échoue aussi, la position doit être marquée protection_failed
        (rattrapée ensuite par phase0_oco_retry.py) plutôt que silencieusement ignorée."""
        placed_at = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        pending = _pending(placed_at=placed_at)
        pos = _position()
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"a": ["1100.5", "0.01"], "c": ["1100.0", "0.01"]},
            "pairs_ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"},
            # pas de clé order_sell_ETHUSDC_stop-loss -> repose échoue aussi
        })

        history, saved_pending, mock_save_history, mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_called_once()
        self.assertEqual(pos["status"], "open")
        self.assertTrue(pos.get("protection_failed"))
        alert_calls = [c.args[0] for c in mock_tg.call_args_list if c.args]
        self.assertTrue(any("NON protégée" in msg for msg in alert_calls))


class TestConcessionBudgetExhaustedTriggersMarketFallback(unittest.TestCase):
    def test_concession_budget_exceeded_cancels_and_falls_back_to_market(self):
        pending = _pending()
        pos = _position()
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            # ask = 1096.0 -> concession = (1100-1096)/1100 = 0.36% > budget 0.3%
            "ticker_ETHUSDC": {"a": ["1096.0", "0.01"], "c": ["1097.0", "0.01"]},
            "order_sell_ETHUSDC_market": {"txid": ["MARKETTX1"]},
            "query-orders_MARKETTX1": {"status": "closed", "cost": "1096.0", "vol_exec": "1.0", "fee": "0.4"},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_called_once()
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["exit_maker_or_taker"], "taker")
        self.assertEqual(saved_pending, [])


class TestAskMovedTriggersAmend(unittest.TestCase):
    def test_ask_moved_within_budget_amends_and_updates_current_limit_price(self):
        pending = _pending()
        pos = _position()
        fake_cli = _FakeCli(**{
            "query-orders_SELLTX1": {"status": "open", "vol_exec": "0"},
            "ticker_ETHUSDC": {"a": ["1099.5", "0.01"], "c": ["1099.0", "0.01"]},
            "order_amend_SELLTX1": {},
        })

        history, saved_pending, mock_save_history, _mock_tg = _run_tick([pending], fake_cli, [pos])

        mock_save_history.assert_not_called()
        self.assertEqual(len(saved_pending), 1)
        self.assertAlmostEqual(saved_pending[0]["current_limit_price"], 1099.5)
        self.assertTrue(fake_cli.calls_with("order", "amend"))


class TestSignalSellNeverUsesMakerExitPath(unittest.TestCase):
    """Une vente sur signal retombé n'emprunte jamais ce chemin (#390 — hors périmètre) :
    attempt_maker_exit() n'est appelée que par tp_watcher.py et phase0_profit.py, jamais par le
    code de vente sur signal (commands/ ou prompts), qui continue de vendre au marché direct."""

    def test_maker_exit_watcher_module_has_no_signal_sell_caller(self):
        import subprocess as _sp
        grep = _sp.run(
            ["grep", "-rl", "--include=*.py", "attempt_maker_exit", os.path.join(PROJECT_DIR, "binance-bot")],
            capture_output=True, text=True,
        )
        callers = {os.path.basename(p) for p in grep.stdout.strip().splitlines()}
        self.assertEqual(callers, {"maker_exit_watcher.py", "tp_watcher.py", "phase0_profit.py"})


if __name__ == "__main__":
    unittest.main()
