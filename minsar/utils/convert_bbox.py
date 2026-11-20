#!/usr/bin/env python3
# Convert bounding box or polygon to POLYGON WKT, subset flags, and MintPy/MiaplPy/alos2Stack lines.
# Accepts: POLYGON WKT, GoogleEarth-style points, S:N,W:E, S N W E, or a template assignment of those.
# Author: Falk Amelung
# Created: 8/2023; renamed and extended for bbox + --asf
#######################################

import datetime
import re
import sys
import argparse

from minsar.utils.bbox_cli_argv import (
    CONVERT_BBOX_ARGV_KW,
    fix_argv_for_negative_bbox_sn_we,
)

# Optional: avoid hard dependency on minsar.objects for standalone use
try:
    from minsar.objects import message_rsmas
except ImportError:
    message_rsmas = None

inps = None

# ASF Vertex URL format (same as burst2stack2vertex.bash: search.asf.alaska.edu)
ASF_VERTEX_BASE = "https://search.asf.alaska.edu/#/"
# Default discovery periods (get_sar_coverage.py). NISAR end is today at import.
ASF_DEFAULT_START = "2016-01-01"
ASF_DEFAULT_END = "2026-12-31"
ASF_NISAR_DEFAULT_START = "2026-01-01"
ASF_NISAR_DEFAULT_END = datetime.date.today().isoformat()

EXAMPLE = """examples:
  convert_bbox.py   "POLYGON((-86.581 12.3995,-86.4958 12.3995,-86.4958 12.454,-86.581 12.454,-86.581 12.3995))"
  convert_bbox.py   12.3995:12.454,-86.581:-86.4958
  convert_bbox.py   -8.394 -8.082 117.859 118.176
  convert_bbox.py   "alos2Stack.boundingBox = -8.394 -8.082 117.859 118.176"
  convert_bbox.py   "48.1153435942954,32.48224314182711,0 48.1460783620229,32.49847964019297,0 48.1153435942954,32.48224314182711,0"
  convert_bbox.py   12.399:12.454,-86.581:-86.496 --asf
  convert_bbox.py   -23.393:-23.097,-68.356:-68.175   # negative lat (see -- below if needed)
  convert_bbox.py   -- -23.393:-23.097,-68.356:-68.175
"""


