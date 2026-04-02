#!/usr/bin/env python3
"""Tests for insarmaps_csv_geo and CSV paths in footprint helpers."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "insarmaps_utils"))

from insarmaps_csv_geo import csv_lat_lon_spans, csv_mean_lat_lon


class TestInsarmapsCsvGeo(unittest.TestCase):
    def test_mean_lat_lon(self):
        lines = [
            "Latitude,Longitude,D20180101",
            "10.0,-80.0,1",
            "10.2,-80.1,2",
            "10.4,-80.2,3",
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        try:
            ml, mo = csv_mean_lat_lon(path)
            self.assertAlmostEqual(ml, 10.2)
            self.assertAlmostEqual(mo, -80.1)
            ls, xs = csv_lat_lon_spans(path)
            self.assertAlmostEqual(ls, 0.4)
            self.assertAlmostEqual(xs, 0.2)
        finally:
            os.unlink(path)

    def test_get_center_coords_csv(self):
        try:
            import h5py  # noqa: F401 — get_data_footprint_centroid imports it at module load
        except ImportError:
            self.skipTest("h5py not installed")
        from get_data_footprint_centroid import get_center_coords

        lines = [
            "Y,X,D20180101",
            "1.0,2.0,0",
            "3.0,4.0,0",
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        try:
            la, lo = get_center_coords(path, decimals=4)
            self.assertEqual(la, "2.0000")
            self.assertEqual(lo, "3.0000")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
