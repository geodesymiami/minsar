#!/usr/bin/env python3
"""Unit tests for reference_point_hdfeos5 (in-memory HE5 re-reference)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

# Allow importing from minsar/utils when not installed as a package module.
UTILS = Path(__file__).resolve().parents[1]
if str(UTILS) not in sys.path:
    sys.path.insert(0, str(UTILS))

import reference_point_hdfeos5 as mod  # noqa: E402


DISP = "HDFEOS/GRIDS/timeseries/observation/displacement"


def _write_geo_he5(path, n_dates=3, length=5, width=6):
    """Minimal GEO HE5 with known displacement and REF_* attrs."""
    y_first = 10.0
    x_first = 20.0
    y_step = -0.1
    x_step = 0.1
    # Pixel (2, 3) → lat = 10 + 2*(-0.1) = 9.8, lon = 20 + 3*0.1 = 20.3
    data = np.zeros((n_dates, length, width), dtype=np.float32)
    for i in range(n_dates):
        data[i] = float(i + 1)
        data[i, 2, 3] = 100.0 + i  # ref pixel value before re-ref
        data[i, 0, 0] = 50.0 + i

    with h5py.File(path, "w") as f:
        f.attrs["Y_FIRST"] = str(y_first)
        f.attrs["X_FIRST"] = str(x_first)
        f.attrs["Y_STEP"] = str(y_step)
        f.attrs["X_STEP"] = str(x_step)
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        f.attrs["REF_Y"] = "0"
        f.attrs["REF_X"] = "0"
        f.attrs["REF_LAT"] = "10.0"
        f.attrs["REF_LON"] = "20.0"
        f.attrs["FILE_TYPE"] = "HDFEOS"
        grp = f.create_group("HDFEOS/GRIDS/timeseries/observation")
        grp.create_dataset("displacement", data=data, chunks=True)
        dates = np.array([b"20200101", b"20200113", b"20200125"], dtype="S8")
        grp.create_dataset("date", data=dates[:n_dates])
    return 9.8, 20.3  # lat, lon of pixel (2, 3)


class TestParseRefLalo(unittest.TestCase):
    def test_space_separated(self):
        self.assertEqual(mod.parse_ref_lalo(["1.5", "-90.1"]), (1.5, -90.1))

    def test_comma_separated(self):
        self.assertEqual(mod.parse_ref_lalo(["1.5,-90.1"]), (1.5, -90.1))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            mod.parse_ref_lalo(["1.5"])


class TestReferencePointHdfeos5Geo(unittest.TestCase):
    def test_zero_at_ref_and_attrs_same_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            he5 = os.path.join(tmp, "geo_test.he5")
            lat, lon = _write_geo_he5(he5)
            out = mod.reference_point_hdfeos5(he5, lat, lon, force=True)
            self.assertEqual(out, os.path.abspath(he5))
            self.assertEqual(os.path.basename(out), "geo_test.he5")

            with h5py.File(he5, "r") as f:
                ds = f[DISP]
                for i in range(ds.shape[0]):
                    self.assertAlmostEqual(float(ds[i, 2, 3]), 0.0, places=5)
                    # former (0,0) was 50+i; ref was 100+i → 50+i - (100+i) = -50
                    self.assertAlmostEqual(float(ds[i, 0, 0]), -50.0, places=5)
                self.assertEqual(str(f.attrs["REF_Y"]), "2")
                self.assertEqual(str(f.attrs["REF_X"]), "3")
                self.assertEqual(str(f.attrs["REF_LAT"]), str(lat))
                self.assertEqual(str(f.attrs["REF_LON"]), str(lon))

    def test_output_copies_to_new_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            he5 = os.path.join(tmp, "geo_test.he5")
            lat, lon = _write_geo_he5(he5)
            out_path = os.path.join(tmp, "geo_out.he5")
            out = mod.reference_point_hdfeos5(he5, lat, lon, outfile=out_path, force=True)
            self.assertEqual(out, os.path.abspath(out_path))
            with h5py.File(out_path, "r") as f:
                self.assertAlmostEqual(float(f[DISP][0, 2, 3]), 0.0, places=5)
            # Original unchanged at ref pixel
            with h5py.File(he5, "r") as f:
                self.assertAlmostEqual(float(f[DISP][0, 2, 3]), 100.0, places=5)

    def test_lalo_to_yx_geo(self):
        meta = {
            "Y_FIRST": "10.0",
            "X_FIRST": "20.0",
            "Y_STEP": "-0.1",
            "X_STEP": "0.1",
            "LENGTH": "5",
            "WIDTH": "6",
        }
        y, x = mod.lalo_to_yx_geo(meta, 9.8, 20.3)
        self.assertEqual((y, x), (2, 3))

    def test_lalo_to_yx_radar_uses_geo2radar(self):
        """Radar lat/lon must use geo2radar (lalo2yx raises NOT geocoded)."""
        from unittest.mock import MagicMock, patch

        meta = {"LENGTH": "100", "WIDTH": "200", "FILE_TYPE": "timeseries"}
        fake_coord = MagicMock()
        fake_coord.geo2radar.return_value = (np.array([10]), np.array([20]), 0)
        with patch("mintpy.utils.utils.coordinate", return_value=fake_coord):
            y, x = mod.lalo_to_yx_radar(meta, 37.77, 15.15, "/fake/geometryRadar.h5")
        self.assertEqual((y, x), (10, 20))
        fake_coord.geo2radar.assert_called_once()
        fake_coord.lalo2yx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
