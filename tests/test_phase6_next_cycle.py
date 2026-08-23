"""Tests d'intégration pour phase6_next_cycle.py — calcul du prochain slot 4h UTC et affichage
au fuseau configuré (#421 : le script réimplémentait son propre calcul et son propre formatage,
ratant ainsi le correctif #393 et affichant l'heure du fuseau machine au lieu de `display_timezone`).

Le script réutilise désormais `core.timing.next_4h_slot()` et `core.timing.fmt_local()`. On gèle
l'heure courante en patchant l'attribut `datetime` du module `core.timing` (nom lié via
`from datetime import datetime`, pas le module stdlib top-level — `core.timing` est déjà en cache
dans sys.modules quand le script est exécuté via exec_phase_script, donc patcher cet attribut
affecte bien l'appel fait depuis le script). `display_timezone` est fixé explicitement à
Europe/Paris (comme tests/test_timing.py) pour que les tests restent indépendants du fuseau de la
machine qui les exécute.

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire
from config.app import APP_CONFIG  # noqa: E402
from core.timing import fmt_local  # noqa: E402

PHASE6_NEXT_CYCLE_PATH = os.path.join(
    PROJECT_DIR, "binance-bot", "core", "phases", "phase6_next_cycle.py",
)


def _expected_next_str(next_slot_utc):
    return fmt_local(next_slot_utc)


def _run_phase6_next_cycle(now_utc):
    """Exécute phase6_next_cycle.py avec l'heure UTC courante gelée à `now_utc`."""

    class _FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return now_utc.astimezone(tz) if tz else now_utc

    cycle_id = harness.new_cycle_id()
    out_path = f"/tmp/cycle_{cycle_id}_phase6_next_output.json"
    try:
        with patch("core.timing.datetime", _FrozenDatetime):
            harness.exec_phase_script(PHASE6_NEXT_CYCLE_PATH, cycle_id)
        return harness.load_and_remove_json(out_path)
    finally:
        harness.remove_if_exists(out_path)


class _DisplayTimezoneTestCase(unittest.TestCase):
    """Fixe `display_timezone` à Europe/Paris, indépendamment du fuseau de la machine hôte."""

    def setUp(self):
        self._original_tz = APP_CONFIG.get("display_timezone")
        APP_CONFIG["display_timezone"] = "Europe/Paris"

    def tearDown(self):
        if self._original_tz is None:
            APP_CONFIG.pop("display_timezone", None)
        else:
            APP_CONFIG["display_timezone"] = self._original_tz


class TestNextSlotJustBeforeSlot(_DisplayTimezoneTestCase):
    """Heure juste avant un slot -> le slot du jour reste le prochain."""

    def test_next_slot_is_same_day_slot_when_just_before(self):
        now_utc = datetime.datetime(2026, 7, 26, 4, 4, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 26, 4, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


class TestNextSlotJustAfterSlot(_DisplayTimezoneTestCase):
    """Heure juste après un slot -> le prochain slot 4h suivant est visé."""

    def test_next_slot_is_next_4h_slot_when_just_after(self):
        now_utc = datetime.datetime(2026, 7, 26, 4, 6, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 26, 8, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


class TestNextSlotExactlyOnSlotBoundary(_DisplayTimezoneTestCase):
    """Cas limite : heure exactement sur un slot (04:05:00) -> le prochain slot est visé, pas le
    slot courant (next_slot <= now déclenche le +4h)."""

    def test_next_slot_skips_to_following_slot_when_exactly_on_boundary(self):
        now_utc = datetime.datetime(2026, 7, 26, 4, 5, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 26, 8, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


class TestNextSlotCrossingMidnight(_DisplayTimezoneTestCase):
    """Heure en soirée -> le prochain slot 4h franchit minuit vers le jour suivant."""

    def test_next_slot_crosses_midnight_to_next_day(self):
        now_utc = datetime.datetime(2026, 7, 26, 22, 30, 0, tzinfo=datetime.timezone.utc)
        next_slot_utc = datetime.datetime(2026, 7, 27, 0, 5, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], _expected_next_str(next_slot_utc))


class TestNextSlotUsesConfiguredTimezoneNotMachineTimezone(_DisplayTimezoneTestCase):
    """Régression #421 : la sortie doit refléter `display_timezone` (Europe/Paris ici), pas le
    fuseau de la machine qui exécute le sous-processus (ex : VPS en Etc/UTC, où `astimezone()`
    sans argument ne convertit rien et affiche l'heure UTC telle quelle sous un libellé
    "heure locale" mensonger)."""

    def test_output_is_paris_offset_not_raw_utc(self):
        # Été -> Paris = UTC+2 (CEST). Slot 08:05 UTC doit s'afficher 10:05, jamais 08:05.
        now_utc = datetime.datetime(2026, 7, 26, 4, 6, 0, tzinfo=datetime.timezone.utc)
        output = _run_phase6_next_cycle(now_utc)

        self.assertEqual(output["next_str"], "26/07 10:05 (heure locale)")


if __name__ == "__main__":
    unittest.main()
