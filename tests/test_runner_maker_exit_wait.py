"""Tests pour orchestration/runner.py — attente bornée d'une chasse de sortie maker avant le
démarrage d'un cycle (#461).

Contexte : un cycle pose le verrou (state/agent_lock.json) pendant toute sa durée (médiane 418s,
p90 609s, max observé 15617s). Si une chasse de sortie maker est en cours quand un cycle
démarre, le watcher (_maker_exit_watcher_tick) ne peut plus s'exécuter tant que le cycle tourne
-> la position reste sans stop au-delà du délai de chasse prévu. La correction fait attendre le
cycle (avant acquire_lock()) tant que state/maker_exit_pending_orders.json n'est pas vide,
borné à maker_exit_timeout_seconds + marge pour ne jamais bloquer indéfiniment.

Un ordre peut aussi rester bloqué dans ce fichier indéfiniment (échec query-orders persistant
dans le watcher, thread watcher mort sur une exception non couverte) : sans garde d'ancienneté,
un tel résidu retarderait chaque cycle, pour toujours, silencieusement. _active_maker_exit_orders
exclut donc les ordres dont placed_at dépasse maker_exit_timeout_seconds + marge (plus une
chasse active à ce stade) et déclenche une alerte Telegram.

_load_config, load_maker_exit_pending_orders et time.sleep/time.monotonic sont mockés (jamais le
vrai config.json ni le vrai state/*.json, jamais de vraie attente)."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from orchestration import runner  # noqa: E402 -- import après sys.path.insert, ordre volontaire


class TestNoChaseInProgressNeverDelays(unittest.TestCase):
    """Aucune chasse en cours -> aucun retard, comportement actuel strictement inchangé."""

    def test_empty_pending_orders_returns_immediately_without_sleep(self):
        with patch("orchestration.runner._load_config", return_value={}), \
             patch("orchestration.runner.load_maker_exit_pending_orders", return_value=[]), \
             patch("orchestration.runner.time.sleep") as mock_sleep:
            runner._wait_for_maker_exit_chase()

        mock_sleep.assert_not_called()


class TestChaseInProgressDelaysCycleStart(unittest.TestCase):
    """Une chasse en cours retarde le démarrage : on attend jusqu'à ce que la liste des ordres
    en attente se vide."""

    def test_waits_polling_until_pending_orders_clear(self):
        pending_sequence = iter([[{"trade_id": "T1"}], [{"trade_id": "T1"}], []])
        with patch("orchestration.runner._load_config", return_value={"maker_tick_seconds": 20}), \
             patch("orchestration.runner.load_maker_exit_pending_orders",
                   side_effect=lambda: next(pending_sequence)), \
             patch("orchestration.runner.time.sleep") as mock_sleep, \
             patch("orchestration.runner.time.monotonic", return_value=0.0):
            runner._wait_for_maker_exit_chase()

        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(20)  # poll = maker_tick_seconds, cadence du watcher


class TestWaitIsBoundedByTimeoutPlusMargin(unittest.TestCase):
    """L'attente est bornée : au-delà de maker_exit_timeout_seconds + marge, le cycle démarre
    malgré la chasse toujours en cours."""

    def test_stops_waiting_once_deadline_exceeded_even_if_still_pending(self):
        # deadline = 0 + 600 (timeout) + 60 (marge) = 660. Séquence : calcul deadline (0), deux
        # vérifications sous la borne (100, 200), puis une au-delà (700) -> sortie de boucle.
        monotonic_values = iter([0, 100, 200, 700])
        with patch("orchestration.runner._load_config",
                   return_value={"maker_exit_timeout_seconds": 600, "maker_tick_seconds": 5}), \
             patch("orchestration.runner.load_maker_exit_pending_orders",
                   return_value=[{"trade_id": "T1"}]), \
             patch("orchestration.runner.time.sleep") as mock_sleep, \
             patch("orchestration.runner.time.monotonic",
                   side_effect=lambda: next(monotonic_values)):
            runner._wait_for_maker_exit_chase()  # ne doit jamais lever StopIteration (pas de boucle infinie)

        self.assertEqual(mock_sleep.call_count, 2)


class TestStaleOrderDoesNotDelayCycle(unittest.TestCase):
    """Un ordre résidu (placed_at trop ancien pour être une chasse active) ne doit jamais
    retarder le démarrage d'un cycle, quelle que soit la cause du blocage côté watcher (#461)."""

    def setUp(self):
        runner._STALE_MAKER_EXIT_ALERTED_TXIDS.clear()

    def test_stale_pending_order_ignored_no_sleep_but_alerts(self):
        stale_placed_at = (datetime.now(timezone.utc) - timedelta(seconds=10_000)).isoformat()
        stale_pending = {"trade_id": "T1", "coin": "ETH", "txid": "SELLTX1", "placed_at": stale_placed_at}
        with patch("orchestration.runner._load_config", return_value={}), \
             patch("orchestration.runner.load_maker_exit_pending_orders", return_value=[stale_pending]), \
             patch("orchestration.runner.send_telegram") as mock_tg, \
             patch("orchestration.runner.time.sleep") as mock_sleep:
            runner._wait_for_maker_exit_chase()

        mock_sleep.assert_not_called()
        mock_tg.assert_called_once()
        self.assertIn("résidu", mock_tg.call_args[0][0])

    def test_stale_order_alerted_only_once_across_polls(self):
        """Casse le garde-fou dans l'autre sens : si l'ordre traîne sur plusieurs polls (ex.
        mélangé à une chasse active), l'alerte ne doit pas être répétée à chaque tour."""
        stale_placed_at = (datetime.now(timezone.utc) - timedelta(seconds=10_000)).isoformat()
        fresh_placed_at = datetime.now(timezone.utc).isoformat()
        stale_pending = {"trade_id": "T1", "coin": "ETH", "txid": "STALETX", "placed_at": stale_placed_at}
        fresh_pending = {"trade_id": "T2", "coin": "SOL", "txid": "FRESHTX", "placed_at": fresh_placed_at}
        batch_sequence = iter([
            [stale_pending, fresh_pending],
            [stale_pending, fresh_pending],
            [stale_pending],  # la chasse active s'est résolue, seul le résidu reste
        ])
        with patch("orchestration.runner._load_config", return_value={"maker_tick_seconds": 5}), \
             patch("orchestration.runner.load_maker_exit_pending_orders",
                   side_effect=lambda: next(batch_sequence)), \
             patch("orchestration.runner.send_telegram") as mock_tg, \
             patch("orchestration.runner.time.sleep") as mock_sleep, \
             patch("orchestration.runner.time.monotonic", return_value=0.0):
            runner._wait_for_maker_exit_chase()

        # Seule la chasse active (fresh_pending) fait attendre le cycle -> 2 polls avant qu'elle
        # ne se résolve, le résidu ne compte jamais dans l'attente.
        self.assertEqual(mock_sleep.call_count, 2)
        mock_tg.assert_called_once()  # jamais réalerté au 2e ni 3e passage


