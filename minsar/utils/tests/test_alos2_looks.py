#!/usr/bin/env python3
"""Tests for alos2Stack.rangeLooks / azimuthLooks -> alosStack.xml look properties (ScanSAR)."""

import unittest

from minsar.utils.stack_run import _alos2_look_properties


class TestAlos2Looks(unittest.TestCase):
    def test_auto_writes_nothing(self):
        self.assertEqual(_alos2_look_properties({}), {})
        self.assertEqual(_alos2_look_properties({"alos2Stack.rangeLooks": "auto", "alos2Stack.azimuthLooks": "auto"}), {})

    def test_isce_default(self):
        self.assertEqual(
            _alos2_look_properties({"alos2Stack.rangeLooks": "5", "alos2Stack.azimuthLooks": "28"}),
            {"number of range looks 1": 1, "number of azimuth looks 1": 14, "number of range looks 2": 5, "number of azimuth looks 2": 2},
        )

    def test_finer_pixel(self):
        props = _alos2_look_properties({"alos2Stack.rangeLooks": "2", "alos2Stack.azimuthLooks": "14"})
        self.assertEqual((props["number of range looks 2"], props["number of azimuth looks 2"]), (2, 1))

    def test_errors(self):
        for template in (
            {"alos2Stack.rangeLooks": "5", "alos2Stack.azimuthLooks": "30"},
            {"alos2Stack.rangeLooks": "5"},
            {"alos2Stack.rangeLooks": "five", "alos2Stack.azimuthLooks": "28"},
            {"alos2Stack.rangeLooks": "0", "alos2Stack.azimuthLooks": "28"},
        ):
            with self.assertRaises(RuntimeError, msg=template):
                _alos2_look_properties(template)


if __name__ == "__main__":
    unittest.main()
