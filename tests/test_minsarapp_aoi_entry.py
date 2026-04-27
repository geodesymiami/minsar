#!/usr/bin/env python3
"""Tests for argv splitting used by minsarapp_aoi_entry (create_template vs minsarApp)."""
import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from minsar.scripts.create_template import create_parser


def _split_for_bridge(fixed: list[str]) -> tuple[list[str], list[str]]:
    """Mirror minsarapp_aoi_entry: parse_known and slice."""
    p = create_parser(add_help=False)
    _ns, rest = p.parse_known_args(fixed)
    n = len(rest)
    if n:
        ct_list = fixed[: len(fixed) - n]
    else:
        ct_list = list(fixed)
    return ct_list, list(rest)


class TestMinsarappAoiSplit(unittest.TestCase):
    def test_minsar_start_not_abbrev_of_start_date(self) -> None:
        """--start is forwarded to minsarApp, not misparsed as --start-date."""
        fixed = ["1:2,3:4", "N", "--start", "download"]
        ct, ms = _split_for_bridge(fixed)
        self.assertEqual(ct, ["1:2,3:4", "N"])
        self.assertEqual(ms, ["--start", "download"])

    def test_create_template_options_consumed(self) -> None:
        fixed = [
            "1:2,3:4",
            "N",
            "--period",
            "2024",
            "--flight-dir",
            "asc",
        ]
        ct, rest = _split_for_bridge(fixed)
        self.assertEqual(ct, fixed)
        self.assertEqual(rest, [])

    def test_minsar_options_after_ct_options(self) -> None:
        fixed = [
            "1:2,3:4",
            "N",
            "--period",
            "2024",
            "--start",
            "download",
        ]
        ct, rest = _split_for_bridge(fixed)
        self.assertEqual(ct, ["1:2,3:4", "N", "--period", "2024"])
        self.assertEqual(rest, ["--start", "download"])


if __name__ == "__main__":
    if not os.environ.get("MINSAR_HOME"):
        os.environ["MINSAR_HOME"] = str(_REPO)
    unittest.main()
