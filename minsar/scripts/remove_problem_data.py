#!/usr/bin/env python3
"""
Remove Sentinel-1 acquisitions affected by degraded burst synchronisation
(MPC Quality Disclaimer #273).

Identifies acquisitions between 2025-04-29 19:40:10 and 2025-05-01 19:33:34
in the given SLC directory and removes them (SAFE dirs, zip, xml, BURST.tiff).

References:
  - https://sar-mpc.eu/disclaimers/273/
  - https://github.com/isce-framework/isce2/discussions/986#discussioncomment-14405193
"""

import argparse
import glob
import os
import re
import shutil
import sys
from datetime import datetime

from minsar.objects import message_rsmas

# MPC Quality Disclaimer #273 validity window
WINDOW_START = datetime(2025, 4, 29, 19, 40, 10)
WINDOW_END = datetime(2025, 5, 1, 19, 33, 34)

DISCLAIMER_URL = "https://sar-mpc.eu/disclaimers/273/"
ISCE2_DISCUSSION_URL = "https://github.com/isce-framework/isce2/discussions/986#discussioncomment-14405193"

EPILOG = f"""
These data are removed because of burst synchronisation issues documented in:
  {DISCLAIMER_URL}
  {ISCE2_DISCUSSION_URL}

MPC Quality Disclaimer #273: Products with degraded burst synchronisation
(validity: 2025-04-29 19:40:10 to 2025-05-01 19:33:34). Processing such data
can cause incoherent stripes in interferograms; see the ISCE2 discussion for
details.
"""


def _timestamp_from_filename(basename):
    """
    Extract first YYYYMMDDTHHMMSS from Sentinel-1 filename.
    Handles: SAFE, zip, xml, BURST.tiff.
    """
    match = re.search(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})", basename)
    if not match:
        return None
    try:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
        )
    except (ValueError, IndexError):
        return None


def _in_window(dt):
    """True if dt is within the MPC #273 validity window (inclusive)."""
    if dt is None:
        return False
    return WINDOW_START <= dt <= WINDOW_END


def _find_affected(slc_dir):
    """Return list of (path, basename) for files/dirs to remove."""
    affected = []
    patterns = [
        ("*.SAFE", os.path.isdir),
        ("*.zip", os.path.isfile),
        ("*.xml", os.path.isfile),
        ("*BURST.tiff", os.path.isfile),
    ]
    for pattern, check in patterns:
        for path in glob.glob(os.path.join(slc_dir, pattern)):
            if not check(path):
                continue
            basename = os.path.basename(path)
            dt = _timestamp_from_filename(basename)
            if _in_window(dt):
                affected.append((path, basename))
    return affected


def main(iargs=None):
    parser = argparse.ArgumentParser(
        description="Remove Sentinel-1 acquisitions with degraded burst sync (MPC #273)",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slc_dir",
        help="SLC directory containing .SAFE dirs, .zip, .xml, *BURST.tiff",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed; do not remove anything",
    )
    inps = parser.parse_args(args=iargs)

    if iargs is not None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1:]
    try:
        message_rsmas.log(os.getcwd(), os.path.basename(__file__) + " " + " ".join(input_arguments))
    except (TypeError, AttributeError):
        pass

    slc_dir = inps.slc_dir
    if not os.path.isdir(slc_dir):
        print(f"ERROR: Not a directory: {slc_dir}", file=sys.stderr)
        return 1

    affected = _find_affected(slc_dir)
    if not affected:
        print("Nothing to remove.")
        return 0

    if inps.dry_run:
        # Unique dates from affected items
        unique_dates = set()
        for _, basename in affected:
            dt = _timestamp_from_filename(basename)
            if dt:
                unique_dates.add(dt.strftime("%Y-%m-%d"))
        # Show only .SAFE dirs and .zip files in dry-run output (not .xml, *BURST.tiff)
        display_basenames = []
        for path, basename in sorted(affected, key=lambda x: x[1]):
            if basename.endswith(".SAFE") and os.path.isdir(path):
                display_basenames.append(basename)
            elif basename.endswith(".zip"):
                display_basenames.append(basename)
        msg = f"[dry-run] Would remove {len(unique_dates)} date(s):"
        if display_basenames:
            msg += f" {', '.join(display_basenames)}"
        else:
            msg += " (auxiliary files only, e.g. .xml, *BURST.tiff)"
        print(msg)
        return 0

    # Group by date; prefer .SAFE then .zip for the single "Removed:" line per date
    by_date = {}
    for path, basename in affected:
        dt = _timestamp_from_filename(basename)
        date_key = dt.strftime("%Y-%m-%d") if dt else "__no_date__"
        by_date.setdefault(date_key, []).append((path, basename))
    for date_key in sorted(by_date):
        items = by_date[date_key]
        # Prefer .SAFE, then .zip, else first basename for the printed line
        display_basename = None
        for path, basename in items:
            if basename.endswith(".SAFE") and os.path.isdir(path):
                display_basename = basename
                break
        if display_basename is None:
            for path, basename in items:
                if basename.endswith(".zip"):
                    display_basename = basename
                    break
        if display_basename is None:
            display_basename = items[0][1]
        for path, basename in items:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except Exception as e:
                print(f"WARNING: Could not remove {path}: {e}", file=sys.stderr)
        print(f"Removed: {display_basename}")
    num_dates = len([k for k in by_date if k != "__no_date__"])
    print(f"Removed {num_dates} date(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
