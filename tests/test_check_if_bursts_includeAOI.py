"""Tests for check_if_bursts_includeAOI.py helpers and CLI."""

import importlib.util
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / 'minsar' / 'scripts' / 'check_if_bursts_includeAOI.py'


def _load():
    spec = importlib.util.spec_from_file_location('_cbc', _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBboxAndCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_bbox_sn_we_negative_lat(self):
        poly = self.m.bbox_sn_we_to_polygon('-8.302:-8.235,123.491:123.543')
        self.assertAlmostEqual(poly.bounds[0], 123.491)
        self.assertAlmostEqual(poly.bounds[1], -8.302)
        self.assertAlmostEqual(poly.bounds[2], 123.543)
        self.assertAlmostEqual(poly.bounds[3], -8.235)

    def test_bbox_reversed_order_ok(self):
        a = self.m.bbox_sn_we_to_polygon('-8.235:-8.302,123.543:123.491').bounds
        b = self.m.bbox_sn_we_to_polygon('-8.302:-8.235,123.491:123.543').bounds
        self.assertEqual(a, b)

    def test_main_needs_bbox_and_paths(self):
        self.assertEqual(self.m.main([]), 2)
        self.assertEqual(self.m.main(['-8:0,1:2']), 2)

    def test_main_rejects_unknown_dash_token(self):
        self.assertEqual(self.m.main(['--foo', 'a', 'b']), 2)

    def test_acquisition_date_from_burst_name(self):
        self.assertEqual(
            self.m.acquisition_date_yyyymmdd_from_burst_filename(
                'S1A_IW_SLC__1SDV_20141109T212806_B823_IW1_burst.tif'
            ),
            '20141109',
        )
        self.assertIsNone(self.m.acquisition_date_yyyymmdd_from_burst_filename('no_date_here.tif'))

    def test_common_parent_single_dir(self):
        p = Path('/a/b/c.tif')
        self.assertEqual(self.m._common_parent_dir([p]), Path('/a/b'))


if __name__ == '__main__':
    unittest.main()
