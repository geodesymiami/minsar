#!/usr/bin/env python3
"""Expand an AOI bbox so both Sentinel-1 ascending and descending can cover it.

Given a MintPy/MiaplPy-style geographic box (S:N,W:E), compute a larger box
whose axis-aligned extent contains the geographic envelopes of the minimum
radar-oriented rectangles that cover the AOI for nominal S1 ascending and
descending headings. Use the result as miaplpy.subset.lalo / mintpy.subset.lalo.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# Allow `python minsar/scripts/calculate_bbox.py` without PYTHONPATH
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from minsar.utils.bbox_cli_argv import fix_argv_for_negative_bbox_sn_we
from minsar.utils.convert_bbox import _input_to_bounds

# Nominal Sentinel-1 platform headings (degrees clockwise from north).
DEFAULT_HEADING_ASC = -12.0
DEFAULT_HEADING_DESC = 192.0  # 180 + 12

# meters per degree latitude (WGS84 approximation)
_M_PER_DEG_LAT = 111_320.0

CALCULATE_BBOX_ARGV_KW = {
    "consume_one": (
        "--heading-asc",
        "--heading-desc",
        "--margin-deg",
        "--digits",
    ),
    "consume_two": (),
    "flags": (),
}

EXAMPLE = """Examples:
  calculate_bbox.py 37.475:37.841,14.913:15.251
  calculate_bbox.py "POLYGON((14.913 37.475,15.251 37.475,15.251 37.841,14.913 37.841,14.913 37.475))"
  calculate_bbox.py 37.475:37.841,14.913:15.251 --heading-asc -13 --heading-desc 193
  calculate_bbox.py 37.475:37.841,14.913:15.251 --margin-deg 0.01
  calculate_bbox.py -- -23.393:-23.097,-68.356:-68.175
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Expand an AOI (S:N,W:E) so the area is covered under both Sentinel-1\n"
            "ascending and descending orbits (nominal heading ±12° from N–S).\n"
            "Output is a larger S:N,W:E suitable for miaplpy.subset.lalo / mintpy.subset.lalo."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument(
        "aoi",
        metavar="AOI",
        help="Area of interest: lat_min:lat_max,lon_min:lon_max (S:N,W:E) or WKT POLYGON.",
    )
    parser.add_argument(
        "--heading-asc",
        type=float,
        default=DEFAULT_HEADING_ASC,
        metavar="DEG",
        help=f"Ascending platform heading, deg clockwise from north (default: {DEFAULT_HEADING_ASC}).",
    )
    parser.add_argument(
        "--heading-desc",
        type=float,
        default=DEFAULT_HEADING_DESC,
        metavar="DEG",
        help=f"Descending platform heading, deg clockwise from north (default: {DEFAULT_HEADING_DESC}).",
    )
    parser.add_argument(
        "--margin-deg",
        type=float,
        default=0.0,
        metavar="DEG",
        help="Extra pad (degrees) added on all sides after orbit expansion (default: 0).",
    )
    parser.add_argument(
        "--digits",
        type=int,
        default=3,
        metavar="N",
        help="Decimal places for printed coordinates (default: 3).",
    )
    return parser


def cmd_line_parse(iargs=None):
    argv = sys.argv[1:] if iargs is None else list(iargs)
    argv = fix_argv_for_negative_bbox_sn_we(argv, **CALCULATE_BBOX_ARGV_KW)
    parser = create_parser()
    return parser.parse_args(argv)


def _local_meters_per_deg(lat_deg: float) -> tuple[float, float]:
    """Return (m_per_deg_lon, m_per_deg_lat) at latitude."""
    m_lat = _M_PER_DEG_LAT
    m_lon = _M_PER_DEG_LAT * math.cos(math.radians(lat_deg))
    if abs(m_lon) < 1e-6:
        m_lon = 1e-6
    return m_lon, m_lat


