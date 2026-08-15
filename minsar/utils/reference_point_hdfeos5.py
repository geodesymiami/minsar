#!/usr/bin/env python3
"""In-memory reference-point update for MintPy HDFEOS5 (.he5) files.

Resolves lat/lon from GEO metadata or in-file geometry latitude/longitude
(MintPy geo2radar + geometryRadar.h5 only as fallback). Subtracts the
reference time series from the displacement cube in memory when the pixel
changes. Default is in-place (same basename). Use --output to write a
different path.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import h5py
import numpy as np

DISP_PATH = "HDFEOS/GRIDS/timeseries/observation/displacement"
OBS_GROUP = "HDFEOS/GRIDS/timeseries/observation"
TS_GROUP = "HDFEOS/GRIDS/timeseries"
LAT_PATH = "HDFEOS/GRIDS/timeseries/geometry/latitude"
LON_PATH = "HDFEOS/GRIDS/timeseries/geometry/longitude"
MAX_INMEMORY_BYTES = 4 * 1024**3

DESCRIPTION = """\
Change the spatial reference point of an HDFEOS5 timeseries in place (or to --output).
GEO files use Y_FIRST/X_FIRST; RADAR files use in-file latitude/longitude
(or --lookup / geometryRadar.h5 / temporary extract as fallback).
Prints current and new reference; quits if the pixel is unchanged.
"""

EXAMPLE = """Examples:
reference_point_hdfeos5.py S1_....he5 --ref-lalo -0.81 -91.190
reference_point_hdfeos5.py S1_....he5 --ref-lalo -0.81,-91.190 --output out.he5
reference_point_hdfeos5.py geo_S1_....he5 --ref-lalo 36.4 25.47
"""


def _log(msg):
    print(msg, flush=True)


def create_parser():
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("infile", help="Input HDFEOS5 (.he5) file")
    parser.add_argument(
        "--ref-lalo",
        nargs="+",
        metavar="LAT LON",
        required=True,
        help="Reference point as LAT LON or LAT,LON",
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="outfile",
        default=None,
        help="Output .he5 path (default: update input in place)",
    )
    parser.add_argument(
        "--lookup",
        "-l",
        dest="lookup",
        default=None,
        help="geometryRadar.h5 for RADAR coordinate lookup (optional)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-reference even if REF_Y/REF_X already match the target pixel",
    )
    return parser


def parse_ref_lalo(tokens):
    """Return (lat, lon) floats from ['lat,lon'] or ['lat', 'lon']."""
    if len(tokens) == 1 and "," in tokens[0]:
        parts = tokens[0].split(",")
        if len(parts) != 2:
            raise ValueError(f"Invalid --ref-lalo: {tokens[0]!r}")
        return float(parts[0]), float(parts[1])
    if len(tokens) == 2:
        return float(tokens[0]), float(tokens[1])
    raise ValueError(
        f"--ref-lalo expects LAT LON or LAT,LON; got {tokens!r}"
    )


def _attrs_to_dict(attrs):
    """Decode h5py attribute mapping to a plain str→str dict."""
    out = {}
    for key, val in attrs.items():
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="replace")
        elif isinstance(val, np.ndarray) and val.shape == ():
            val = val.item()
            if isinstance(val, bytes):
                val = val.decode("utf-8", errors="replace")
        out[str(key)] = str(val) if not isinstance(val, str) else val
    return out


def read_he5_metadata(he5_path):
    """Collect metadata from root and observation group (MintPy-style)."""
    meta = {}
    with h5py.File(he5_path, "r") as f:
        meta.update(_attrs_to_dict(f.attrs))
        if OBS_GROUP in f:
            meta.update(_attrs_to_dict(f[OBS_GROUP].attrs))
        if TS_GROUP in f:
            meta.update(_attrs_to_dict(f[TS_GROUP].attrs))
        if DISP_PATH not in f:
            raise KeyError(f"Missing dataset {DISP_PATH} in {he5_path}")
        meta.update(_attrs_to_dict(f[DISP_PATH].attrs))
        shape = f[DISP_PATH].shape
    meta.setdefault("LENGTH", str(shape[-2]))
    meta.setdefault("WIDTH", str(shape[-1]))
    return meta


def is_geo_coords(meta):
    """True when HE5 is geocoded (has Y_FIRST)."""
    return "Y_FIRST" in meta


def lalo_to_yx_geo(meta, lat, lon):
    """Convert lat/lon to pixel y/x for GEO metadata."""
    y_first = float(meta["Y_FIRST"])
    x_first = float(meta["X_FIRST"])
    y_step = float(meta["Y_STEP"])
    x_step = float(meta["X_STEP"])
    ref_y = int(np.rint((lat - y_first) / y_step))
    ref_x = int(np.rint((lon - x_first) / x_step))
    length = int(float(meta["LENGTH"]))
    width = int(float(meta["WIDTH"]))
    if not (0 <= ref_y < length and 0 <= ref_x < width):
        raise ValueError(
            f"Reference pixel ({ref_y}, {ref_x}) outside grid "
            f"{length}x{width} for lat={lat}, lon={lon}"
        )
    return ref_y, ref_x


def lalo_to_yx_from_arrays(lat2d, lon2d, lat, lon):
    """Nearest valid pixel to (lat, lon) in 2D latitude/longitude arrays."""
    d2 = (lat2d.astype(np.float64) - lat) ** 2 + (lon2d.astype(np.float64) - lon) ** 2
    d2 = np.where(np.isfinite(d2), d2, np.inf)
    if not np.isfinite(d2).any():
        raise ValueError("No valid lat/lon pixels for reference search")
    ref_y, ref_x = np.unravel_index(int(np.argmin(d2)), d2.shape)
    return int(ref_y), int(ref_x)


def lalo_to_yx_he5_geometry(he5_path, lat, lon):
    """Return (y, x) from in-file geometry lat/lon, or None if datasets missing."""
    with h5py.File(he5_path, "r") as f:
        if LAT_PATH not in f or LON_PATH not in f:
            return None
        lat2d = f[LAT_PATH][()]
        lon2d = f[LON_PATH][()]
    return lalo_to_yx_from_arrays(lat2d, lon2d, lat, lon)


def lalo_to_yx_radar(meta, lat, lon, lookup_path):
    """Convert lat/lon to radar y/x via MintPy coordinate.geo2radar + lookup."""
    from mintpy.utils import utils as ut

    atr = dict(meta)
    atr["FILE_TYPE"] = atr.get("FILE_TYPE", "timeseries")
    coord = ut.coordinate(atr, lookup_file=lookup_path)
    # geo2radar (not lalo2yx): lalo2yx is for geocoded files only.
    ref_y, ref_x = coord.geo2radar(np.array(lat), np.array(lon))[0:2]
    ref_y, ref_x = int(np.asarray(ref_y).item()), int(np.asarray(ref_x).item())
    length = int(float(meta["LENGTH"]))
    width = int(float(meta["WIDTH"]))
    if not (0 <= ref_y < length and 0 <= ref_x < width):
        raise ValueError(
            f"Reference pixel ({ref_y}, {ref_x}) outside radar grid "
            f"{length}x{width} for lat={lat}, lon={lon}"
        )
    return ref_y, ref_x


def ensure_radar_lookup(he5_path, lookup_pre=None):
    """Return path to geometryRadar.h5 for RADAR HE5."""
    if lookup_pre and os.path.isfile(lookup_pre):
        return os.path.abspath(lookup_pre)

    he5_dir = os.path.dirname(os.path.abspath(he5_path))
    for candidate in (
        os.path.join(he5_dir, "geometryRadar.h5"),
        os.path.join(he5_dir, "inputs", "geometryRadar.h5"),
        os.path.join(he5_dir, "geo", "geo_geometryRadar.h5"),
    ):
        if os.path.isfile(candidate):
            return candidate

    # Extract geometry only into a temp dir (same idea as geocode_hdfeos5._ensure_lookup).
    extract = shutil.which("extract_hdfeos5.py")
    if not extract:
        raise FileNotFoundError(
            "geometryRadar.h5 not found beside HE5 and extract_hdfeos5.py not on PATH. "
            "Pass --lookup /path/to/geometryRadar.h5."
        )
    with tempfile.TemporaryDirectory(prefix=".ref_he5_lut_", dir=he5_dir) as tmpdir:
        he5_in_tmp = os.path.join(tmpdir, os.path.basename(he5_path))
        os.symlink(os.path.abspath(he5_path), he5_in_tmp)
        result = subprocess.run([extract, he5_in_tmp], check=False)
        if result.returncode != 0:
            raise RuntimeError(f"extract_hdfeos5.py failed for lookup from {he5_path}")
        lut = os.path.join(tmpdir, "geometryRadar.h5")
        if not os.path.isfile(lut):
            lut = os.path.join(tmpdir, "inputs", "geometryRadar.h5")
        if not os.path.isfile(lut):
            raise FileNotFoundError(
                "Lookup not found after extract. Pass --lookup geometryRadar.h5."
            )
        out_lut = os.path.join(he5_dir, ".ref_he5_lut_geometryRadar.h5")
        shutil.copy(lut, out_lut)
    return out_lut


def resolve_ref_yx(he5_path, lat, lon, lookup=None):
    """Return (ref_y, ref_x, meta, coords) for lat/lon on HE5."""
    meta = read_he5_metadata(he5_path)
    if is_geo_coords(meta):
        ref_y, ref_x = lalo_to_yx_geo(meta, lat, lon)
        return ref_y, ref_x, meta, "GEO"
    _log("Resolving reference pixel from in-file latitude/longitude ...")
    yx = lalo_to_yx_he5_geometry(he5_path, lat, lon)
    if yx is not None:
        return yx[0], yx[1], meta, "RADAR"
    _log("In-file lat/lon not found; using geometryRadar.h5 lookup ...")
    lookup_path = ensure_radar_lookup(he5_path, lookup_pre=lookup)
    ref_y, ref_x = lalo_to_yx_radar(meta, lat, lon, lookup_path)
    return ref_y, ref_x, meta, "RADAR"


def _parse_current_ref(meta):
    """Return (y, x, lat, lon); y/x are None if missing or unparsable."""
    try:
        cur_y = int(float(meta["REF_Y"]))
        cur_x = int(float(meta["REF_X"]))
    except (KeyError, TypeError, ValueError):
        cur_y, cur_x = None, None
    try:
        cur_lat = float(meta["REF_LAT"])
        cur_lon = float(meta["REF_LON"])
    except (KeyError, TypeError, ValueError):
        cur_lat, cur_lon = None, None
    return cur_y, cur_x, cur_lat, cur_lon


def _fmt_ref(y, x, lat, lon):
    """Format a reference point for logging."""
    yx = f"y={y}, x={x}" if y is not None and x is not None else "y=?, x=?"
    if lat is None or lon is None:
        return f"{yx} (lat=?, lon=?)"
    return f"{yx} (lat={lat}, lon={lon})"


def _set_ref_attrs(h5obj, ref_y, ref_x, lat, lon):
    """Write REF_* attributes onto an h5py File or Group."""
    h5obj.attrs["REF_Y"] = str(ref_y)
    h5obj.attrs["REF_X"] = str(ref_x)
    h5obj.attrs["REF_LAT"] = str(lat)
    h5obj.attrs["REF_LON"] = str(lon)


def _apply_ref_attrs(f, ref_y, ref_x, lat, lon):
    """Write REF_* on root, observation, and timeseries groups if present."""
    _set_ref_attrs(f, ref_y, ref_x, lat, lon)
    if OBS_GROUP in f:
        _set_ref_attrs(f[OBS_GROUP], ref_y, ref_x, lat, lon)
    if TS_GROUP in f:
        _set_ref_attrs(f[TS_GROUP], ref_y, ref_x, lat, lon)


def _check_ref_series(ref, ref_y, ref_x):
    """Raise if any date is NaN at the reference pixel."""
    if np.isnan(ref).any():
        bad = int(np.flatnonzero(np.isnan(ref))[0])
        raise ValueError(
            f"NaN at reference pixel (y={ref_y}, x={ref_x}) on date index {bad}"
        )


def update_displacement(ds, ref_y, ref_x):
    """Subtract displacement at (ref_y, ref_x) from every date.

    Loads the cube when it fits in MAX_INMEMORY_BYTES; otherwise writes
    chunk-aligned date blocks so LZF chunks are rewritten once.
    """
    n_dates, length, width = ds.shape[0], ds.shape[1], ds.shape[2]
    nbytes = int(n_dates) * int(length) * int(width) * ds.dtype.itemsize
    if nbytes <= MAX_INMEMORY_BYTES:
        _log(
            f"Updating displacement in memory "
            f"({n_dates} dates, {length}x{width}, {nbytes / 1e6:.1f} MB) ..."
        )
        data = ds[()]
        ref = np.asarray(data[:, ref_y, ref_x])
        _check_ref_series(ref, ref_y, ref_x)
        data -= ref[:, None, None]
        ds[()] = data
        return

    chunk0 = ds.chunks[0] if ds.chunks else 1
    _log(
        f"Updating displacement in {chunk0}-date blocks "
        f"({n_dates} dates, {length}x{width}) ..."
    )
    ref = np.asarray(ds[:, ref_y, ref_x])
    _check_ref_series(ref, ref_y, ref_x)
    for i0 in range(0, n_dates, chunk0):
        i1 = min(i0 + chunk0, n_dates)
        slab = np.asarray(ds[i0:i1, :, :])
        slab = slab - ref[i0:i1, None, None]
        ds[i0:i1, :, :] = slab


def reference_point_hdfeos5(he5_path, lat, lon, outfile=None, lookup=None, force=False):
    """Subtract displacement at (lat, lon) from every date; update REF_* attrs.

    Returns path to the updated HE5 file, or the input path if the reference
    pixel is unchanged (no write).
    """
    he5_path = os.path.abspath(he5_path)
    if not os.path.isfile(he5_path):
        raise FileNotFoundError(he5_path)

    _log(f"Reading {he5_path} ...")
    ref_y, ref_x, meta, coords = resolve_ref_yx(he5_path, lat, lon, lookup=lookup)
    cur_y, cur_x, cur_lat, cur_lon = _parse_current_ref(meta)

    _log(f"Coordinate system: {coords}")
    _log(f"Current reference: {_fmt_ref(cur_y, cur_x, cur_lat, cur_lon)}")
    _log(f"New reference:     {_fmt_ref(ref_y, ref_x, lat, lon)}")

    if not force and cur_y is not None and cur_y == ref_y and cur_x == ref_x:
        _log("Current and new reference point are the same; nothing to do.")
        return he5_path

    if outfile:
        outfile = os.path.abspath(outfile)
        if outfile != he5_path:
            _log(f"Copying to {outfile} ...")
            shutil.copy2(he5_path, outfile)
            work_path = outfile
        else:
            work_path = he5_path
    else:
        work_path = he5_path

    with h5py.File(work_path, "r+") as f:
        update_displacement(f[DISP_PATH], ref_y, ref_x)
        _apply_ref_attrs(f, ref_y, ref_x, lat, lon)

    _log(f"Updated reference point in: {work_path}")
    return work_path


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        lat, lon = parse_ref_lalo(inps.ref_lalo)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        out = reference_point_hdfeos5(
            inps.infile,
            lat,
            lon,
            outfile=inps.outfile,
            lookup=inps.lookup,
            force=inps.force,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Done: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
