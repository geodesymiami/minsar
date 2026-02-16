#!/usr/bin/env python3
"""
Check that each .SAFE directory in the given directory is complete.
If a required file (e.g. preview/map-overlay.kml) is missing, remove the SAFE
and log the date to DATES_REMOVED.txt.
"""

import argparse
import glob
import os
import re
import shutil
import sys

from minsar.objects import message_rsmas

# Required paths inside each SAFE (relative to SAFE root). Extend this list as needed.
REQUIRED_SAFE_PATHS = [
    "preview/map-overlay.kml",
]

DATES_REMOVED_FILENAME = "DATES_REMOVED.txt"


def _date_from_safe_name(safe_basename):
    """Extract YYYYMMDD from SAFE name, e.g. S1A_IW_SLC__1SSV_20170116T161603_... -> 20170116."""
    match = re.search(r"(\d{4})(\d{2})(\d{2})T", safe_basename)
    if match:
        return match.group(1) + match.group(2) + match.group(3)
    return None


def main(iargs=None):
    parser = argparse.ArgumentParser(
        description="Check SAFE directories for required files; remove incomplete SAFEs and log to DATES_REMOVED.txt"
    )
    parser.add_argument("slc_dir", help="Directory containing .SAFE dirs (e.g. SLC)")
    inps = parser.parse_args(args=iargs)

    if iargs is not None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1:]
    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + " " + " ".join(input_arguments))

    slc_dir = inps.slc_dir
    if not os.path.isdir(slc_dir):
        print(f"ERROR: Not a directory: {slc_dir}", file=sys.stderr)
        return 1

    dates_removed_file = os.path.join(slc_dir, DATES_REMOVED_FILENAME)
    safe_dirs = glob.glob(os.path.join(slc_dir, "*.SAFE"))

    for safe_path in safe_dirs:
        if not os.path.isdir(safe_path):
            continue
        safe_basename = os.path.basename(safe_path)
        incomplete_reason = None
        for req in REQUIRED_SAFE_PATHS:
            full_path = os.path.join(safe_path, req)
            if not os.path.isfile(full_path):
                incomplete_reason = f"SAFE incomplete: {req} missing"
                break
        if incomplete_reason is None:
            continue
        date_str = _date_from_safe_name(safe_basename)
        if date_str:
            with open(dates_removed_file, "a") as f:
                f.write(f"{date_str}  {incomplete_reason}\n")
        print(f"Removing incomplete SAFE: {safe_basename} ({incomplete_reason})")
        try:
            shutil.rmtree(safe_path)
        except Exception as e:
            print(f"WARNING: Could not remove {safe_path}: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
