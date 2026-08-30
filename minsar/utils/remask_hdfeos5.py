#!/usr/bin/env python3
"""Rebuild quality/mask in an HDF-EOS5 file from embedded quality layers.

Same -m / --vmin / --vmin-sim as dolphin2hdfeos5.py. Writes a new .he5 with a
mask suffix (does not modify the input in place). NaN-fills displacement outside mask.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from minsar.utils.dolphin_hdfeos5_utils import (
        REMASK_HDFEOS5_EXAMPLES,
        add_mask_arguments,
        apply_mask_suffix,
        mask_filename_suffix,
        remask_he5_file,
        resolve_mask_thresholds,
    )
except ImportError:
    from dolphin_hdfeos5_utils import (
        REMASK_HDFEOS5_EXAMPLES,
        add_mask_arguments,
        apply_mask_suffix,
        mask_filename_suffix,
        remask_he5_file,
        resolve_mask_thresholds,
    )

DESCRIPTION = "Remask an HDF-EOS5 file using embedded quality layers (default -m recommended)"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=REMASK_HDFEOS5_EXAMPLES,
    )
    parser.add_argument("he5_file", help="Input .he5 path")
    parser.add_argument(
        "-o",
        "--output",
        dest="outfile",
        default=None,
        help="Output .he5 (default: input stem + mask suffix)",
    )
    add_mask_arguments(parser)
    return parser


def run(inps) -> Path:
    in_path = Path(inps.he5_file).expanduser().resolve()
    if not in_path.is_file():
        raise FileNotFoundError(f"HE5 not found: {in_path}")
    vmin, vmin_sim = resolve_mask_thresholds(inps.mask_source, inps.vmin, inps.vmin_sim)
    suffix = mask_filename_suffix(inps.mask_source, vmin, vmin_sim)
    if inps.outfile:
        out_path = Path(inps.outfile).expanduser().resolve()
        if out_path.suffix.lower() != ".he5":
            out_path = out_path.with_suffix(".he5")
        out_path = apply_mask_suffix(out_path, suffix)
    else:
        out_path = apply_mask_suffix(in_path, suffix)
    if out_path == in_path:
        raise ValueError(
            f"output would overwrite input ({in_path}); "
            "use a different -m / --vmin (adds a filename suffix) or pass -o OUTFILE"
        )
    print(f"Input:  {in_path}")
    print(f"Mask:   -m {inps.mask_source} --vmin {vmin}" + (f" --vmin-sim {vmin_sim}" if vmin_sim is not None else ""))
    print(f"Output: {out_path}")
    remask_he5_file(in_path, out_path, inps.mask_source, vmin, vmin_sim)
    print(f"\nIngest with:\n  ingest_insarmaps.bash \"{out_path}\"")
    return out_path


def main(iargs=None):
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
