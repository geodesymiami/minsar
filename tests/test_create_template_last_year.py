#!/usr/bin/env python3
"""Tests for create_template.py --last-year date range."""
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_CT_PATH = _REPO / "minsar" / "scripts" / "create_template.py"


def _load_create_template():
    spec = importlib.util.spec_from_file_location("create_template", _CT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct = _load_create_template()


class TestLastCalendarYearRange(unittest.TestCase):
    def test_previous_year_full_range(self):
        self.assertEqual(
            ct._last_calendar_year_full_range(date(2026, 4, 7)),
            ("20250101", "20251231"),
        )

    def test_january_first_still_previous_calendar_year(self):
        self.assertEqual(
            ct._last_calendar_year_full_range(date(2026, 1, 1)),
            ("20250101", "20251231"),
        )


if __name__ == "__main__":
    unittest.main()
