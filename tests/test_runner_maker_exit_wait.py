"""Tests pour orchestration/runner.py — attente bornée d'une chasse de sortie maker avant le
démarrage d'un cycle (#461).

Contexte : un cycle pose le verrou (state/agent_lock.json) pendant toute sa durée (médiane 418s,
p90 609s, max observé 15617s). Si une chasse de sortie maker est en cours quand un cycle
démarre, le watcher (_maker_exit_watcher_tick) ne peut plus s'exécuter tant que le cycle tourne
-> la position reste sans stop au-delà du délai de chasse prévu. La correction fait attendre le
cycle (avant acquire_lock()) tant que state/maker_exit_pending_orders.json n'est pas vide,
borné à maker_exit_timeout_seconds + marge pour ne jamais bloquer indéfiniment.

_load_config, load_maker_exit_pending_orders et time.sleep/time.monotonic sont mockés (jamais le
vrai config.json ni le vrai state/*.json, jamais de vraie attente)."""
import os
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
