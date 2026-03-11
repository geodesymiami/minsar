#!/usr/bin/env python3
"""
Flip the sign of the perpendicular baseline in slcStack.h5 (MiaplPy/MintPy format).

Usage:
    flip_sign_bperp.py slcStack.h5
    flip_sign_bperp.py --dry-run path/to/inputs/slcStack.h5
    flip_sign_bperp.py --revert slcStack.h5
"""

import argparse
import sys

import h5py
import numpy as np

ATTR_BPERP_SIGN_FLIPPED = "bperp_sign_flipped"


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
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Revert a previous flip (flip sign back and set bperp_sign_flipped=False)",
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
            already_flipped = bperp.attrs.get(ATTR_BPERP_SIGN_FLIPPED, False)

            if args.dry_run:
                print(f"bperp (first 5): {data[:5].tolist()}")
                print(f"bperp_sign_flipped: {already_flipped}")
                if args.revert:
                    print("Would revert (flip sign and set bperp_sign_flipped=False)." if already_flipped else "Nothing to revert (bperp sign not flipped).")
                else:
                    print("Would flip sign (multiply by -1) and set bperp_sign_flipped=True." if not already_flipped else "Sign already flipped.")
                return 0

            if args.revert:
                if not already_flipped:
                    print("bperp sign not flipped", file=sys.stderr)
                    return 1
                bperp[...] = np.float32(-data)
                bperp.attrs[ATTR_BPERP_SIGN_FLIPPED] = False
                print(f"Reverted sign of bperp in {path} ({len(data)} values).")
            else:
                if already_flipped:
                    print("Sign already flipped")
                    return 0
                bperp[...] = np.float32(-data)
                bperp.attrs[ATTR_BPERP_SIGN_FLIPPED] = True
                print(f"Flipped sign of bperp in {path} ({len(data)} values).")
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
