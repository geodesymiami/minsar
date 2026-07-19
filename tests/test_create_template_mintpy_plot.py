#!/usr/bin/env python3
"""Tests for create_template.py mintpy.plot span / CLI wiring."""
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


class TestSubstituteMintpyPlot(unittest.TestCase):
    def test_span_short_writes_yes(self):
        dummy = (
            "ssaraopt.relativeOrbit = 1\n"
            "ssaraopt.startDate = 20141001\n"
            "ssaraopt.endDate = auto\n"
            "topsStack.coregistration = NESD\n"
            "miaplpy.subset.lalo = 0:1,0:1\n"
            "mintpy.plot = no\n"
            "mintpy.plot.maxMemory = auto\n"
        )
        out = ct._substitute_template(
            dummy,
            relative_orbit=9,
            subset_lalo="1:2,3:4",
            start_date="20260101",
            end_date="20260228",
            exclude_season=None,
            mintpy_plot="yes",
        )
        self.assertRegex(out, r"(?m)^\s*mintpy\.plot\s*=\s*yes\s*$")
        self.assertIn("20260101", out)
        self.assertIn("20260228", out)

    def test_cli_no_overrides(self):
        dummy = "mintpy.plot = yes\nmintpy.plot.maxMemory = auto\n"
        out = ct._substitute_template(
            dummy,
            relative_orbit=1,
            subset_lalo="1:2,3:4",
            start_date="20260101",
            end_date="20260228",
            exclude_season=None,
            mintpy_plot="no",
        )
        self.assertRegex(out, r"(?m)^\s*mintpy\.plot\s*=\s*no\s*$")


class TestMintpyPlotCliFlags(unittest.TestCase):
    def test_mutually_exclusive_flags(self):
        parser = ct.create_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "36.3:36.4,25.3:25.4",
                    "T",
                    "--mintpy-plot",
                    "--mintpy-no-plot",
                ]
            )

    def test_mintpy_no_plot_sets_const(self):
        parser = ct.create_parser()
        inps = parser.parse_args(
            ["36.3:36.4,25.3:25.4", "T", "--mintpy-no-plot"]
        )
        self.assertEqual(inps.mintpy_plot_cli, "no")


if __name__ == "__main__":
    unittest.main()
