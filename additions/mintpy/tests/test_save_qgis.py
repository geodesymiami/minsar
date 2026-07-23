#!/usr/bin/env python3
"""Unit tests for MinSAR-patched save_qgis (HDFEOS + estimated velocity + mask)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

_TOOLS_MINTPY = Path(__file__).resolve().parents[3] / "tools" / "MintPy" / "src"
if _TOOLS_MINTPY.is_dir():
    import sys
    sys.path.insert(0, str(_TOOLS_MINTPY))

try:
    import h5py
    from mintpy.cli import save_qgis as save_qgis_cli
    from mintpy.save_qgis import (
        estimate_velocity_mintpy_default,
        gather_files,
        get_ts_date_list,
        resolve_lat_lon,
        resolve_mask,
        write_vector_file,
    )
    HAS_MINTPY = True
except Exception as exc:  # pragma: no cover
    HAS_MINTPY = False
    _IMPORT_ERR = exc


def _geo_attrs(f, length, width):
    f.attrs["LENGTH"] = str(length)
    f.attrs["WIDTH"] = str(width)
    f.attrs["Y_FIRST"] = "10.0"
    f.attrs["X_FIRST"] = "20.0"
    f.attrs["Y_STEP"] = "-0.001"
    f.attrs["X_STEP"] = "0.001"
    f.attrs["Y_UNIT"] = "degrees"
    f.attrs["X_UNIT"] = "degrees"
    f.attrs["REF_Y"] = "0"
    f.attrs["REF_X"] = "0"


def _write_geo_timeseries(path: Path, dates, cube, *, unit="m"):
    length, width = cube.shape[1], cube.shape[2]
    with h5py.File(path, "w") as f:
        f.create_dataset("date", data=np.array(dates, dtype="S8"))
        f.create_dataset("timeseries", data=cube.astype(np.float32))
        f.create_dataset("bperp", data=np.zeros(len(dates), dtype=np.float32))
        f.attrs["FILE_TYPE"] = "timeseries"
        f.attrs["UNIT"] = unit
        f.attrs["REF_DATE"] = dates[0]
        _geo_attrs(f, length, width)


def _write_geo_hdfeos(path: Path, dates, cube, mask=None, *, with_latlon=False):
    length, width = cube.shape[1], cube.shape[2]
    with h5py.File(path, "w") as f:
        f.attrs["FILE_TYPE"] = "HDFEOS"
        f.attrs["UNIT"] = "m"
        f.attrs["REF_DATE"] = dates[0]
        _geo_attrs(f, length, width)
        obs = f.create_group("HDFEOS/GRIDS/timeseries/observation")
        obs.create_dataset("date", data=np.array(dates, dtype="S8"))
        obs.create_dataset("bperp", data=np.zeros(len(dates), dtype=np.float32))
        obs.create_dataset("displacement", data=cube.astype(np.float32))
        qual = f.create_group("HDFEOS/GRIDS/timeseries/quality")
        if mask is None:
            mask = np.ones((length, width), dtype=bool)
        qual.create_dataset("mask", data=mask.astype(bool))
        qual.create_dataset("temporalCoherence", data=np.ones((length, width), np.float32) * 0.9)
        geom = f.create_group("HDFEOS/GRIDS/timeseries/geometry")
        geom.create_dataset("height", data=np.full((length, width), 100.0, np.float32))
        if with_latlon:
            # simple geo grid matching Y_FIRST/X_FIRST
            lats = np.zeros((length, width), np.float32)
            lons = np.zeros((length, width), np.float32)
            for i in range(length):
                for j in range(width):
                    lats[i, j] = 10.0 + (-0.001) * (i + 0.5)
                    lons[i, j] = 20.0 + (0.001) * (j + 0.5)
            geom.create_dataset("latitude", data=lats)
            geom.create_dataset("longitude", data=lons)


def _write_radar_hdfeos(path: Path, dates, cube, mask=None):
    """Radar-coded HE5: no Y_FIRST; has latitude/longitude datasets."""
    length, width = cube.shape[1], cube.shape[2]
    with h5py.File(path, "w") as f:
        f.attrs["FILE_TYPE"] = "HDFEOS"
        f.attrs["UNIT"] = "m"
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        f.attrs["REF_DATE"] = dates[0]
        obs = f.create_group("HDFEOS/GRIDS/timeseries/observation")
        obs.create_dataset("date", data=np.array(dates, dtype="S8"))
        obs.create_dataset("bperp", data=np.zeros(len(dates), dtype=np.float32))
        obs.create_dataset("displacement", data=cube.astype(np.float32))
        qual = f.create_group("HDFEOS/GRIDS/timeseries/quality")
        if mask is None:
            mask = np.ones((length, width), dtype=bool)
        qual.create_dataset("mask", data=mask.astype(bool))
        qual.create_dataset("temporalCoherence", data=np.ones((length, width), np.float32))
        geom = f.create_group("HDFEOS/GRIDS/timeseries/geometry")
        geom.create_dataset("height", data=np.zeros((length, width), np.float32))
        lats = np.full((length, width), 35.0, np.float32)
        lons = np.full((length, width), 25.0, np.float32)
        for j in range(width):
            lons[:, j] = 25.0 + 0.01 * j
        for i in range(length):
            lats[i, :] = 35.0 + 0.01 * i
        geom.create_dataset("latitude", data=lats)
        geom.create_dataset("longitude", data=lons)


def _write_geometry(path: Path, length, width, *, geo=True):
    with h5py.File(path, "w") as f:
        f.create_dataset("height", data=np.zeros((length, width), np.float32))
        f.attrs["FILE_TYPE"] = "geometry"
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        if geo:
            _geo_attrs(f, length, width)
        else:
            f.create_dataset("latitude", data=np.full((length, width), 35.0, np.float32))
            f.create_dataset("longitude", data=np.full((length, width), 25.0, np.float32))


def _write_coherence(path: Path, length, width):
    with h5py.File(path, "w") as f:
        f.create_dataset("temporalCoherence", data=np.ones((length, width), np.float32))
        f.attrs["FILE_TYPE"] = "temporalCoherence"
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        _geo_attrs(f, length, width)


def _write_mask(path: Path, mask):
    length, width = mask.shape
    with h5py.File(path, "w") as f:
        f.create_dataset("mask", data=mask.astype(np.bool_))
        f.attrs["FILE_TYPE"] = "mask"
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        _geo_attrs(f, length, width)


@unittest.skipUnless(HAS_MINTPY, f"mintpy/h5py unavailable: {_IMPORT_ERR if not HAS_MINTPY else ''}")
class TestSaveQgisHdfeos(unittest.TestCase):
    def test_cli_accepts_hdfeos_without_geom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 3, 4), dtype=np.float32)
            cube[1] = 0.01
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            inps = save_qgis_cli.cmd_line_parse([str(he5)])
            self.assertEqual(inps.ts_file, str(he5))
            self.assertTrue(inps.out_file.endswith(".gpkg"))
            self.assertFalse(inps.no_gpkg)

    def test_cli_no_gpkg_defaults_to_shp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 2, 2), dtype=np.float32)
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            inps = save_qgis_cli.cmd_line_parse([str(he5), "--no-gpkg"])
            self.assertTrue(inps.no_gpkg)
            self.assertTrue(inps.out_file.endswith(".shp"))

    def test_cli_o_shp_implies_no_gpkg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 2, 2), dtype=np.float32)
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            out = root / "custom.shp"
            inps = save_qgis_cli.cmd_line_parse([str(he5), "-o", str(out)])
            self.assertTrue(inps.no_gpkg)
            self.assertEqual(inps.out_file, str(out))

    def test_cli_requires_geom_for_timeseries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 2, 2), dtype=np.float32)
            ts = root / "timeseries.h5"
            _write_geo_timeseries(ts, dates, cube)
            with self.assertRaises(Exception):
                save_qgis_cli.cmd_line_parse([str(ts)])

    def test_get_date_list_hdfeos(self):
        with tempfile.TemporaryDirectory() as tmp:
            he5 = Path(tmp) / "p.he5"
            dates = ["20190101", "20190201", "20190301"]
            cube = np.zeros((3, 2, 2), dtype=np.float32)
            _write_geo_hdfeos(he5, dates, cube)
            self.assertEqual(get_ts_date_list(str(he5)), dates)

    def test_resolve_mask_from_hdfeos(self):
        with tempfile.TemporaryDirectory() as tmp:
            he5 = Path(tmp) / "p.he5"
            dates = ["20200101", "20210101"]
            cube = np.ones((2, 2, 2), dtype=np.float32)
            mask = np.array([[True, False], [True, True]])
            _write_geo_hdfeos(he5, dates, cube, mask=mask)
            got, src = resolve_mask(str(he5))
            np.testing.assert_array_equal(got, mask)
            self.assertEqual(src, str(he5))

    def test_estimate_velocity_prints_equivalent_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 3, 4), dtype=np.float32)
            cube[1] = 0.02
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            with mock.patch("builtins.print") as mprint:
                data = estimate_velocity_mintpy_default(str(he5))
            printed = "\n".join(str(c.args[0]) for c in mprint.call_args_list if c.args)
            self.assertIn("timeseries2velocity.py", printed)
            self.assertIn(str(he5), printed)
            np.testing.assert_allclose(data, 0.02, atol=1e-5)

    def test_gather_files_hdfeos_no_velocity_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.ones((2, 2, 2), dtype=np.float32)
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            fDict = gather_files(str(he5))
            self.assertIsNone(fDict["Velocity"])
            self.assertEqual(fDict["TimeSeries"], str(he5))
            self.assertEqual(fDict["Mask"], str(he5))
            self.assertEqual(fDict["Coherence"], str(he5))
            self.assertEqual(fDict["Geometry"], str(he5))

    def test_resolve_lat_lon_radar_hdfeos(self):
        with tempfile.TemporaryDirectory() as tmp:
            he5 = Path(tmp) / "radar.he5"
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 2, 3), dtype=np.float32)
            _write_radar_hdfeos(he5, dates, cube)
            from mintpy.utils import readfile
            atr = readfile.read_attribute(str(he5))
            self.assertNotIn("Y_FIRST", atr)
            lats, lons = resolve_lat_lon(atr, str(he5), box=(0, 0, 3, 2))
            self.assertEqual(lats.shape, (2, 3))
            self.assertTrue(np.all(np.isfinite(lats)))
            self.assertTrue(np.all(np.isfinite(lons)))

    def test_write_gpkg_applies_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 2, 3), dtype=np.float32)
            cube[1] = 0.01
            mask = np.array([[True, False, True], [False, True, False]])
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube, mask=mask)
            fDict = gather_files(str(he5))
            gpkg = root / "out.gpkg"
            write_vector_file(fDict, str(gpkg), box=(0, 0, 3, 2))
            self.assertTrue(gpkg.is_file())
            from osgeo import ogr
            ds = ogr.Open(str(gpkg))
            layer = ds.GetLayer(0)
            self.assertEqual(layer.GetFeatureCount(), int(np.sum(mask)))

    def test_write_shape_file_applies_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 2, 3), dtype=np.float32)
            cube[1] = 0.01
            mask = np.array([[True, False, True], [False, True, False]])
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube, mask=mask)
            fDict = gather_files(str(he5))
            shp = root / "out.shp"
            write_vector_file(fDict, str(shp), box=(0, 0, 3, 2))
            self.assertTrue(shp.is_file())
            # count features via ogr
            from osgeo import ogr
            ds = ogr.Open(str(shp))
            layer = ds.GetLayer(0)
            self.assertEqual(layer.GetFeatureCount(), int(np.sum(mask)))


if __name__ == "__main__":
    unittest.main()