def create_parser():
    parser = argparse.ArgumentParser(
        description="Convert POLYGON, S:N,W:E, or S N W E to WKT, subset flags, and MintPy/MiaplPy/alos2Stack lines.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument("input_str", nargs="*", help="POLYGON WKT, lat_min:lat_max,lon_min:lon_max (S:N,W:E), S N W E, or GoogleEarth points")
    parser.add_argument(
        "--lat_delta",
        type=float,
        default=0.15,
        help="Unused; kept for backward compatibility (topsStack.boundingBox line was removed).",
    )
    parser.add_argument(
        "--lon_delta",
        type=float,
        default=1.5,
        help="Unused; kept for backward compatibility (topsStack.boundingBox line was removed).",
    )
    parser.add_argument("--asf", action="store_true", help="Print ASF Vertex / Search URL for S1 BURST coverage (default dates as in get_sar_coverage.py)")
    parser.add_argument("--start-date", default=ASF_DEFAULT_START, metavar="YYYY-MM-DD", help=f"Start date for ASF URL when --asf (default: {ASF_DEFAULT_START})")
    parser.add_argument("--end-date", default=ASF_DEFAULT_END, metavar="YYYY-MM-DD", help=f"End date for ASF URL when --asf (default: {ASF_DEFAULT_END})")
    return parser


def cmd_line_parse(args):
    parser = create_parser()
    args = fix_argv_for_negative_bbox_sn_we(list(args), **CONVERT_BBOX_ARGV_KW)
    args = _fix_argv_for_snwe_numbers(args)
    return parser.parse_args(args)


_NUMBER_TOKEN = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$")


def _is_number_token(token):
    return bool(_NUMBER_TOKEN.match(token))


def _parse_snwe_numbers(s):
    """Parse S N W E (lat_min lat_max lon_min lon_max). Returns bounds or None."""
    parts = s.split()
    if len(parts) != 4:
        return None
    try:
        lat_min, lat_max, lon_min, lon_max = (float(part) for part in parts)
    except ValueError:
        return None
    return (min(lat_min, lat_max), max(lat_min, lat_max), min(lon_min, lon_max), max(lon_min, lon_max))


def _assignment_rhs(s):
    """Drop a template 'key = value' prefix and a trailing # comment."""
    s = s.strip()
    if "=" in s:
        s = s.split("=", 1)[1].strip()
    if "#" in s:
        s = s.split("#", 1)[0].strip()
    return s


def _tail_is_known_options(tail):
    """True when every token in tail is a convert_bbox option (and its value)."""
    one = frozenset(CONVERT_BBOX_ARGV_KW["consume_one"])
    flags = frozenset(CONVERT_BBOX_ARGV_KW["flags"])
    k = 0
    n = len(tail)
    while k < n:
        token = tail[k]
        if token in flags:
            k += 1
            continue
        if token in one and k + 1 < n:
            k += 2
            continue
        if token.startswith("--") and "=" in token:
            k += 1
            continue
        return False
    return True


def _fix_argv_for_snwe_numbers(argv):
    """Insert '--' before S N W E numbers so a leading '-' is not an option."""
    argv = list(argv)
    if not argv or "--" in argv or argv[0] in ("-h", "--help"):
        return argv

    one = frozenset(CONVERT_BBOX_ARGV_KW["consume_one"])
    flags = frozenset(CONVERT_BBOX_ARGV_KW["flags"])
    i = 0
    n = len(argv)
    while i < n:
        token = argv[i]
        if token in ("-h", "--help"):
            return argv
        if token in flags:
            i += 1
            continue
        if token in one:
            if i + 1 >= n:
                return argv
            i += 2
            continue
        if token.startswith("--") and "=" in token:
            i += 1
            continue
        break

    rest = argv[i:]
    if not rest:
        return argv

    nums = []
    j = 0
    while j < len(rest) and len(nums) < 4 and _is_number_token(rest[j]):
        nums.append(rest[j])
        j += 1
    if len(nums) == 4 and any(num.startswith("-") for num in nums) and _tail_is_known_options(rest[j:]):
        return argv[:i] + rest[j:] + ["--"] + nums

    if rest[0].startswith("-") and _parse_snwe_numbers(rest[0]) is not None and _tail_is_known_options(rest[1:]):
        return argv[:i] + rest[1:] + ["--", rest[0]]
    return argv


def _parse_bbox_string(s):
    """Parse S:N,W:E (lat_min:lat_max,lon_min:lon_max). Returns (min_lat, max_lat, min_lon, max_lon) or None."""
    s = s.strip()
    if "," not in s or ":" not in s:
        return None
    try:
        lat_part, lon_part = s.split(",", 1)
        lat_min, lat_max = map(float, lat_part.split(":"))
        lon_min, lon_max = map(float, lon_part.split(":"))
        return (min(lat_min, lat_max), max(lat_min, lat_max), min(lon_min, lon_max), max(lon_min, lon_max))
    except (ValueError, AttributeError):
        return None


def _normalize_lon(lon):
    """Normalize longitude into [-180, 180] range."""
    wrapped = ((lon + 180.0) % 360.0) - 180.0
    if wrapped == -180.0 and lon > 0:
        return 180.0
    return wrapped


def _normalize_bounds(min_lat, max_lat, min_lon, max_lon):
    """Normalize longitudes and return canonical lat/lon bounds."""
    lon_a = _normalize_lon(min_lon)
    lon_b = _normalize_lon(max_lon)
    return (
        min(min_lat, max_lat),
        max(min_lat, max_lat),
        min(lon_a, lon_b),
        max(lon_a, lon_b),
    )


def _bbox_to_wkt(min_lat, max_lat, min_lon, max_lon):
    """Return WKT POLYGON for a rectangular bbox (lon lat order, closed)."""
    return (
        f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},"
        f"{max_lon} {max_lat},{min_lon} {max_lat},{min_lon} {min_lat}))"
    )


def _input_to_bounds(input_str):
    """
    Detect input format and return (min_lat, max_lat, min_lon, max_lon).
    Raises ValueError if unparseable.
    """
    s = _assignment_rhs(input_str)
    if not s:
        raise ValueError("Empty input")

    # 1) POLYGON WKT
    if s.upper().startswith("POLYGON"):
        modified = s.removeprefix("POLYGON((").removesuffix("))")
        points = modified.split(",")
        longs, lats = [], []
        for point in points:
            parts = point.split()
            if len(parts) >= 2:
                longs.append(float(parts[0]))
                lats.append(float(parts[1]))
        if not longs or not lats:
            raise ValueError("POLYGON has no valid coordinates")
        return _normalize_bounds(min(lats), max(lats), min(longs), max(longs))

    # 2) S:N,W:E bbox
    bbox = _parse_bbox_string(s)
    if bbox is not None:
        return _normalize_bounds(*bbox)

    # 3) S N W E (alos2Stack.boundingBox / topsStack.boundingBox)
    snwe = _parse_snwe_numbers(s)
    if snwe is not None:
        return _normalize_bounds(*snwe)

    # 4) GoogleEarth-style: "lon,lat,z lon,lat,z ..."
    try:
        points = s.split()
        longs, lats = [], []
        for point in points:
            parts = point.split(",")
            if len(parts) >= 2:
                longs.append(float(parts[0]))
                lats.append(float(parts[1]))
        if longs and lats:
            return _normalize_bounds(min(lats), max(lats), min(longs), max(longs))
    except (ValueError, AttributeError):
        pass

    raise ValueError(
        "Cannot parse input. Use POLYGON((...)), lat_min:lat_max,lon_min:lon_max (S:N,W:E), S N W E, or GoogleEarth points."
    )


