#!/usr/bin/env python3
"""Tests for create_template _parse_cli_date_to_yyyymmdd."""
import importlib.util
import sys
import unittest
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


class TestParseCliDate(unittest.TestCase):
    def test_yyyy_mm_dd(self) -> None:
        self.assertEqual(
            ct._parse_cli_date_to_yyyymmdd("2023-01-01"), "20230101"
        )

    def test_yyyymmdd(self) -> None:
        self.assertEqual(
            ct._parse_cli_date_to_yyyymmdd("20230101"), "20230101"
        )

    def test_strips_whitespace(self) -> None:
        self.assertEqual(
            ct._parse_cli_date_to_yyyymmdd("  2024-12-31  "), "20241231"
        )
        self.assertEqual(
            ct._parse_cli_date_to_yyyymmdd("\t20190101\n"), "20190101"
        )

    def test_invalid_calendar(self) -> None:
        with self.assertRaises(ValueError):
            ct._parse_cli_date_to_yyyymmdd("2023-02-29")

    def test_rejects_malformed(self) -> None:
        for bad in ("2023", "2023-13-01", "abcd0101", "2023-1-1", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ct._parse_cli_date_to_yyyymmdd(bad)

    def test_period_substrings_use_same_parser(self) -> None:
        s, e = ct._parse_period("20210101:2021-12-31")
        self.assertEqual(s, "20210101")
        self.assertEqual(e, "20211231")


if __name__ == "__main__":
    unittest.main()