def _corners_sn_we(min_lat, max_lat, min_lon, max_lon):
    """Four corners as (lon, lat) SW, SE, NE, NW."""
    return (
        (min_lon, min_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
        (min_lon, max_lat),
    )


def _radar_aligned_envelope(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    heading_deg: float,
) -> tuple[float, float, float, float]:
    """Axis-aligned lat/lon bbox of the radar-oriented rectangle covering the AOI.

    Heading is platform azimuth clockwise from north. Along-track unit in
    (east, north) is (sin h, cos h); across-track (right) is (cos h, -sin h).
    """
    lat0 = 0.5 * (min_lat + max_lat)
    lon0 = 0.5 * (min_lon + max_lon)
    m_lon, m_lat = _local_meters_per_deg(lat0)

    h = math.radians(heading_deg)
    along_e, along_n = math.sin(h), math.cos(h)
    across_e, across_n = math.cos(h), -math.sin(h)

    along_vals = []
    across_vals = []
    for lon, lat in _corners_sn_we(min_lat, max_lat, min_lon, max_lon):
        east = (lon - lon0) * m_lon
        north = (lat - lat0) * m_lat
        along_vals.append(east * along_e + north * along_n)
        across_vals.append(east * across_e + north * across_n)

    a0, a1 = min(along_vals), max(along_vals)
    c0, c1 = min(across_vals), max(across_vals)

    env_lats = []
    env_lons = []
    for a in (a0, a1):
        for c in (c0, c1):
            east = a * along_e + c * across_e
            north = a * along_n + c * across_n
            env_lons.append(lon0 + east / m_lon)
            env_lats.append(lat0 + north / m_lat)

    return min(env_lats), max(env_lats), min(env_lons), max(env_lons)


def expand_bbox_for_asc_desc(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    *,
    heading_asc: float = DEFAULT_HEADING_ASC,
    heading_desc: float = DEFAULT_HEADING_DESC,
    margin_deg: float = 0.0,
) -> tuple[float, float, float, float]:
    """Return expanded (S, N, W, E) covering radar envelopes for both headings."""
    if max_lat <= min_lat or max_lon <= min_lon:
        raise ValueError(f"Invalid AOI bounds: {min_lat}:{max_lat},{min_lon}:{max_lon}")

    envelopes = [
        _radar_aligned_envelope(min_lat, max_lat, min_lon, max_lon, heading_asc),
        _radar_aligned_envelope(min_lat, max_lat, min_lon, max_lon, heading_desc),
    ]
    s = min(e[0] for e in envelopes)
    n = max(e[1] for e in envelopes)
    w = min(e[2] for e in envelopes)
    e = max(e[3] for e in envelopes)

    # Always at least the input AOI
    s = min(s, min_lat)
    n = max(n, max_lat)
    w = min(w, min_lon)
    e = max(e, max_lon)

    if margin_deg:
        s -= margin_deg
        n += margin_deg
        w -= margin_deg
        e += margin_deg

    # Clamp latitude
    s = max(s, -90.0)
    n = min(n, 90.0)
    return s, n, w, e


def format_sn_we(min_lat, max_lat, min_lon, max_lon, digits: int = 3) -> str:
    """Format as MintPy/MiaplPy subset.lalo S:N,W:E."""
    fmt = f"{{:.{digits}f}}"
    return (
        f"{fmt.format(min_lat)}:{fmt.format(max_lat)},"
        f"{fmt.format(min_lon)}:{fmt.format(max_lon)}"
    )


def contains_bounds(outer, inner) -> bool:
    """True if outer (S,N,W,E) contains inner (S,N,W,E)."""
    s0, n0, w0, e0 = outer
    s1, n1, w1, e1 = inner
    return s0 <= s1 and n0 >= n1 and w0 <= w1 and e0 >= e1


def main(iargs=None) -> int:
    inps = cmd_line_parse(iargs)
    try:
        min_lat, max_lat, min_lon, max_lon = _input_to_bounds(inps.aoi)
    except ValueError as exc:
        print(f"Error: cannot parse AOI: {exc}", file=sys.stderr)
        return 1

    if inps.digits < 0:
        print("Error: --digits must be >= 0", file=sys.stderr)
        return 1

    expanded = expand_bbox_for_asc_desc(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        heading_asc=inps.heading_asc,
        heading_desc=inps.heading_desc,
        margin_deg=inps.margin_deg,
    )
    out = format_sn_we(*expanded, digits=inps.digits)
    inp = format_sn_we(min_lat, max_lat, min_lon, max_lon, digits=inps.digits)

    print(f"input  AOI : {inp}")
    print(
        f"headings   : asc={inps.heading_asc:g}°, desc={inps.heading_desc:g}° "
        f"(clockwise from north)"
    )
    if inps.margin_deg:
        print(f"margin     : {inps.margin_deg:g}°")
    print(f"expanded   : {out}")
    print(f"miaplpy.subset.lalo                  = {out}    #[S:N,W:E / no], auto for no")
    print(f"mintpy.subset.lalo                   = {out}    #[S:N,W:E / no], auto for no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
