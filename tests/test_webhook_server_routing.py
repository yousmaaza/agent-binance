"""Tests d'intégration pour le routing des commandes Telegram dans webhook_server.py.

`main_loop()` n'expose pas de fonction de dispatch séparée : le routing (`if text.startswith(...)`)
vit directement dans la boucle `while True` de polling. On exécute donc la vraie `main_loop()`
avec tous ses I/O mockés (tg_post/get_offset/save_offset/send_telegram/validate_and_repair_boot,
`threading.Thread` remplacé par une classe qui exécute la cible immédiatement et
synchroniquement), en injectant un unique faux update Telegram, puis on interrompt la boucle
via une sentinelle `BaseException` (jamais catchée par le `except Exception` du polling) levée
au 2e appel `getUpdates` — jamais de vrai long-polling, jamais de vrai CLI `claude` (les
handlers réels comme `run_trade_workflow` sont mockés, donc `_run_claude` n'est jamais atteint).

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

import webhook_server  # noqa: E402 -- import après sys.path.insert, ordre volontaire

TEST_CHAT_ID = "555555"


class _StopMainLoop(BaseException):
    """Sentinelle pour interrompre main_loop() — hérite de BaseException (pas Exception) pour
    ne pas être interceptée par le `except Exception` de la boucle de polling."""


class _FakeThread:
    """Remplace threading.Thread dans webhook_server : exécute la cible immédiatement et
    synchroniquement (pas de vrai thread) pour observer ses effets dans le test."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


def _fake_update(text):
    return {"update_id": 1, "message": {"text": text, "chat": {"id": int(TEST_CHAT_ID)}}}


def _run_one_command(text):
    """Exécute main_loop() jusqu'au traitement d'un unique message Telegram `text`, puis
    l'interrompt. Retourne le dict des mocks utilisés (clés = noms d'attributs webhook_server)."""
    mocks = {
        "tg_post": MagicMock(side_effect=[{}, {"result": [_fake_update(text)]}, _StopMainLoop()]),
        "get_offset": MagicMock(return_value=0),
        "save_offset": MagicMock(),
        "send_telegram": MagicMock(),
        "validate_and_repair_boot": MagicMock(return_value=(True, None)),
        "tp_watcher_loop": MagicMock(),
        "maker_watcher_loop": MagicMock(),
        "maker_exit_watcher_loop": MagicMock(),
        "release_lock": MagicMock(),
        "run_trade_workflow": MagicMock(),
        "run_status": MagicMock(return_value="status-text"),
        "run_perf": MagicMock(return_value="perf-text"),
        "run_maker": MagicMock(return_value="maker-text"),
    }

    with contextlib.ExitStack() as stack:
        for name, mock in mocks.items():
            stack.enter_context(patch.object(webhook_server, name, mock))
        stack.enter_context(
            patch.object(webhook_server, "threading", types.SimpleNamespace(Thread=_FakeThread)),
        )
        stack.enter_context(patch("core.env.CHAT_ID", TEST_CHAT_ID))

        try:
            webhook_server.main_loop()
        except _StopMainLoop:
            pass

    return mocks


class TestStatusCommandRouting(unittest.TestCase):
    """`/status` -> run_status() appelé, résultat envoyé en HTML."""

    def test_status_dispatches_run_status_and_sends_html_result(self):
        mocks = _run_one_command("/status")

        mocks["run_status"].assert_called_once()
        mocks["send_telegram"].assert_any_call("status-text", parse_mode="HTML")


class TestTradeCommandRouting(unittest.TestCase):
    """`/trade` -> run_trade_workflow() déclenché en trigger manuel, jamais le vrai CLI claude."""

    def test_trade_dispatches_run_trade_workflow_manual(self):
        mocks = _run_one_command("/trade")

        mocks["run_trade_workflow"].assert_called_once()
        _, kwargs = mocks["run_trade_workflow"].call_args
        self.assertEqual(kwargs["trigger"], "manual")


class TestPerfCommandRouting(unittest.TestCase):
    """`/perf` -> run_perf() appelé, résultat envoyé en HTML."""

    def test_perf_dispatches_run_perf_and_sends_html_result(self):
        mocks = _run_one_command("/perf")

        mocks["run_perf"].assert_called_once()
        mocks["send_telegram"].assert_any_call("perf-text", parse_mode="HTML")


class TestMakerCommandRouting(unittest.TestCase):
    """`/maker` -> run_maker() appelé, résultat envoyé en HTML."""

    def test_maker_dispatches_run_maker_and_sends_html_result(self):
        mocks = _run_one_command("/maker")

        mocks["run_maker"].assert_called_once()
        mocks["send_telegram"].assert_any_call("maker-text", parse_mode="HTML")


class TestResetCommandRouting(unittest.TestCase):
    """`/reset` -> release_lock() appelé, notification de confirmation envoyée."""

    def test_reset_releases_lock_and_notifies(self):
        mocks = _run_one_command("/reset")

        mocks["release_lock"].assert_called_once()
        sent_text = mocks["send_telegram"].call_args[0][0]
        self.assertIn("Lock réinitialisé", sent_text)


class TestUnknownCommandRouting(unittest.TestCase):
    """Commande inconnue -> comportement par défaut : rappel de la liste des commandes."""

    def test_unknown_command_sends_commands_help(self):
        mocks = _run_one_command("/inconnu")

        sent_text = mocks["send_telegram"].call_args[0][0]
        self.assertIn("Commandes :", sent_text)
        mocks["run_trade_workflow"].assert_not_called()
        mocks["run_status"].assert_not_called()
        mocks["run_perf"].assert_not_called()
        mocks["run_maker"].assert_not_called()
        mocks["release_lock"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
