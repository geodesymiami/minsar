#!/usr/bin/env python3
"""
CLI for add_missing_attributes: add ORBIT_DIRECTION and relative_orbit to
slcStack.h5 and/or geometryRadar.h5 when missing.
"""

import argparse
import sys

from minsar.src.minsar.add_missing_attributes import process_file

EXAMPLE = """
Examples:
  add_missing_attributes.py inputs/slcStack.h5 inputs/geometryRadar.h5
  add_missing_attributes.py --dry-run inputs/slcStack.h5
  add_missing_attributes.py inputs/slcStack.h5 --orbit-number 45000 --platform S1
"""


def create_parser():
    parser = argparse.ArgumentParser(
        description="Add missing ORBIT_DIRECTION and relative_orbit to slcStack.h5 / geometryRadar.h5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="file.h5",
        help="slcStack.h5 and/or geometryRadar.h5 to update",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be added, do not write",
    )
    parser.add_argument(
        "--orbit-number",
        type=int,
        default=None,
        metavar="N",
        help="Absolute orbit number (when not in file)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        metavar="NAME",
        help="Platform e.g. S1, TSX (when not in file)",
    )
    return parser


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    if inps.orbit_number is not None and not inps.platform:
        parser.error("--platform is required when --orbit-number is set")
    if inps.platform and inps.orbit_number is None:
        parser.error("--orbit-number is required when --platform is set")

    ok = 0
    for path in inps.files:
        if process_file(
            path,
            dry_run=inps.dry_run,
            orbit_number_cli=inps.orbit_number,
            platform_cli=inps.platform,
        ):
            ok += 1
    return 0 if ok >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
