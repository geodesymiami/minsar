#!/usr/bin/env python3
"""
Flip the sign of the perpendicular baseline in slcStack.h5 (MiaplPy/MintPy format).

Usage:
    flip_sign_bperp.py slcStack.h5
    flip_sign_bperp.py --dry-run path/to/inputs/slcStack.h5
"""

import argparse
import sys

import h5py
import numpy as np


def main():
    parser = argparse.ArgumentParser(
        description="Flip the sign of the perpendicular baseline in slcStack.h5",
        epilog="Example: flip_sign_bperp.py slcStack.h5",
    )
    parser.add_argument(
        "slc_stack",
        metavar="slcStack.h5",
        help="Path to slcStack.h5",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print current bperp and what would be done, do not modify the file",
    )
    args = parser.parse_args()

    path = args.slc_stack

    try:
        with h5py.File(path, "r" if args.dry_run else "r+") as f:
            if "bperp" not in f:
                print(f"Error: no 'bperp' dataset in {path}", file=sys.stderr)
                return 1

            bperp = f["bperp"]
            data = bperp[:]

            if args.dry_run:
                print(f"bperp (first 5): {data[:5].tolist()}")
                print("Would flip sign (multiply by -1).")
                return 0

            bperp[...] = np.float32(-data)
            print(f"Flipped sign of bperp in {path} ({len(data)} values).")
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
