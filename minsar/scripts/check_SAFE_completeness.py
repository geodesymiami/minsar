#!/usr/bin/env python3
"""
Check that each .SAFE directory in the given directory is complete.
A SAFE is complete when it has manifest.safe, preview/map-overlay.kml,
at least one annotation XML, and at least one measurement TIFF.
Incomplete SAFEs are removed and the date is logged to dates_removed.txt.
The file is kept sorted by date (first column).
"""

import argparse
import glob
import os
import re
import shutil
import sys

from minsar.objects import message_rsmas

# Required paths inside each SAFE (relative to SAFE root).
REQUIRED_SAFE_PATHS = [
    "manifest.safe",
    "preview/map-overlay.kml",
]

DATES_REMOVED_FILENAME = "dates_removed.txt"


def _date_from_safe_name(safe_basename):
    """Extract YYYYMMDD from SAFE name, e.g. S1A_IW_SLC__1SSV_20170116T161603_... -> 20170116."""
    match = re.search(r"(\d{4})(\d{2})(\d{2})T", safe_basename)
    if match:
        return match.group(1) + match.group(2) + match.group(3)
    return None


def _nonempty_files(directory, suffixes):
    """Return non-empty files in directory whose names end with one of suffixes."""
    if not os.path.isdir(directory):
        return []
    found = []
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            continue
        lower = name.lower()
        if any(lower.endswith(suffix) for suffix in suffixes):
            found.append(path)
    return found


def incomplete_reason(safe_path):
    """Return why safe_path is incomplete, or None if it is usable by ISCE."""
    for req in REQUIRED_SAFE_PATHS:
        full_path = os.path.join(safe_path, req)
        if not os.path.isfile(full_path) or os.path.getsize(full_path) == 0:
            return f"SAFE incomplete: {req} missing"
    if not _nonempty_files(os.path.join(safe_path, "annotation"), (".xml",)):
        return "SAFE incomplete: no annotation XML"
    if not _nonempty_files(os.path.join(safe_path, "measurement"), (".tif", ".tiff")):
        return "SAFE incomplete: no measurement TIFF"
    return None


def main(iargs=None):
    parser = argparse.ArgumentParser(
        description="Remove .SAFE dirs missing manifest, annotation XML, or a measurement TIFF. Log dates to dates_removed.txt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  check_SAFE_completeness.py SLC\n  check_SAFE_completeness.py --dry-run SLC",
    )
    parser.add_argument("slc_dir", help="Directory containing .SAFE dirs (e.g. SLC)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report which SAFE dirs would be removed; do not remove or append to dates_removed.txt",
    )
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
        reason = incomplete_reason(safe_path)
        if reason is None:
            continue
        date_str = _date_from_safe_name(safe_basename)
        if inps.dry_run:
            print(f"[dry-run] Would remove: {safe_path} ({reason})")
            if date_str:
                print(f"  -> would append to {dates_removed_file}: {date_str}  {reason}")
            continue
        if date_str:
            with open(dates_removed_file, "a") as f:
                f.write(f"{date_str}  {reason}\n")
        print(f"Removing incomplete SAFE: {safe_basename} ({reason})")
        try:
            shutil.rmtree(safe_path)
        except Exception as e:
            print(f"WARNING: Could not remove {safe_path}: {e}", file=sys.stderr)

    # Keep dates_removed.txt sorted by date (first column YYYYMMDD)
    if not inps.dry_run and os.path.isfile(dates_removed_file):
        with open(dates_removed_file, "r") as f:
            lines = f.readlines()
        lines.sort(key=lambda line: line.split(None, 1)[0] if line.strip() else "")
        with open(dates_removed_file, "w") as f:
            f.writelines(lines)

    return 0


if __name__ == "__main__":
    sys.exit(main())
