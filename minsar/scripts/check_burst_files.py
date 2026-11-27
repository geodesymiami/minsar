#!/usr/bin/env python3
"""
Remove unreadable burst files (*.tiff, *.xml) left by burst2stack --keep-files.
A SLURM timeout can leave a truncated file that burst2safe reuses because it only
checks existence. Only dates without a .SAFE in the directory are checked.
Removed files are logged to burst_files_removed.txt, sorted by date.
"""

import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

from minsar.objects import message_rsmas

REMOVED_LOG_FILENAME = "burst_files_removed.txt"
DATE_PATTERN = re.compile(r"(\d{8})T")


def _date_from_name(basename):
    """Return YYYYMMDD from a burst or SAFE name, or None."""
    match = DATE_PATTERN.search(basename)
    return match.group(1) if match else None


def tiff_invalid_reason(path):
    """Return why a GeoTIFF is unreadable, or None. Reading the last row catches truncation."""
    from osgeo import gdal
    gdal.UseExceptions()
    ds = None
    try:
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        band.ReadAsArray(0, ds.RasterYSize - 1, ds.RasterXSize, 1)
    except Exception as e:
        return f"unreadable tiff: {str(e).splitlines()[0] if str(e) else type(e).__name__}"
    finally:
        ds = None
    return None


def xml_invalid_reason(path):
    """Return why an XML file does not parse, or None."""
    try:
        ET.parse(path)
    except ET.ParseError as e:
        return f"unreadable xml: {e}"
    return None


def invalid_reason(path):
    """Return why a burst file is unusable, or None."""
    if os.path.getsize(path) == 0:
        return "empty file"
    if path.lower().endswith((".tif", ".tiff")):
        return tiff_invalid_reason(path)
    return xml_invalid_reason(path)


def main(iargs=None):
    parser = argparse.ArgumentParser(
        description="Remove unreadable burst *.tiff/*.xml for dates without a .SAFE. Log to burst_files_removed.txt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  check_burst_files.py BURST\n  check_burst_files.py --dry-run BURST",
    )
    parser.add_argument("slc_dir", help="Directory with burst files and .SAFE dirs (e.g. BURST)")
    parser.add_argument("--dry-run", action="store_true", help="Only report files that would be removed")
    inps = parser.parse_args(args=iargs)

    input_arguments = iargs if iargs is not None else sys.argv[1:]
    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + " " + " ".join(input_arguments))

    slc_dir = inps.slc_dir
    if not os.path.isdir(slc_dir):
        print(f"ERROR: Not a directory: {slc_dir}", file=sys.stderr)
        return 1

    safe_dates = {_date_from_name(os.path.basename(p)) for p in glob.glob(os.path.join(slc_dir, "*.SAFE"))}

    candidates = []
    for pattern in ("*.tiff", "*.tif", "*.xml"):
        candidates.extend(glob.glob(os.path.join(slc_dir, pattern)))

    log_file = os.path.join(slc_dir, REMOVED_LOG_FILENAME)
    for path in sorted(candidates):
        if not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        date_str = _date_from_name(name)
        if date_str is None or date_str in safe_dates:
            continue
        reason = invalid_reason(path)
        if reason is None:
            continue
        if inps.dry_run:
            print(f"[dry-run] Would remove: {path} ({reason})")
            continue
        print(f"Removing invalid burst file: {name} ({reason})")
        try:
            os.remove(path)
        except OSError as e:
            print(f"WARNING: Could not remove {path}: {e}", file=sys.stderr)
            continue
        with open(log_file, "a") as f:
            f.write(f"{date_str}  {name}  {reason}\n")

    if not inps.dry_run and os.path.isfile(log_file):
        with open(log_file) as f:
            lines = f.readlines()
        lines.sort(key=lambda line: line.split(None, 1)[0] if line.strip() else "")
        with open(log_file, "w") as f:
            f.writelines(lines)

    return 0


if __name__ == "__main__":
    sys.exit(main())
