#!/usr/bin/env python3
"""Calculate miaplpy.subset.lalo boxes that cover an AOI for Asc/Desc tracks.

Expands a geographic AOI using platform heading (MintPy HEADING / S1
platformHeading). Default mode pads latitude on the along-track approach side
(Asc: south, Desc: north) from heading skew over the AOI longitude width.

Examples:
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159 --orbit asc
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159 --asc-heading -13.275
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159 --mode aabb
  calculate_bbox_for_miaplpy_subset_lalo.py "POLYGON((15.109 37.796,15.159 37.796,15.159 37.861,15.109 37.861,15.109 37.796))"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a file without an editable install
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from minsar.utils.bbox_cli_argv import (
    CALCULATE_MIAPLPY_SUBSET_ARGV_KW,
    fix_argv_for_negative_bbox_sn_we,
)
from minsar.utils.convert_bbox import _input_to_bounds
from minsar.utils.miaplpy_subset_lalo_expand import (
    DEFAULT_ASC_HEADING_DEG,
    DEFAULT_DESC_HEADING_DEG,
    MODES,
    expand_aoi_to_subset_lines,
)

EXAMPLE = """examples:
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159 --orbit asc
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159 --asc-heading -13.275 --desc-heading -166.725
  calculate_bbox_for_miaplpy_subset_lalo.py 37.796:37.861,15.109:15.159 --mode aabb
  calculate_bbox_for_miaplpy_subset_lalo.py -- -23.393:-23.097,-68.356:-68.175
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Expand AOI to miaplpy.subset.lalo for ascending/descending coverage.\n"
            "Uses platform heading (MintPy HEADING): degrees clockwise from North.\n"
            f"Defaults: Asc {DEFAULT_ASC_HEADING_DEG:g} deg, Desc {DEFAULT_DESC_HEADING_DEG:g} deg "
            "(typical Sentinel-1 mid-latitude; Etna A44 HEADING ~ -13.3).\n"
            "Default --mode asymmetric_lat pads Asc south / Desc north from heading skew;\n"
            "--mode aabb uses the radar-aligned geographic AABB (often identical for Asc/Desc)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument(
        "aoi",
        metavar="AOI",
        help="Geographic AOI: lat_min:lat_max,lon_min:lon_max (S:N,W:E), or POLYGON WKT, or GoogleEarth points",
    )
    parser.add_argument(
        "--orbit",
        choices=("both", "asc", "desc", "ascending", "descending"),
        default="both",
        help="Which orbit direction to print (default: both)",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="asymmetric_lat",
        help="Expansion mode (default: asymmetric_lat)",
    )
    parser.add_argument(
        "--asc-heading",
        type=float,
        default=DEFAULT_ASC_HEADING_DEG,
        metavar="DEG",
        help=f"Ascending platform heading deg CW from North (default: {DEFAULT_ASC_HEADING_DEG:g})",
    )
    parser.add_argument(
        "--desc-heading",
        type=float,
        default=DEFAULT_DESC_HEADING_DEG,
        metavar="DEG",
        help=f"Descending platform heading deg CW from North (default: {DEFAULT_DESC_HEADING_DEG:g})",
    )
    parser.add_argument(
        "--decimals",
        type=int,
        default=3,
        metavar="N",
        help="Decimal places in subset.lalo (default: 3)",
    )
    return parser


def cmd_line_parse(args=None):
    argv = list(sys.argv[1:] if args is None else args)
    argv = fix_argv_for_negative_bbox_sn_we(argv, **CALCULATE_MIAPLPY_SUBSET_ARGV_KW)
    parser = create_parser()
    inps = parser.parse_args(argv)
    if inps.decimals < 0:
        parser.error("--decimals must be >= 0")
    return inps


def main(iargs=None) -> int:
    inps = cmd_line_parse(iargs)
    try:
        min_lat, max_lat, min_lon, max_lon = _input_to_bounds(inps.aoi)
    except ValueError as exc:
        print(f"Error: cannot parse AOI: {exc}", file=sys.stderr)
        return 1

    if inps.orbit == "both":
        orbits = ("asc", "desc")
    elif inps.orbit in ("asc", "ascending"):
        orbits = ("asc",)
    else:
        orbits = ("desc",)

    lines = expand_aoi_to_subset_lines(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        orbits=orbits,
        asc_heading=inps.asc_heading,
        desc_heading=inps.desc_heading,
        decimals=inps.decimals,
        mode=inps.mode,
    )
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
