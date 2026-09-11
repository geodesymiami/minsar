#!/usr/bin/env python3
"""Add or replace quality/demError in an HDF-EOS5 (.he5) file."""

from __future__ import annotations

import argparse
import os
import sys

import h5py
import numpy as np
from mintpy.utils import readfile

DESCRIPTION = "Add or replace HDFEOS/GRIDS/timeseries/quality/demError in an .he5 file."
EXAMPLES = """Examples:
  add_demerr_to_hdfeos5.py S1_desc_128_mintpy_20160605_20160828.he5
  add_demerr_to_hdfeos5.py S1_desc_128_mintpy_20160605_20160828.he5 -d geo/geo_demErr.h5
  add_demerr_to_hdfeos5.py S1_desc_128_mintpy_20160605_20160828.he5 -d demErr.h5 -t smallbaselineApp.cfg
"""
DEM_ERR_DS = "HDFEOS/GRIDS/timeseries/quality/demError"
FLOAT_ZERO = np.float32(0.0)


def create_parser():
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES,
    )
    parser.add_argument("he5_file", help="HDF-EOS5 (.he5) file to update in place")
    parser.add_argument("-d", "--dem-error", dest="dem_err_file", help="DEM error file (demErr.h5 or geo_demErr.h5)")
    parser.add_argument("-t", "--template", dest="template_file", help="MintPy template used to geocode radar demErr.h5")
    return parser


def _he5_is_geo(he5):
    atr = readfile.read_attribute(he5)
    if "Y_FIRST" in atr:
        return True
    try:
        _, atr2 = readfile.read(he5, datasetName="HDFEOS/GRIDS/timeseries/quality/temporalCoherence")
        return "Y_FIRST" in atr2
    except Exception:
        return False


def _default_dem_path(he5, he5_geo):
    he5_dir = os.path.dirname(os.path.abspath(he5))
    candidates = []
    if he5_geo:
        candidates += [
            os.path.join(he5_dir, "geo_demErr.h5"),
            os.path.join(he5_dir, "geo", "geo_demErr.h5"),
        ]
    candidates += [
        os.path.join(he5_dir, "demErr.h5"),
        os.path.join(os.path.dirname(he5_dir), "demErr.h5"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _geocode_dem_err(radar_file, out_dir, template_file):
    """Geocode radar demErr.h5 into out_dir/geo_demErr.h5. Returns output path or None."""
    work_dir = os.path.dirname(os.path.abspath(radar_file)) or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    iargs = [os.path.abspath(radar_file), "--outdir", os.path.abspath(out_dir), "--update"]
    tmpl = template_file
    if not tmpl:
        cand = os.path.join(work_dir, "smallbaselineApp.cfg")
        if os.path.isfile(cand):
            tmpl = cand
    if tmpl:
        iargs += ["-t", os.path.abspath(tmpl)]
    print("geocode.py", " ".join(iargs))
    cwd = os.getcwd()
    try:
        os.chdir(work_dir)
        from mintpy.cli.geocode import main as geocode_main
        try:
            geocode_main(iargs)
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise RuntimeError(f"geocode.py exited with {exc.code}") from exc
    finally:
        os.chdir(cwd)
    out_file = os.path.join(os.path.abspath(out_dir), "geo_demErr.h5")
    if not os.path.isfile(out_file):
        raise FileNotFoundError(f"geocode.py did not write {out_file}")
    return out_file


def _read_dem_err(dem_path):
    ds_list = readfile.get_dataset_list(dem_path)
    if "dem" in ds_list:
        ds_in = "dem"
    elif "demErr" in ds_list:
        ds_in = "demErr"
    else:
        ds_in = ds_list[0]
    return readfile.read(dem_path, datasetName=ds_in)[0]


def run(inps):
    he5 = os.path.abspath(inps.he5_file)
    if not os.path.isfile(he5):
        raise FileNotFoundError(he5)

    he5_dir = os.path.dirname(he5)
    he5_geo = _he5_is_geo(he5)
    dem_path = inps.dem_err_file or _default_dem_path(he5, he5_geo)
    if not dem_path:
        raise FileNotFoundError("demErr.h5 / geo_demErr.h5 not found (pass -d)")
    if not os.path.isfile(dem_path):
        raise FileNotFoundError(dem_path)

    dem_meta = readfile.read_attribute(dem_path)
    if he5_geo and "Y_FIRST" not in dem_meta.keys():
        out_dir = he5_dir
        if os.path.isdir(os.path.join(he5_dir, "geo")):
            out_dir = os.path.join(he5_dir, "geo")
        tmpl = inps.template_file or os.path.join(he5_dir, "smallbaselineApp.cfg")
        if not os.path.isfile(tmpl):
            tmpl = inps.template_file
        dem_path = _geocode_dem_err(dem_path, out_dir, tmpl)

    data = _read_dem_err(dem_path)
    with h5py.File(he5, "a") as f:
        ref = f["HDFEOS/GRIDS/timeseries/quality/temporalCoherence"]
        if data.shape != ref.shape:
            raise ValueError(f"demError shape {data.shape} != quality grid {ref.shape}")
        grp = f["HDFEOS/GRIDS/timeseries/quality"]
        if "demError" in grp:
            del grp["demError"]
        dset = grp.create_dataset("demError", data=np.asarray(data, dtype=np.float32), chunks=True, compression="lzf")
        dset.attrs["Title"] = "demError"
        dset.attrs["MissingValue"] = FLOAT_ZERO
        dset.attrs["_FillValue"] = FLOAT_ZERO
        dset.attrs["Units"] = "meters"
    print(f"wrote {DEM_ERR_DS} from {dem_path} -> {he5}")
    return he5


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        run(inps)
    except (FileNotFoundError, ValueError, RuntimeError, KeyError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
