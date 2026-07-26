"""Tests d'intégration pour phase8_cycle_log.py — append JSONL + rotation 90 lignes + push git.

`state/cycle_log.jsonl` est un fichier de production réel (jamais touché par les tests, cf.
CLAUDE.md) : `os.path.exists()` et `open()` sont interceptés spécifiquement pour ce chemin
(lecture/écriture en mémoire), tout le reste passe par les vraies fonctions. Le script interne
génère et exécute un script bash (`subprocess.run([script_path], ...)`) pour committer/pusher —
`subprocess.run` est mocké pour qu'aucun vrai `git commit`/`push` ne soit déclenché.

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE8_CYCLE_LOG_PATH = os.path.join(
    PROJECT_DIR, "binance-bot", "core", "phases", "phase8_cycle_log.py",
)
CYCLE_LOG_PATH = os.path.join(PROJECT_DIR, "state", "cycle_log.jsonl")

_real_exists = os.path.exists


class _CaptureFile(io.StringIO):
    """StringIO dont le contenu écrit est renvoyé dans `sink` à la fermeture (mode 'w')."""

    def __init__(self, sink, initial_value=""):
        super().__init__(initial_value)
        self._sink = sink

    def close(self):
        self._sink.append(self.getvalue())
        super().close()


def _fake_exists_factory(file_exists):
    def _fake_exists(path):
        if os.path.abspath(str(path)) == CYCLE_LOG_PATH:
            return file_exists
        return _real_exists(path)
    return _fake_exists


def _fake_open_factory(existing_lines, captured_writes):
    def _fake_open(path, mode="r", *args, **kwargs):
        if os.path.abspath(str(path)) == CYCLE_LOG_PATH:
            if "w" in mode:
                return _CaptureFile(captured_writes)
            content = "\n".join(existing_lines) + ("\n" if existing_lines else "")
            return io.StringIO(content)
        return harness._real_open(path, mode, *args, **kwargs)
    return _fake_open


def _run_phase8_cycle_log(input_data, existing_lines=None, subprocess_returncode=0):
    """Exécute phase8_cycle_log.py. Retourne (captured_writes, mock_tg, mock_subprocess_run)."""
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase8_input.json"
    script_path = f"/tmp/_cl_push_{cycle_id}.sh"
    with open(in_path, "w") as f:
        json.dump(input_data, f)

    captured_writes = []
    mock_subprocess_run = MagicMock(
        return_value=MagicMock(returncode=subprocess_returncode, stdout="", stderr="fail msg"),
    )
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            stack.enter_context(patch("os.path.exists", side_effect=_fake_exists_factory(
                existing_lines is not None,
            )))
            stack.enter_context(patch("builtins.open", side_effect=_fake_open_factory(
                existing_lines or [], captured_writes,
            )))
            stack.enter_context(patch("subprocess.run", mock_subprocess_run))

            harness.exec_phase_script(PHASE8_CYCLE_LOG_PATH, cycle_id)

        return captured_writes, mock_tg, mock_subprocess_run
    finally:
        harness.remove_if_exists(in_path, script_path)


DEFAULT_INPUT = {
    "top_score": 5, "executed": 1, "skipped": 0,
    "skip_type": None, "skip_detail": None,
    "portfolio": 200.0, "sentiment": "Neutral", "open_positions": 2,
}


class TestAppendsNewLineToEmptyLog(unittest.TestCase):
    """Fichier absent -> une seule ligne JSONL écrite avec les champs de synthèse fournis."""

    def test_appends_single_entry_when_log_absent(self):
        captured_writes, mock_tg, mock_subprocess_run = _run_phase8_cycle_log(
            DEFAULT_INPUT, existing_lines=None,
        )

        self.assertEqual(len(captured_writes), 1)
        lines = [ln for ln in captured_writes[0].splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["top_score"], 5)
        self.assertEqual(entry["executed"], 1)
        self.assertEqual(entry["portfolio"], 200.0)
        mock_subprocess_run.assert_called_once()
        mock_tg.assert_not_called()


class TestNoRotationAtExactly90Lines(unittest.TestCase):
    """89 lignes existantes + 1 append = 90 total -> aucune ligne supprimée (pas de rotation)."""

    def test_keeps_all_90_lines_when_total_is_exactly_90(self):
        existing = [json.dumps({"cycle_id": f"C{i}"}) for i in range(89)]
        captured_writes, _, _ = _run_phase8_cycle_log(DEFAULT_INPUT, existing_lines=existing)

        lines = [ln for ln in captured_writes[0].splitlines() if ln.strip()]
        self.assertEqual(len(lines), 90)
        self.assertEqual(json.loads(lines[0])["cycle_id"], "C0")  # la plus ancienne conservée


class TestRotationAt91LinesDropsOldest(unittest.TestCase):
    """90 lignes existantes + 1 append = 91 total -> rotation, la plus ancienne est supprimée."""

    def test_drops_oldest_line_when_total_exceeds_90(self):
        existing = [json.dumps({"cycle_id": f"C{i}"}) for i in range(90)]
        captured_writes, _, _ = _run_phase8_cycle_log(DEFAULT_INPUT, existing_lines=existing)

        lines = [ln for ln in captured_writes[0].splitlines() if ln.strip()]
        self.assertEqual(len(lines), 90)
        self.assertEqual(json.loads(lines[0])["cycle_id"], "C1")  # C0 a été droppée
        self.assertEqual(json.loads(lines[-1])["top_score"], 5)  # la nouvelle entrée en dernier


class TestGitPushFailureNotifiesTelegram(unittest.TestCase):
    """subprocess.run renvoie un code non-zéro -> tg() notifie l'échec, sans lever d'exception."""

    def test_notifies_when_push_script_fails(self):
        captured_writes, mock_tg, mock_subprocess_run = _run_phase8_cycle_log(
            DEFAULT_INPUT, existing_lines=None, subprocess_returncode=1,
        )

        mock_subprocess_run.assert_called_once()
        mock_tg.assert_called_once()
        self.assertIn("push échoué", mock_tg.call_args[0][0])
        # L'écriture JSONL elle-même a bien eu lieu malgré l'échec du push git
        self.assertEqual(len(captured_writes), 1)


if __name__ == "__main__":
    unittest.main()
