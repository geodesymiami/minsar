#!/usr/bin/env python3
"""Tests for get_zoomfactor_from_data_footprint viewport-fill behavior."""

import importlib.util
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / 'get_zoomfactor_from_data_footprint.py'


def _load():
    spec = importlib.util.spec_from_file_location('gzf', _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestViewportFill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_smaller_viewport_fill_yields_higher_zoom(self):
        z_full = self.m.calculate_zoom_from_extent(0.8, 0.5, viewport_fill=1.0)
        z_tight = self.m.calculate_zoom_from_extent(0.8, 0.5, viewport_fill=0.6)
        self.assertGreater(z_tight, z_full)

    def test_invalid_viewport_fill_returns_mid_zoom(self):
        z = self.m.calculate_zoom_from_extent(0.5, 0.5, viewport_fill=0.0)
        self.assertEqual(z, 11.5)


if __name__ == '__main__':
    unittest.main()
