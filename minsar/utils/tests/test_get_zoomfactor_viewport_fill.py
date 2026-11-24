#!/usr/bin/env python3
"""Tests for get_zoomfactor_from_data_footprint viewport-fill behavior."""

import importlib.util
import math
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / 'get_zoomfactor_from_data_footprint.py'


def _load():
    spec = importlib.util.spec_from_file_location('gzf', _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mercator_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi)


class TestViewportFill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_larger_viewport_fill_yields_higher_zoom(self):
        z_small = self.m.zoom_for_bounds(37.0, 37.8, 15.0, 15.5, viewport_fill=0.5)
        z_large = self.m.zoom_for_bounds(37.0, 37.8, 15.0, 15.5, viewport_fill=1.0)
        self.assertAlmostEqual(z_large - z_small, 1.0)

    def test_wide_box_covers_three_quarters_of_width(self):
        zoom = self.m.zoom_for_bounds(37.0, 37.1, 15.0, 16.0, width=1148, height=802)
        box_px = (1.0 / 360.0) * 512 * 2 ** zoom
        self.assertAlmostEqual(box_px / 1148, 0.75)

    def test_tall_box_covers_three_quarters_of_height(self):
        zoom = self.m.zoom_for_bounds(37.0, 38.0, 15.0, 15.1, width=1148, height=802)
        box_px = (_mercator_y(38.0) - _mercator_y(37.0)) * 512 * 2 ** zoom
        self.assertAlmostEqual(box_px / 802, 0.75)

    def test_zoom_is_clamped(self):
        self.assertEqual(self.m.zoom_for_bounds(-60, 60, -170, 170, min_zoom=3, max_zoom=18), 3)
        self.assertEqual(self.m.zoom_for_bounds(37.0, 37.00001, 15.0, 15.00001, min_zoom=3, max_zoom=18), 18)

    def test_degenerate_input_returns_mid_zoom(self):
        self.assertEqual(self.m.zoom_for_bounds(37.0, 37.5, 15.0, 15.5, viewport_fill=0.0, min_zoom=8, max_zoom=15), 11.5)
        self.assertEqual(self.m.zoom_for_bounds(37.0, 37.0, 15.0, 15.0, min_zoom=8, max_zoom=15), 11.5)

    def test_wkt_polygon_bounds(self):
        bounds = self.m.wkt_polygon_bounds('POLYGON((15.0 37.0,15.5 37.0,15.5 37.8,15.0 37.8,15.0 37.0))')
        self.assertEqual(bounds, (37.0, 37.8, 15.0, 15.5))
        self.assertIsNone(self.m.wkt_polygon_bounds(''))
        self.assertIsNone(self.m.wkt_polygon_bounds(None))


if __name__ == '__main__':
    unittest.main()
