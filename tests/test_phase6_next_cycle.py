"""Tests d'intégration pour phase6_next_cycle.py — calcul du prochain slot 4h UTC.

Le script lit l'heure courante via `datetime.datetime.now(datetime.timezone.utc)` : on gèle
cette valeur en patchant l'attribut `datetime.datetime` du module stdlib partagé (même objet
que celui importé par le script via `import datetime`), avec une sous-classe dont `now()`
retourne une heure figée. Le formatage final passe par `.astimezone()` (heure locale, sans
argument) — le test reproduit exactement le même appel pour construire la valeur attendue,
plutôt que de figer un fuseau, afin de rester indépendant du fuseau de la machine qui exécute
les tests.

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE6_NEXT_CYCLE_PATH = os.path.join(
    PROJECT_DIR, "binance-bot", "core", "phases", "phase6_next_cycle.py",
)


def _expected_next_str(next_slot_utc):
    return next_slot_utc.astimezone().strftime("%d/%m %H:%M") + " (heure locale)"


def _run_phase6_next_cycle(now_utc):
    """Exécute phase6_next_cycle.py avec l'heure UTC courante gelée à `now_utc`."""

    class _FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return now_utc.astimezone(tz) if tz else now_utc

    cycle_id = harness.new_cycle_id()
    out_path = f"/tmp/cycle_{cycle_id}_phase6_next_output.json"
    try:
        with patch("datetime.datetime", _FrozenDatetime):
            harness.exec_phase_script(PHASE6_NEXT_CYCLE_PATH, cycle_id)
        return harness.load_and_remove_json(out_path)
    finally:
        harness.remove_if_exists(out_path)


class TestNextSlotJustBeforeSlot(unittest.TestCase):
    """Heure juste avant un slot -> le slot du jour reste le prochain."""

    def test_next_slot_is_same_day_slot_when_just_before(self):
        now_utc = datetime.datetime(2026, 7, 26, 4, 4, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 26, 4, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


class TestNextSlotJustAfterSlot(unittest.TestCase):
    """Heure juste après un slot -> le prochain slot 4h suivant est visé."""

    def test_next_slot_is_next_4h_slot_when_just_after(self):
        now_utc = datetime.datetime(2026, 7, 26, 4, 6, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 26, 8, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


class TestNextSlotExactlyOnSlotBoundary(unittest.TestCase):
    """Cas limite : heure exactement sur un slot (04:05:00) -> le prochain slot est visé, pas le
    slot courant (next_slot <= now déclenche le +4h)."""

    def test_next_slot_skips_to_following_slot_when_exactly_on_boundary(self):
        now_utc = datetime.datetime(2026, 7, 26, 4, 5, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 26, 8, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


class TestNextSlotCrossingMidnight(unittest.TestCase):
    """Heure en soirée -> le prochain slot 4h franchit minuit vers le jour suivant."""

    def test_next_slot_crosses_midnight_to_next_day(self):
        now_utc = datetime.datetime(2026, 7, 26, 22, 30, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 27, 0, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


if __name__ == "__main__":
    unittest.main()
