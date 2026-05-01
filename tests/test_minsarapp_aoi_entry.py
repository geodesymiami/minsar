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
from minsar.scripts.minsarapp_aoi_entry import (
    apply_flight_dir_to_ct_list,
    expand_flight_dir_for_dual_templates,
    minsarapp_args_after_primary,
)


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


class TestMinsarappOppositeOrbitForBoth(unittest.TestCase):
    def test_asc_desc_inserts_opposite_orbit(self) -> None:
        p = "/te/FooSenA1.template"
        self.assertEqual(
            minsarapp_args_after_primary(p, "asc,desc", []),
            [p, "--opposite-orbit"],
        )

    def test_desc_asc_inserts_opposite_orbit(self) -> None:
        p = "/te/FooSenD1.template"
        self.assertEqual(
            minsarapp_args_after_primary(p, "desc,asc", ["--start", "jobfiles"]),
            [p, "--opposite-orbit", "--start", "jobfiles"],
        )

    def test_both_inserts_opposite_orbit(self) -> None:
        p = "/te/FooSenA1.template"
        self.assertEqual(
            minsarapp_args_after_primary(p, "both", []),
            [p, "--opposite-orbit"],
        )
        self.assertEqual(
            minsarapp_args_after_primary(p, "both", ["--start", "download"]),
            [p, "--opposite-orbit", "--start", "download"],
        )

    def test_both_respects_no_opposite_orbit(self) -> None:
        p = "/te/FooSenA1.template"
        self.assertEqual(
            minsarapp_args_after_primary(
                p, "both", ["--no-opposite-orbit", "--miaplpy"]
            ),
            [p, "--no-opposite-orbit", "--miaplpy"],
        )

    def test_both_does_not_duplicate_opposite_orbit(self) -> None:
        p = "/te/FooSenA1.template"
        self.assertEqual(
            minsarapp_args_after_primary(
                p, "both", ["--opposite-orbit", "--start", "ifgram"]
            ),
            [p, "--opposite-orbit", "--start", "ifgram"],
        )

    def test_asc_no_insert(self) -> None:
        p = "/te/x.template"
        self.assertEqual(
            minsarapp_args_after_primary(p, "asc", ["--start", "download"]),
            [p, "--start", "download"],
        )

    def test_desc_no_insert(self) -> None:
        p = "/te/x.template"
        self.assertEqual(
            minsarapp_args_after_primary(p, "desc", []),
            [p],
        )

    def test_asc_with_opposite_in_rest_no_duplicate_insert(self) -> None:
        p = "/te/x.template"
        self.assertEqual(
            minsarapp_args_after_primary(
                p, "asc", ["--opposite-orbit", "--miaplpy"]
            ),
            [p, "--opposite-orbit", "--miaplpy"],
        )


class TestExpandFlightDirForTemplates(unittest.TestCase):
    def test_asc_plus_opposite_becomes_asc_desc(self) -> None:
        self.assertEqual(
            expand_flight_dir_for_dual_templates("asc", ["--opposite-orbit"]),
            "asc,desc",
        )

    def test_desc_plus_opposite_becomes_desc_asc(self) -> None:
        self.assertEqual(
            expand_flight_dir_for_dual_templates("desc", ["--opposite-orbit"]),
            "desc,asc",
        )

    def test_respects_no_opposite(self) -> None:
        self.assertEqual(
            expand_flight_dir_for_dual_templates(
                "asc", ["--no-opposite-orbit", "--opposite-orbit"]
            ),
            "asc",
        )

    def test_dual_unchanged(self) -> None:
        self.assertEqual(
            expand_flight_dir_for_dual_templates("asc,desc", ["--opposite-orbit"]),
            "asc,desc",
        )


class TestApplyFlightDirToCtList(unittest.TestCase):
    def test_two_token_form(self) -> None:
        self.assertEqual(
            apply_flight_dir_to_ct_list(
                ["1:2,3:4", "N", "--flight-dir", "asc", "--period", "2024"],
                "asc,desc",
            ),
            ["1:2,3:4", "N", "--flight-dir", "asc,desc", "--period", "2024"],
        )

    def test_equals_form(self) -> None:
        self.assertEqual(
            apply_flight_dir_to_ct_list(["a", "b", "--flight-dir=desc"], "desc,asc"),
            ["a", "b", "--flight-dir=desc,asc"],
        )


if __name__ == "__main__":
    if not os.environ.get("MINSAR_HOME"):
        os.environ["MINSAR_HOME"] = str(_REPO)
    unittest.main()
