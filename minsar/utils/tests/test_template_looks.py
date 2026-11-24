#!/usr/bin/env python3
"""Tests for minsar.utils.template_looks (looks options of minsarApp.bash and create_template.py)."""

import argparse
import unittest

from minsar.utils import template_looks as tl

S1 = (
    "ssaraopt.platform = SENTINEL-1A,SENTINEL-1B\n"
    "topsStack.azimuthLooks          = 5    # comment\n"
    "topsStack.rangeLooks            = 15   # comment\n"
)
ALOS2 = (
    "ssaraopt.platform                    = ALOS2  #[ALOS2 / ALOS-2]\n"
    "alos2Stack.rangeLooks                = auto  #[int], final range looks\n"
    "alos2Stack.azimuthLooks              = auto  #[multiple of 14]\n"
)


class TestTemplateLooks(unittest.TestCase):
    def test_all_spellings_parse(self):
        parser = argparse.ArgumentParser(allow_abbrev=False)
        tl.add_looks_arguments(parser)
        for option in tl.RANGE_OPTIONS:
            self.assertEqual(parser.parse_args([option, "20"]).range_looks, 20, msg=option)
        for option in tl.AZIMUTH_OPTIONS:
            self.assertEqual(parser.parse_args([option, "5"]).azimuth_looks, 5, msg=option)

    def test_sentinel_keeps_comment_and_other_value(self):
        out, changed = tl.set_looks_in_template_text(S1, range_looks=20)
        self.assertEqual(changed, {"topsStack.rangeLooks": 20})
        self.assertIn("topsStack.rangeLooks            = 20   # comment\n", out)
        self.assertIn("topsStack.azimuthLooks          = 5    # comment\n", out)

    def test_missing_key_is_appended(self):
        out, _ = tl.set_looks_in_template_text("ssaraopt.platform = SENTINEL-1A\n", range_looks=20, azimuth_looks=5)
        self.assertIn("topsStack.rangeLooks = 20\n", out)
        self.assertIn("topsStack.azimuthLooks = 5\n", out)

    def test_alos2_both(self):
        out, changed = tl.set_looks_in_template_text(ALOS2, range_looks=2, azimuth_looks=14)
        self.assertEqual(changed, {"alos2Stack.rangeLooks": 2, "alos2Stack.azimuthLooks": 14})
        self.assertIn("alos2Stack.rangeLooks                = 2  #[int], final range looks\n", out)

    def test_alos2_one_given_completes_the_pair(self):
        _, changed = tl.set_looks_in_template_text(ALOS2, range_looks=20)
        self.assertEqual(changed, {"alos2Stack.rangeLooks": 20, "alos2Stack.azimuthLooks": 28})
        _, changed = tl.set_looks_in_template_text(ALOS2, azimuth_looks=14)
        self.assertEqual(changed, {"alos2Stack.rangeLooks": 5, "alos2Stack.azimuthLooks": 14})

    def test_alos2_azimuth_multiple_of_14(self):
        with self.assertRaises(ValueError):
            tl.set_looks_in_template_text(ALOS2, azimuth_looks=20)

    def test_values_below_one_raise(self):
        with self.assertRaises(ValueError):
            tl.set_looks_in_template_text(S1, range_looks=0)

    def test_wrong_sensor_spelling(self):
        with self.assertRaises(ValueError):
            tl.check_option_spellings(["--topsStack.rangeLooks", "20"], tl.stack_prefix(ALOS2))
        with self.assertRaises(ValueError):
            tl.check_option_spellings(["--alos2Stack.azimuthLooks=28"], tl.stack_prefix(S1))
        tl.check_option_spellings(["--rangeLooks", "20", "--azimuth-looks", "5"], tl.stack_prefix(ALOS2))
        tl.check_option_spellings(["--topsStack.rangeLooks", "20"], tl.stack_prefix(S1))

    def test_stripmap_prefix(self):
        self.assertEqual(tl.stack_prefix("ssaraopt.platform = TSX\nstripmapStack.rangeLooks = 10\n"), "stripmapStack")


if __name__ == "__main__":
    unittest.main()