def _asf_vertex_url(wkt, min_lat, max_lat, min_lon, max_lon, start, end, dataset_param, extra_params=None):
    """Build ASF Vertex URL (same format as burst2stack2vertex.bash). dataset_param is URL-encoded. extra_params: optional list of 'key=value' for NISAR etc."""
    polygon_enc = wkt.replace(" ", "%20")
    lon_center = round((min_lon + max_lon) / 2, 3)
    lat_center = round((min_lat + max_lat) / 2, 3)
    params = [
        "zoom=9.1",
        f"center={lon_center},{lat_center}",
        f"polygon={polygon_enc}",
        f"dataset={dataset_param}",
        "maxResults=250",
        "resultsLoaded=true",
        f"start={start}T00:00:00Z",
        f"end={end}T23:59:59Z",
    ]
    if extra_params:
        params.extend(extra_params)
    return f"{ASF_VERTEX_BASE}?{'&'.join(params)}"


def run_convert_bbox(input_str, lat_delta, lon_delta, asf_only=False, asf_start=None, asf_end=None):
    """Convert input to bounds; print WKT, subset flags, and MintPy/MiaplPy/alos2Stack lines (optional ASF URL)."""
    _ = (lat_delta, lon_delta)  # CLI backward compatibility; no longer affect output
    min_lat, max_lat, min_lon, max_lon = _input_to_bounds(input_str)

    min_lat = round(min_lat, 3)
    max_lat = round(max_lat, 3)
    min_lon = round(min_lon, 3)
    max_lon = round(max_lon, 3)

    subset_str = f"{min_lat}:{max_lat},{min_lon}:{max_lon}"
    wkt = _bbox_to_wkt(min_lat, max_lat, min_lon, max_lon)

    if asf_only:
        start = asf_start or ASF_DEFAULT_START
        end = asf_end or ASF_DEFAULT_END
        s1_url = _asf_vertex_url(wkt, min_lat, max_lat, min_lon, max_lon, start, end, "SENTINEL-1%20BURSTS")
        nisar_url = _asf_vertex_url(
            wkt, min_lat, max_lat, min_lon, max_lon,
            ASF_NISAR_DEFAULT_START, ASF_NISAR_DEFAULT_END,
            "NISAR",
            extra_params=["processingLevel=GSLC", "prodConfig=PR", "sciProducts=GSLC"],
        )
        print("Sentinel-1 bursts")
        print(s1_url)
        print("")
        print("NISAR")
        print(nisar_url)
        print("")
        print("WKT (paste in Vertex if needed):")
        print(wkt)
        print("")
        print(f"--sub-lat {min_lat} {max_lat} --sub-lon {min_lon} {max_lon}")
        return

    print(wkt)
    print("")
    print(f"--sub-lat {min_lat} {max_lat} --sub-lon {min_lon} {max_lon}")
    print(f"alos2Stack.boundingBox               = {min_lat} {max_lat} {min_lon} {max_lon}")
    print("")
    print("mintpy.subset.lalo                   = " + subset_str + "    #[S:N,W:E / no], auto for no")
    print("miaplpy.subset.lalo                  = " + subset_str + "    #[S:N,W:E / no], auto for no")
    print("")


def main(iargs=None):
    inps = cmd_line_parse(sys.argv[1:] if iargs is None else iargs)
    input_str = " ".join(inps.input_str).strip()
    if input_str == "":
        create_parser().print_help()
        sys.exit(1)
    run_convert_bbox(
        input_str,
        inps.lat_delta,
        inps.lon_delta,
        asf_only=inps.asf,
        asf_start=inps.start_date,
        asf_end=inps.end_date,
    )


if __name__ == "__main__":
    main()
