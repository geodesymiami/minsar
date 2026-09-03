#!/usr/bin/env python3
"""Tests for create_template.py tropo / insarmaps_dataset CLI wiring."""
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

_DUMMY = (
    "ssaraopt.relativeOrbit = 1\n"
    "mintpy.troposphericDelay.method    = auto\n"
    "minsar.insarmaps_dataset             = filt*DS\n"
)


class TestSubstituteTropoInsarmaps(unittest.TestCase):
    def test_overrides_both(self):
        out = ct._substitute_template(
            _DUMMY,
            relative_orbit=9,
            subset_lalo="1:2,3:4",
            start_date=None,
            end_date=None,
            exclude_season=None,
            mintpy_tropospheric_delay_method="no",
            minsar_insarmaps_dataset="DS",
        )
        self.assertRegex(
            out, r"(?m)^\s*mintpy\.troposphericDelay\.method\s*=\s*no\s"
        )
        self.assertRegex(out, r"(?m)^\s*minsar\.insarmaps_dataset\s*=\s*DS\s")

    def test_defaults_unchanged_when_none(self):
        out = ct._substitute_template(
            _DUMMY,
            relative_orbit=9,
            subset_lalo="1:2,3:4",
            start_date=None,
            end_date=None,
            exclude_season=None,
        )
        self.assertRegex(
            out, r"(?m)^\s*mintpy\.troposphericDelay\.method\s*=\s*auto\s"
        )
        self.assertRegex(
            out, r"(?m)^\s*minsar\.insarmaps_dataset\s*=\s*filt\*DS\s"
        )


class TestTropoInsarmapsCliFlags(unittest.TestCase):
    def test_long_options_parse(self):
        parser = ct.create_parser()
        inps = parser.parse_args(
            [
                "36.3:36.4,25.3:25.4",
                "T",
                "--mintpy.troposphericDelay.method",
                "no",
                "--minsar.insarmaps_dataset",
                "DS",
            ]
        )
        self.assertEqual(inps.mintpy_tropospheric_delay_method, "no")
        self.assertEqual(inps.minsar_insarmaps_dataset, "DS")

    def test_short_options_parse(self):
        parser = ct.create_parser()
        inps = parser.parse_args(
            [
                "36.3:36.4,25.3:25.4",
                "T",
                "--tropo",
                "no",
                "--insarmaps-dataset",
                "DS",
            ]
        )
        self.assertEqual(inps.mintpy_tropospheric_delay_method, "no")
        self.assertEqual(inps.minsar_insarmaps_dataset, "DS")

    def test_invalid_tropo_rejected(self):
        with self.assertRaises(ValueError):
            ct._validate_mintpy_tropospheric_delay_method("bogus")


if __name__ == "__main__":
    unittest.main()
