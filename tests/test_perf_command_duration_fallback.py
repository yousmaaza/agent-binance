"""Tests pour commands/perf.py — repli sur `duration_seconds` dans le bloc Mongo (#452).

Les 102 cycles en erreur déjà en base ne portent que `duration_seconds` (jamais `duration_s`,
écrit uniquement par le nouveau chemin unifié). Sans repli, leur durée disparaîtrait de la
moyenne affichée par /perf — aucune migration de données n'est faite dans ce ticket."""
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))

from commands import (
    perf,
)


class _FakeCyclesCollection:
    def __init__(self, rows):
        self._rows = rows

    def find(self, _filter, _projection):
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self.cycles = _FakeCyclesCollection(rows)


class TestDurationFallbackToLegacyField(unittest.TestCase):
    def test_average_includes_rows_with_only_duration_seconds(self):
        rows = [
            {"execution": {}, "decisions": [], "duration_s": 100, "error_type": None},
            {"execution": {}, "decisions": [], "duration_seconds": 200, "error_type": "crash"},
        ]
        fake_db = _FakeDb(rows)

        with patch("storage.mongo.mongo_repo._db", return_value=fake_db):
            lines = perf._bloc_cycles()

        joined = "\n".join(lines)
        self.assertIn("Durée moy. : <code>150s</code>", joined)  # (100+200)/2, les deux comptent
        self.assertIn("(source : Mongo)", joined)

    def test_row_with_neither_field_excluded_without_crashing(self):
        rows = [
            {"execution": {}, "decisions": [], "duration_s": 100, "error_type": None},
            {"execution": {}, "decisions": [], "error_type": "crash"},  # ni duration_s ni duration_seconds
        ]
        fake_db = _FakeDb(rows)

        with patch("storage.mongo.mongo_repo._db", return_value=fake_db):
            lines = perf._bloc_cycles()

        joined = "\n".join(lines)
        self.assertIn("Durée moy. : <code>100s</code>", joined)


if __name__ == "__main__":
    unittest.main()
