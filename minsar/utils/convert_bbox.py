#!/usr/bin/env python3
# Convert bounding box or polygon to topsStack/MintPy/MiaplPy strings (and optionally ASF Vertex URL).
# Accepts: POLYGON WKT, GoogleEarth-style points, or S:N,W:E bbox (lat_min:lat_max,lon_min:lon_max).
# Author: Falk Amelung
# Created: 8/2023; renamed and extended for bbox + --asf
#######################################

import sys
import argparse

# Optional: avoid hard dependency on minsar.objects for standalone use
try:
    from minsar.objects import message_rsmas
except ImportError:
    message_rsmas = None

inps = None

# ASF Vertex URL format (same as burst2stack2vertex.bash: search.asf.alaska.edu)
ASF_VERTEX_BASE = "https://search.asf.alaska.edu/#/"
# Default discovery periods (get_sar_coverage.py)
ASF_DEFAULT_START = "2020-01-01"
ASF_DEFAULT_END = "2020-02-01"
ASF_NISAR_DEFAULT_START = "2026-01-01"
ASF_NISAR_DEFAULT_END = "2026-02-28"

EXAMPLE = """examples:
  convert_bbox.py   "POLYGON((-86.581 12.3995,-86.4958 12.3995,-86.4958 12.454,-86.581 12.454,-86.581 12.3995))"
  convert_bbox.py   12.3995:12.454,-86.581:-86.4958
  convert_bbox.py   "48.1153435942954,32.48224314182711,0 48.1460783620229,32.49847964019297,0 48.1153435942954,32.48224314182711,0"
  convert_bbox.py   12.399:12.454,-86.581:-86.496 --asf
"""


def create_parser():
    parser = argparse.ArgumentParser(
        description="Convert POLYGON or bbox string (S:N,W:E) from ASF Vertex / GoogleEarth to topsStack, MintPy, MiaplPy subset strings.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument("input_str", nargs="?", help="POLYGON WKT, or lat_min:lat_max,lon_min:lon_max (S:N,W:E), or GoogleEarth points")
    parser.add_argument("--lat_delta", type=float, default=0.15, help="Latitude delta for topsStack bbox expansion")
    parser.add_argument("--lon_delta", type=float, default=1.5, help="Longitude delta for topsStack bbox expansion")
    parser.add_argument("--asf", action="store_true", help="Print ASF Vertex / Search URL for S1 BURST coverage (default dates as in get_sar_coverage.py)")
    parser.add_argument("--start", default=ASF_DEFAULT_START, metavar="YYYY-MM-DD", help=f"Start date for ASF URL when --asf (default: {ASF_DEFAULT_START})")
    parser.add_argument("--end", default=ASF_DEFAULT_END, metavar="YYYY-MM-DD", help=f"End date for ASF URL when --asf (default: {ASF_DEFAULT_END})")
    return parser


def cmd_line_parse(args):
    parser = create_parser()
    return parser.parse_args(args)


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
    s = input_str.strip()
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
        return (min(lats), max(lats), min(longs), max(longs))

    # 2) S:N,W:E bbox
    bbox = _parse_bbox_string(s)
    if bbox is not None:
        return bbox

    # 3) GoogleEarth-style: "lon,lat,z lon,lat,z ..."
    try:
        points = s.split()
        longs, lats = [], []
        for point in points:
            parts = point.split(",")
            if len(parts) >= 2:
                longs.append(float(parts[0]))
                lats.append(float(parts[1]))
        if longs and lats:
            return (min(lats), max(lats), min(longs), max(longs))
    except (ValueError, AttributeError):
        pass

    raise ValueError(
        "Cannot parse input. Use POLYGON((...)), or lat_min:lat_max,lon_min:lon_max (S:N,W:E), or GoogleEarth points."
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
    """Convert input (POLYGON or S:N,W:E or GoogleEarth) to bounds and print topsStack/MintPy/MiaplPy strings (and optional ASF URL)."""
    min_lat, max_lat, min_lon, max_lon = _input_to_bounds(input_str)

    min_lat = round(min_lat, 3)
    max_lat = round(max_lat, 3)
    min_lon = round(min_lon, 3)
    max_lon = round(max_lon, 3)

    min_lat_bbox = round(min_lat - lat_delta, 1)
    max_lat_bbox = round(max_lat + lat_delta, 1)
    min_lon_bbox = round(min_lon - lon_delta, 1)
    max_lon_bbox = round(max_lon + lon_delta, 1)

    bbox_str = f"{min_lat_bbox} {max_lat_bbox} {min_lon_bbox} {max_lon_bbox}"
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
        return

    print("WKT POLYGON:")
    print(wkt)
    print("")
    print("Desired strings: ")
    print("")
    print("topsStack.boundingBox                = " + bbox_str)
    print("")
    print("mintpy.subset.lalo                   = " + subset_str + "    #[S:N,W:E / no], auto for no")
    print("miaplpy.subset.lalo                  = " + subset_str + "    #[S:N,W:E / no], auto for no")
    print("")


def main(iargs=None):
    inps = cmd_line_parse(sys.argv[1:] if iargs is None else iargs)
    if inps.input_str is None or inps.input_str.strip() == "":
        create_parser().print_help()
        sys.exit(1)
    run_convert_bbox(
        inps.input_str,
        inps.lat_delta,
        inps.lon_delta,
        asf_only=inps.asf,
        asf_start=inps.start,
        asf_end=inps.end,
    )


if __name__ == "__main__":
    main()
