#!/usr/bin/env python3
"""Tests for minsar.utils.ssaraopt_to_mintpy_plot."""

import unittest
from datetime import date

from minsar.utils.ssaraopt_to_mintpy_plot import (
    apply_mintpy_plot_line,
    mintpy_plot_from_ssaraopt_span,
    parse_ssaraopt_date,
    resolve_mintpy_plot_value,
    template_has_explicit_mintpy_plot,
)


class TestParseSsaraoptDate(unittest.TestCase):
    def test_yyyymmdd(self):
        self.assertEqual(parse_ssaraopt_date("20230101"), date(2023, 1, 1))

    def test_iso(self):
        self.assertEqual(parse_ssaraopt_date("2023-01-01"), date(2023, 1, 1))

    def test_auto_today(self):
        self.assertEqual(
            parse_ssaraopt_date("auto", today=date(2026, 7, 19)),
            date(2026, 7, 19),
        )

    def test_auto_disallowed(self):
        self.assertIsNone(parse_ssaraopt_date("auto", allow_auto=False))


class TestMintpyPlotFromSpan(unittest.TestCase):
    def test_quick_run_span_yes(self):
        self.assertEqual(
            mintpy_plot_from_ssaraopt_span("20260101", "20260228"),
            "yes",
        )

    def test_exactly_365_days_yes(self):
        # 2024 is leap: Jan 1 to Dec 31 = 365 days difference
        self.assertEqual(
            mintpy_plot_from_ssaraopt_span("20240101", "20241231"),
            "yes",
        )

    def test_non_leap_full_year_yes(self):
        self.assertEqual(
            mintpy_plot_from_ssaraopt_span("20250101", "20251231"),
            "yes",
        )

    def test_366_day_span_no(self):
        # Jan 1 2023 to Jan 2 2024 = 366 days
        self.assertEqual(
            mintpy_plot_from_ssaraopt_span("20230101", "20240102"),
            "no",
        )

    def test_multi_year_no(self):
        self.assertEqual(
            mintpy_plot_from_ssaraopt_span("20230101", "20241231"),
            "no",
        )

    def test_auto_end(self):
        # start 2026-01-01, today mid-year → yes
        self.assertEqual(
            mintpy_plot_from_ssaraopt_span(
                "20260101", "auto", today=date(2026, 6, 1)
            ),
            "yes",
        )

    def test_missing_start_no(self):
        self.assertEqual(mintpy_plot_from_ssaraopt_span(None, "20260101"), "no")

    def test_start_auto_no(self):
        self.assertEqual(mintpy_plot_from_ssaraopt_span("auto", "20260101"), "no")


class TestResolveAndApply(unittest.TestCase):
    def test_cli_override_wins(self):
        self.assertEqual(
            resolve_mintpy_plot_value(
                "20230101", "20241231", cli_override="yes"
            ),
            "yes",
        )
        self.assertEqual(
            resolve_mintpy_plot_value(
                "20260101", "20260228", cli_override="no"
            ),
            "no",
        )

    def test_apply_replaces_existing(self):
        text = "mintpy.plot                       = yes\nmintpy.plot.maxMemory = auto\n"
        out = apply_mintpy_plot_line(text, "no")
        self.assertIn("mintpy.plot                       = no", out)
        self.assertEqual(out.count("mintpy.plot "), 1)

    def test_apply_inserts_before_max_memory(self):
        text = "mintpy.load.autoPath = yes\nmintpy.plot.maxMemory = auto\n"
        out = apply_mintpy_plot_line(text, "no")
        self.assertIn("mintpy.plot                       = no", out)
        self.assertLess(out.index("mintpy.plot "), out.index("mintpy.plot.maxMemory"))

    def test_template_has_explicit(self):
        self.assertTrue(template_has_explicit_mintpy_plot("mintpy.plot = no\n"))
        self.assertFalse(template_has_explicit_mintpy_plot("mintpy.plot = auto\n"))
        self.assertFalse(template_has_explicit_mintpy_plot("mintpy.plot.maxMemory = auto\n"))


if __name__ == "__main__":
    unittest.main()
