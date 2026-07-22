#!/usr/bin/env python3
"""Re-reference an EGMS L2a CSV so displacement is zero at --ref-lalo.

Finds the nearest CSV point within --search-radius (meters), subtracts that
point's displacement time series from every row (all date columns), and writes
the result in place or to --output. Date columns match hdfeos5_or_csv_2json_mbtiles.py:
SARvey ``DYYYYMMDD`` or EGMS ``YYYYMMDD`` (values in millimeters).
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INSARMAPS_UTILS = Path(__file__).resolve().parents[1] / "insarmaps_utils"
if str(INSARMAPS_UTILS) not in sys.path:
    sys.path.insert(0, str(INSARMAPS_UTILS))

from insarmaps_csv_geo import _detect_lat_lon_fieldnames  # noqa: E402

DEFAULT_SEARCH_RADIUS_M = 100.0

DESCRIPTION = """\
Re-reference an EGMS L2a CSV: subtract the displacement at the nearest point
to --ref-lalo so that location becomes zero (constant offset per date column).

Nearest-neighbor search uses haversine distance with a maximum --search-radius
(default 100 m). If no point falls within the radius, the script exits with an error.
"""

EXAMPLE = """Examples:
reference_point_egms.py egms/EGMS_L2a_044_IW2_VV_2020_2024_concat.csv --ref-lalo 37.80455 15.17508
reference_point_egms.py data.csv --ref-lalo 37.80455,15.17508 --search-radius 1000
reference_point_egms.py data.csv --ref-lalo 37.80455 15.17508 --output referenced.csv
"""


def create_parser():
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("infile", help="Input EGMS L2a CSV")
    parser.add_argument(
        "--ref-lalo",
        nargs="+",
        metavar="LAT LON",
        required=True,
        help="Reference location as LAT LON or LAT,LON (degrees)",
    )
    parser.add_argument(
        "--search-radius",
        type=float,
        default=DEFAULT_SEARCH_RADIUS_M,
        metavar="METERS",
        help=(
            "Maximum haversine distance (meters) from --ref-lalo to accept a CSV point "
            f"(default: {DEFAULT_SEARCH_RADIUS_M:g} m). The nearest point within this "
            "radius is used; if none qualify, the script fails."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="outfile",
        default=None,
        help="Output CSV path (default: update input in place)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-reference even if the nearest point is already within 1 mm of zero on all dates",
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
    raise ValueError(f"--ref-lalo expects LAT LON or LAT,LON; got {tokens!r}")


def detect_date_columns(columns):
    """Return sorted date column names (SARvey DYYYYMMDD or EGMS YYYYMMDD)."""
    cols = [str(c).strip() for c in columns]
    sarvey = sorted(c for c in cols if c.startswith("D") and c[1:].isdigit())
    if sarvey:
        return sarvey
    return sorted(c for c in cols if c.isdigit() and len(c) == 8)


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters (vectorized over lat2/lon2 arrays)."""
    r = 6378137.0
    lat1_r = math.radians(lat1)
    lon1_r = math.radians(lon1)
    lat2_r = np.radians(np.asarray(lat2, dtype=float))
    lon2_r = np.radians(np.asarray(lon2, dtype=float))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2.0) ** 2
    return 2.0 * r * np.arcsin(np.sqrt(np.minimum(a, 1.0)))


def find_reference_row(lats, lons, ref_lat, ref_lon, search_radius_m):
    """Return (row_index, distance_m) for nearest point within search_radius_m."""
    dist_m = haversine_m(ref_lat, ref_lon, lats, lons)
    if not np.any(np.isfinite(dist_m)):
        raise ValueError("No finite lat/lon rows in CSV")
    within = dist_m <= float(search_radius_m)
    if not np.any(within):
        nearest = int(np.nanargmin(dist_m))
        raise ValueError(
            f"No CSV point within {search_radius_m:g} m of lat={ref_lat}, lon={ref_lon}. "
            f"Nearest point is {dist_m[nearest]:.1f} m away (row {nearest}). "
            "Increase --search-radius or check coordinates."
        )
    candidates = np.where(within)[0]
    best = candidates[int(np.argmin(dist_m[candidates]))]
    return int(best), float(dist_m[best])


def reference_point_egms(
    csv_path,
    lat,
    lon,
    search_radius_m=DEFAULT_SEARCH_RADIUS_M,
    outfile=None,
    force=False,
):
    """
    Subtract the reference-point displacement from all date columns.

    Returns path to the updated CSV.
    """
    csv_path = Path(csv_path).resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)

    if outfile:
        outfile = Path(outfile).resolve()
        if outfile != csv_path:
            shutil.copy2(csv_path, outfile)
            work_path = outfile
        else:
            work_path = csv_path
    else:
        work_path = csv_path

    df = pd.read_csv(work_path)
    df.columns = [str(c).strip() for c in df.columns]

    lat_col, lon_col = _detect_lat_lon_fieldnames(df.columns)
    if lat_col is None or lon_col is None:
        raise ValueError(
            "Could not find latitude/longitude columns in CSV. "
            "Supported names match hdfeos5_or_csv_2json_mbtiles.py."
        )

    date_cols = detect_date_columns(df.columns)
    if not date_cols:
        raise ValueError("No date columns found (expected DYYYYMMDD or YYYYMMDD headers)")

    lats = df[lat_col].to_numpy(dtype=float)
    lons = df[lon_col].to_numpy(dtype=float)
    row_idx, dist_m = find_reference_row(lats, lons, lat, lon, search_radius_m)

    ref_vals = df.loc[row_idx, date_cols].to_numpy(dtype=float)
    if np.any(~np.isfinite(ref_vals)):
        bad = [date_cols[i] for i, v in enumerate(ref_vals) if not np.isfinite(v)]
        raise ValueError(
            f"NaN/missing displacement at reference row {row_idx} "
            f"(lat={lats[row_idx]}, lon={lons[row_idx]}) for dates: {bad[:5]}"
        )

    if not force and np.all(np.abs(ref_vals) <= 1.0):
        print(
            f"Reference row {row_idx} already near zero (max |disp| <= 1 mm); "
            "use --force to re-apply."
        )
        return str(work_path)

    print(
        f"Reference row: {row_idx} "
        f"(csv lat={lats[row_idx]:.6f}, lon={lons[row_idx]:.6f}; "
        f"distance={dist_m:.1f} m from target lat={lat}, lon={lon})"
    )
    print(f"Date columns: {len(date_cols)} ({date_cols[0]} … {date_cols[-1]})")

    for col, ref_val in zip(date_cols, ref_vals):
        df[col] = pd.to_numeric(df[col], errors="coerce") - ref_val

    df.to_csv(work_path, index=False)
    print(f"Updated reference point in: {work_path}")
    return str(work_path)


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        lat, lon = parse_ref_lalo(inps.ref_lalo)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if inps.search_radius <= 0:
        print("Error: --search-radius must be positive", file=sys.stderr)
        return 1
    try:
        out = reference_point_egms(
            inps.infile,
            lat,
            lon,
            search_radius_m=inps.search_radius,
            outfile=inps.outfile,
            force=inps.force,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Done: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
