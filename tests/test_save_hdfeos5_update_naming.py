"""Regression tests for the hardwired 31-day XXXXXXXX naming policy."""

import unittest
from datetime import date


def _use_x(last_date_ymd: str, today: date) -> bool:
    """Mirror additions/mintpy/save_hdfeos5.py hardwired 31-day policy."""
    from datetime import datetime

    last = datetime.strptime(last_date_ymd[0:10], "%Y-%m-%d").date()
    return (today - last).days <= 31


class TestUpdatePlaceholderHeuristic(unittest.TestCase):
    def test_fresh_last_date_uses_placeholder(self):
        # last is 5 days before 'today' -> use X
        self.assertTrue(_use_x("2026-04-20", date(2026, 4, 25)))

    def test_stale_last_date_uses_real_ymd(self):
        # 400+ days old -> not placeholder
        self.assertFalse(_use_x("2024-12-30", date(2026, 4, 26)))

    def test_boundary_31_days(self):
        # exactly 32 days: no placeholder; 31 days: still placeholder
        t = date(2026, 4, 26)
        self.assertTrue(_use_x("2026-03-26", t))  # 31 days
        self.assertFalse(_use_x("2026-03-25", t))  # 32 days


if __name__ == "__main__":
    unittest.main()
