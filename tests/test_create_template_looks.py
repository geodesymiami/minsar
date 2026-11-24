#!/usr/bin/env python3
"""Tests for the looks options of create_template.py and their routing in minsarApp AOI mode."""
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from minsar.scripts.create_template import create_parser  # noqa: E402
from minsar.utils.template_looks import AZIMUTH_OPTIONS, RANGE_OPTIONS  # noqa: E402

_AOI = "36.331:36.486,25.318:25.492"


class TestCreateTemplateLooks(unittest.TestCase):
    def test_parser_accepts_every_spelling(self):
        for option in RANGE_OPTIONS:
            self.assertEqual(create_parser().parse_args([_AOI, "T", option, "20"]).range_looks, 20, msg=option)
        for option in AZIMUTH_OPTIONS:
            self.assertEqual(create_parser().parse_args([_AOI, "T", option, "5"]).azimuth_looks, 5, msg=option)

    def test_default_is_none(self):
        inps = create_parser().parse_args([_AOI, "T"])
        self.assertIsNone(inps.range_looks)
        self.assertIsNone(inps.azimuth_looks)

    def test_aoi_mode_sends_looks_to_create_template(self):
        from minsar.scripts import minsarapp_aoi_entry as entry
        argv = [_AOI, "T", "--range-looks", "20", "--topsStack.azimuthLooks", "5", "--start", "mintpy"]
        ct_list, rest = entry.partition_aoi_bridge_argv(argv)[:2]
        for token in ("--range-looks", "20", "--topsStack.azimuthLooks", "5"):
            self.assertIn(token, ct_list)
            self.assertNotIn(token, rest)
        self.assertIn("--start", rest)


if __name__ == "__main__":
    unittest.main()