class TestRunWorkflowCycleWaitsBeforeLockCheck(unittest.TestCase):
    """Intégration : _run_workflow_cycle attend AVANT de vérifier/poser le verrou de cycle, pas
    après — sinon un cycle pourrait déjà avoir posé le verrou pendant l'attente."""

    def test_wait_called_before_is_locked_and_acquire_lock(self):
        call_order = []

        def _fake_wait():
            call_order.append("wait")

        def _fake_is_locked():
            call_order.append("is_locked")
            return True  # sort tôt après on_lock_busy, sans exécuter le reste du cycle

        with patch("orchestration.runner._wait_for_maker_exit_chase", side_effect=_fake_wait) as mock_wait, \
             patch("orchestration.runner.is_locked", side_effect=_fake_is_locked), \
             patch("orchestration.runner.acquire_lock") as mock_acquire:
            config = runner.WorkflowConfig(on_lock_busy=lambda: call_order.append("busy"))
            runner._run_workflow_cycle(
                prompt_template="prompt", log_prefix="cycle", trigger="manual",
                fmt_next_fn=None, cycle_type="trade", config=config,
            )

        mock_wait.assert_called_once()
        mock_acquire.assert_not_called()
        self.assertEqual(call_order, ["wait", "is_locked", "busy"])


class TestWaitIsTraced(unittest.TestCase):
    """Le retard doit être journalisé : sans trace, un cycle démarré en retard est indiscernable
    d'un cycle normal en lisant daemon.log (#461)."""

    def test_logs_start_and_resolution(self):
        pending_sequence = iter([[{"trade_id": "T1"}], []])
        with patch("orchestration.runner._load_config", return_value={"maker_tick_seconds": 20}), \
             patch("orchestration.runner.load_maker_exit_pending_orders",
                   side_effect=lambda: next(pending_sequence)), \
             patch("orchestration.runner.time.sleep"), \
             patch("orchestration.runner.time.monotonic", return_value=0.0), \
             patch("orchestration.runner.logger") as mock_logger:
            runner._wait_for_maker_exit_chase()

        info_msgs = [c.args[0] for c in mock_logger.info.call_args_list]
        self.assertTrue(any("en cours" in m for m in info_msgs))
        self.assertTrue(any("résolue" in m for m in info_msgs))

    def test_logs_warning_when_bound_reached(self):
        monotonic_values = iter([0, 100, 700])
        with patch("orchestration.runner._load_config",
                   return_value={"maker_exit_timeout_seconds": 600, "maker_tick_seconds": 5}), \
             patch("orchestration.runner.load_maker_exit_pending_orders",
                   return_value=[{"trade_id": "T1"}]), \
             patch("orchestration.runner.time.sleep"), \
             patch("orchestration.runner.time.monotonic",
                   side_effect=lambda: next(monotonic_values)), \
             patch("orchestration.runner.logger") as mock_logger:
            runner._wait_for_maker_exit_chase()

        warning_msgs = [c.args[0] for c in mock_logger.warning.call_args_list]
        self.assertTrue(any("Borne atteinte" in m for m in warning_msgs))

    def test_no_chase_does_not_log(self):
        with patch("orchestration.runner._load_config", return_value={}), \
             patch("orchestration.runner.load_maker_exit_pending_orders", return_value=[]), \
             patch("orchestration.runner.time.sleep"), \
             patch("orchestration.runner.logger") as mock_logger:
            runner._wait_for_maker_exit_chase()

        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
