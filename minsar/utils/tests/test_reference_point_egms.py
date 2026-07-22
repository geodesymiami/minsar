#!/usr/bin/env python3
"""Unit tests for reference_point_egms (EGMS CSV re-reference)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

UTILS = Path(__file__).resolve().parents[1]
if str(UTILS) not in sys.path:
    sys.path.insert(0, str(UTILS))

import reference_point_egms as mod  # noqa: E402


def _write_sample_csv(path, ref_lat=37.80455, ref_lon=15.17508):
    df = pd.DataFrame(
        {
            "pid": [1, 2, 3],
            "latitude": [ref_lat + 0.001, ref_lat + 0.01, ref_lat - 0.02],
            "longitude": [ref_lon + 0.001, ref_lon + 0.01, ref_lon - 0.02],
            "20200104": [10.0, 20.0, 30.0],
            "20200110": [11.0, 21.0, 31.0],
            "20200116": [12.0, 22.0, 32.0],
        }
    )
    df.to_csv(path, index=False)
    return df


class TestParseRefLalo(unittest.TestCase):
    def test_space_separated(self):
        self.assertEqual(mod.parse_ref_lalo(["37.8", "15.17"]), (37.8, 15.17))

    def test_comma_separated(self):
        self.assertEqual(mod.parse_ref_lalo(["37.8,15.17"]), (37.8, 15.17))


class TestFindReferenceRow(unittest.TestCase):
    def test_nearest_within_radius(self):
        lats = [37.81, 37.80456, 37.90]
        lons = [15.18, 15.17509, 15.20]
        idx, dist = mod.find_reference_row(lats, lons, 37.80455, 15.17508, 500.0)
        self.assertEqual(idx, 1)
        self.assertLess(dist, 20.0)

    def test_raises_when_outside_radius(self):
        lats = [38.0, 38.01]
        lons = [16.0, 16.01]
        with self.assertRaises(ValueError) as ctx:
            mod.find_reference_row(lats, lons, 37.80455, 15.17508, 100.0)
        self.assertIn("No CSV point within", str(ctx.exception))


class TestReferencePointEgms(unittest.TestCase):
    def test_zero_at_ref_and_in_place(self):
        ref_lat, ref_lon = 37.80455, 15.17508
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "egms_test.csv")
            _write_sample_csv(csv_path, ref_lat, ref_lon)
            out = mod.reference_point_egms(
                csv_path, ref_lat, ref_lon, search_radius_m=500.0, force=True
            )
            self.assertEqual(out, os.path.abspath(csv_path))
            df = pd.read_csv(csv_path)
            ref_row = mod.find_reference_row(
                df["latitude"], df["longitude"], ref_lat, ref_lon, 500.0
            )[0]
            for col in ("20200104", "20200110", "20200116"):
                self.assertAlmostEqual(float(df.loc[ref_row, col]), 0.0, places=6)
            self.assertAlmostEqual(float(df.loc[1, "20200104"]), 10.0, places=6)

    def test_output_file(self):
        ref_lat, ref_lon = 37.80455, 15.17508
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.csv")
            dst = os.path.join(tmp, "out.csv")
            _write_sample_csv(src, ref_lat, ref_lon)
            mod.reference_point_egms(
                src, ref_lat, ref_lon, search_radius_m=500.0, outfile=dst, force=True
            )
            self.assertTrue(os.path.isfile(dst))
            orig = pd.read_csv(src)
            self.assertAlmostEqual(float(orig.loc[0, "20200104"]), 10.0, places=6)


if __name__ == "__main__":
    unittest.main()
