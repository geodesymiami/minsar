#!/usr/bin/env python3
"""Unit tests for MinSAR-patched save_explorer (HDFEOS + geo_velocity resolve)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

# Ensure additions MintPy patches are importable via tools/MintPy when installed.
_TOOLS_MINTPY = Path(__file__).resolve().parents[3] / "tools" / "MintPy" / "src"
if _TOOLS_MINTPY.is_dir():
    import sys
    sys.path.insert(0, str(_TOOLS_MINTPY))

try:
    import h5py
    from mintpy.cli import save_explorer as save_explorer_cli
    from mintpy.save_explorer import (
        estimate_velocity_mintpy_default,
        find_geo_velocity_file,
        get_ts_date_list,
        resolve_mask,
        resolve_velocity,
        save_explorer,
    )
    HAS_MINTPY = True
except Exception as exc:  # pragma: no cover
    HAS_MINTPY = False
    _IMPORT_ERR = exc


def _write_geo_timeseries(path: Path, dates, cube, *, unit="m"):
    """Write a minimal MintPy timeseries.h5 in geographic coordinates."""
    length, width = cube.shape[1], cube.shape[2]
    with h5py.File(path, "w") as f:
        f.create_dataset("date", data=np.array(dates, dtype="S8"))
        f.create_dataset("timeseries", data=cube.astype(np.float32))
        f.create_dataset("bperp", data=np.zeros(len(dates), dtype=np.float32))
        f.attrs["FILE_TYPE"] = "timeseries"
        f.attrs["UNIT"] = unit
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        f.attrs["Y_FIRST"] = "10.0"
        f.attrs["X_FIRST"] = "20.0"
        f.attrs["Y_STEP"] = "-0.001"
        f.attrs["X_STEP"] = "0.001"
        f.attrs["REF_Y"] = "0"
        f.attrs["REF_X"] = "0"
        f.attrs["REF_DATE"] = dates[0]


def _write_geo_hdfeos(path: Path, dates, cube, mask=None):
    """Write a minimal geocoded HDFEOS .he5 with quality/mask."""
    length, width = cube.shape[1], cube.shape[2]
    with h5py.File(path, "w") as f:
        f.attrs["FILE_TYPE"] = "HDFEOS"
        f.attrs["UNIT"] = "m"
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        f.attrs["Y_FIRST"] = "10.0"
        f.attrs["X_FIRST"] = "20.0"
        f.attrs["Y_STEP"] = "-0.001"
        f.attrs["X_STEP"] = "0.001"
        f.attrs["REF_Y"] = "0"
        f.attrs["REF_X"] = "0"
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


def _write_velocity(path: Path, vel, *, length=None, width=None):
    length = length or vel.shape[0]
    width = width or vel.shape[1]
    with h5py.File(path, "w") as f:
        f.create_dataset("velocity", data=vel.astype(np.float32))
        f.attrs["FILE_TYPE"] = "velocity"
        f.attrs["UNIT"] = "m/year"
        f.attrs["LENGTH"] = str(length)
        f.attrs["WIDTH"] = str(width)
        f.attrs["Y_FIRST"] = "10.0"
        f.attrs["X_FIRST"] = "20.0"
        f.attrs["Y_STEP"] = "-0.001"
        f.attrs["X_STEP"] = "0.001"


@unittest.skipUnless(HAS_MINTPY, f"mintpy/h5py unavailable: {_IMPORT_ERR if not HAS_MINTPY else ''}")
class TestSaveExplorerHdfeos(unittest.TestCase):
    def test_cli_accepts_hdfeos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            # 0.01 m over 1 year → 0.01 m/year
            cube = np.zeros((2, 3, 4), dtype=np.float32)
            cube[1] = 0.01
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            inps = save_explorer_cli.cmd_line_parse([str(he5), "-o", str(root / "out")])
            self.assertEqual(inps.ts_file, str(he5))

    def test_cli_rejects_radar_hdfeos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            he5 = root / "radar.he5"
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 2, 2), dtype=np.float32)
            _write_geo_hdfeos(he5, dates, cube)
            # strip geo attrs
            with h5py.File(he5, "a") as f:
                for k in ("Y_FIRST", "X_FIRST", "Y_STEP", "X_STEP"):
                    if k in f.attrs:
                        del f.attrs[k]
            with self.assertRaises(Exception):
                save_explorer_cli.cmd_line_parse([str(he5)])

    def test_get_date_list_hdfeos(self):
        with tempfile.TemporaryDirectory() as tmp:
            he5 = Path(tmp) / "p.he5"
            dates = ["20190101", "20190201", "20190301"]
            cube = np.zeros((3, 2, 2), dtype=np.float32)
            _write_geo_hdfeos(he5, dates, cube)
            self.assertEqual(get_ts_date_list(str(he5)), dates)

    def test_prefer_geo_velocity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 3, 4), dtype=np.float32)
            cube[1] = 0.05
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            geo = root / "geo"
            geo.mkdir()
            vel = np.full((3, 4), 0.123, dtype=np.float32)
            _write_velocity(geo / "geo_velocity.h5", vel)
            self.assertEqual(
                find_geo_velocity_file(str(he5)),
                str((geo / "geo_velocity.h5").resolve()),
            )
            data, atr, src = resolve_velocity(str(he5))
            self.assertTrue(str(src).endswith("geo_velocity.h5"))
            np.testing.assert_allclose(data, vel)

    def test_estimate_velocity_when_no_geo_velocity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20210101"]
            cube = np.zeros((2, 3, 4), dtype=np.float32)
            cube[1] = 0.02  # 0.02 m in 1 year
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            data, atr = estimate_velocity_mintpy_default(str(he5))
            self.assertEqual(atr["UNIT"], "m/year")
            np.testing.assert_allclose(data, 0.02, atol=1e-5)

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

    def test_save_explorer_writes_grds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["20200101", "20200701", "20210101"]
            cube = np.zeros((3, 2, 3), dtype=np.float32)
            cube[1] = 0.005
            cube[2] = 0.01
            he5 = root / "prod.he5"
            _write_geo_hdfeos(he5, dates, cube)
            out = root / "InSAR-Explorer"
            inps = save_explorer_cli.cmd_line_parse([str(he5), "-o", str(out)])
            save_explorer(inps)
            self.assertTrue((out / "velocity_mm.grd").is_file())
            for d in dates:
                self.assertTrue((out / f"timeseries-{d}_mm.grd").is_file())


if __name__ == "__main__":
    unittest.main()
