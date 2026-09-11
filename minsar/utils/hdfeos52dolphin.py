#!/usr/bin/env python3
"""Convert MintPy HDF-EOS5 (.he5) to an opera-utils *-stack.nc for bowser.

Reverse of ``dolphin2hdfeos5.py``. 2D HE5 quality layers are broadcast along
time. Writes ``demErr`` when that dataset is present in the HE5.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from minsar.utils.dolphin_hdfeos5_utils import (
        HDFEOS52DOLPHIN_EXAMPLES,
        stack_nc_output_path,
        write_opera_stack_nc,
    )
except ImportError:
    from dolphin_hdfeos5_utils import (
        HDFEOS52DOLPHIN_EXAMPLES,
        stack_nc_output_path,
        write_opera_stack_nc,
    )

DESCRIPTION = "Convert HDF-EOS5 (.he5) to an opera-utils *-stack.nc (for bowser)"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=HDFEOS52DOLPHIN_EXAMPLES,
    )
    parser.add_argument("he5_file", help="Input .he5 path")
    parser.add_argument(
        "-o",
        "--output",
        dest="outfile",
        default=None,
        help="Output *-stack.nc (default: <he5-stem>-stack.nc next to the input)",
    )
    return parser


def run(inps) -> Path:
    in_path = Path(inps.he5_file).expanduser().resolve()
    if not in_path.is_file():
        raise FileNotFoundError(f"HE5 not found: {in_path}")
    out_path = stack_nc_output_path(in_path, inps.outfile)
    print(f"Input:  {in_path}")
    print(f"Output: {out_path}")
    return write_opera_stack_nc(in_path, out_path)


def _clear_sweets_gdal_proj_env() -> None:
    """Drop sweets pixi GDAL/PROJ vars so minsar pyproj uses its own proj.db."""
    for key in ("GDAL_DRIVER_PATH", "GDAL_DATA", "PROJ_LIB", "PROJ_DATA"):
        os.environ.pop(key, None)


def main(iargs=None):
    _clear_sweets_gdal_proj_env()
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        run(inps)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
