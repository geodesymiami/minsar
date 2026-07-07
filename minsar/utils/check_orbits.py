#!/usr/bin/env python3
"""
Check all Sentinel-1 orbit files (*.EOF) in $SENTINEL_ORBITS for corruption.

A valid orbit file is a single XML document with exactly one
``</Earth_Explorer_File>`` root element. Corrupted files are usually the result
of ``wget -c`` appending a second copy onto an already-complete file, so they
contain 2+ root elements (and roughly double the byte size). Truncated files
contain 0 root elements.

The script lists every corrupt orbit file, prints a summary of how many of each
orbit type (POEORB / RESORB, per mission S1A/S1B/S1C/S1D) were found corrupt, and
optionally removes and/or re-downloads them.

--delete   remove the corrupt orbit files
--replace  remove the corrupt orbit files and re-download each one by its exact
           name from the ASF mirror (a corrupt POEORB is replaced by a fresh
           POEORB, a corrupt RESORB by a fresh RESORB), validating that the
           download has exactly one XML root before installing it

Whenever files are removed (--delete or --replace), a log
``deleted_orbits_YYYYMMDD.txt`` (today's date) is written in the orbit directory,
one removed orbit per line with the reason and outcome.

Examples:
    check_orbits.py
    check_orbits.py --orbit-dir /path/to/S1orbits
    check_orbits.py --delete
    check_orbits.py --replace
"""

import argparse
import datetime
import glob
import os
import re
import subprocess
import sys
from collections import Counter

ROOT_CLOSE_TAG = "</Earth_Explorer_File>"
ROOT_CLOSE_BYTES = b"</Earth_Explorer_File>"
READ_CHUNK = 1 << 20  # 1 MiB

ASF_BASE_URL = "https://s1qc.asf.alaska.edu"
DOWNLOAD_TIMEOUT = 180  # seconds


def find_orbit_dir(cli_dir):
    """Resolve orbit directory from CLI arg, $SENTINEL_ORBITS, then $SENTINEL_ORBITS_DIR."""
    if cli_dir:
        return cli_dir
    for env_var in ("SENTINEL_ORBITS", "SENTINEL_ORBITS_DIR"):
        value = os.environ.get(env_var)
        if value:
            return value
    return None


def classify_orbit(basename):
    """Return a label like 'S1A_POEORB' / 'S1B_RESORB', or 'OTHER' if unrecognized."""
    mission_match = re.match(r"(S1[A-D])_", basename)
    mission = mission_match.group(1) if mission_match else "S1?"
    if "POEORB" in basename:
        otype = "POEORB"
    elif "RESORB" in basename:
        otype = "RESORB"
    else:
        otype = "OTHER"
    return "{}_{}".format(mission, otype)


def asf_url_for(basename):
    """Return the ASF download URL for an orbit filename, or None if type unknown."""
    if "POEORB" in basename:
        return "{}/aux_poeorb/{}".format(ASF_BASE_URL, basename)
    if "RESORB" in basename:
        return "{}/aux_resorb/{}".format(ASF_BASE_URL, basename)
    return None


def count_roots(path):
    """Return number of </Earth_Explorer_File> root-close tags in the file (-1 on read error).

    Reads in binary chunks (C-level bytes.count) and stops early once a second
    occurrence is seen, since we only need to distinguish 0 / 1 / 2+ roots.
    Overlap of the tag across chunk boundaries is handled with a small carry.
    """
    tag = ROOT_CLOSE_BYTES
    carry_len = len(tag) - 1
    try:
        count = 0
        prev_tail = b""
        with open(path, "rb") as f:
            while True:
                chunk = f.read(READ_CHUNK)
                if not chunk:
                    break
                buf = prev_tail + chunk
                count += buf.count(tag)
                if count >= 2:
                    return count
                prev_tail = buf[-carry_len:] if carry_len else b""
        return count
    except OSError as err:
        print("WARNING: could not read {}: {}".format(path, err), file=sys.stderr)
        return -1


def is_corrupt(root_count):
    """A healthy orbit file has exactly one root element."""
    return root_count != 1


def download_orbit(basename, orbit_dir):
    """Download an orbit file by exact name from ASF into orbit_dir.

    Uses ``wget`` (which honors the user's ~/.netrc Earthdata credentials, the
    same mechanism as run_download_orbits_asf.bash) to fetch to a temp file,
    validates it has exactly one XML root, then atomically moves it into place
    (replacing any existing file of that name). Returns (success, message).
    """
    url = asf_url_for(basename)
    if not url:
        return False, "unknown orbit type (not POEORB/RESORB)"

    dest = os.path.join(orbit_dir, basename)
    tmp = "{}.tmp.{}".format(dest, os.getpid())
    # -O writes a fresh file (no -c append), so a partial/retry can never double it.
    cmd = ["wget", "-q", "--auth-no-challenge", "-O", tmp, url]
    try:
        result = subprocess.run(cmd, timeout=DOWNLOAD_TIMEOUT)
    except FileNotFoundError:
        return False, "wget not found on PATH"
    except subprocess.TimeoutExpired:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False, "download timed out after {}s".format(DOWNLOAD_TIMEOUT)

    if result.returncode != 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False, "wget failed (exit {})".format(result.returncode)

    roots = count_roots(tmp)
    if roots != 1:
        os.remove(tmp)
        reason = "unreadable" if roots < 0 else "{} root elements".format(roots)
        return False, "downloaded file invalid ({})".format(reason)

    os.replace(tmp, dest)
    return True, "ok"


def write_deleted_log(orbit_dir, log_entries):
    """Append '<basename>  <reason>  <status>' lines to deleted_orbits_YYYYMMDD.txt."""
    if not log_entries:
        return None
    today = datetime.date.today().strftime("%Y%m%d")
    log_path = os.path.join(orbit_dir, "deleted_orbits_{}.txt".format(today))
    try:
        with open(log_path, "a") as f:
            for basename, reason, status in log_entries:
                f.write("{}  {}  {}\n".format(basename, reason, status))
    except OSError as err:
        print("WARNING: could not write log {}: {}".format(log_path, err), file=sys.stderr)
        return None
    return log_path


def main(iargs=None):
    parser = argparse.ArgumentParser(
        description="Check Sentinel-1 orbit files (*.EOF) for corruption (doubled/truncated XML).",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--orbit-dir",
        dest="orbit_dir",
        default=None,
        help="orbit directory to check (default: $SENTINEL_ORBITS)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete the corrupt orbit files that are found",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete corrupt orbit files and re-download each by exact name from ASF",
    )
    inps = parser.parse_args(iargs)

    orbit_dir = find_orbit_dir(inps.orbit_dir)
    if not orbit_dir:
        print("ERROR: no orbit directory given and $SENTINEL_ORBITS is not set.", file=sys.stderr)
        return 2
    if not os.path.isdir(orbit_dir):
        print("ERROR: orbit directory does not exist: {}".format(orbit_dir), file=sys.stderr)
        return 2

    eof_files = sorted(glob.glob(os.path.join(orbit_dir, "*.EOF")))
    total = len(eof_files)
    print("Checking {} orbit file(s) in {} ...".format(total, orbit_dir))

    corrupt = []  # list of (path, root_count)
    for path in eof_files:
        root_count = count_roots(path)
        if is_corrupt(root_count):
            corrupt.append((path, root_count))

    if corrupt:
        print("\nCorrupt orbit files ({}):".format(len(corrupt)))
        for path, root_count in corrupt:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            reason = "unreadable" if root_count < 0 else "{} root elements".format(root_count)
            print("  {}  ({}, {} bytes)".format(os.path.basename(path), reason, size))
    else:
        print("\nNo corrupt orbit files found.")

    # Per-type summary
    type_counts = Counter(classify_orbit(os.path.basename(p)) for p, _ in corrupt)
    if type_counts:
        breakdown = ", ".join("{}={}".format(k, type_counts[k]) for k in sorted(type_counts))
    else:
        breakdown = "none"
    print("\nSUMMARY: {} of {} orbit files corrupt ({})".format(len(corrupt), total, breakdown))

    if not corrupt:
        return 0

    if not (inps.delete or inps.replace):
        print("Run again with --delete to remove, or --replace to re-download, the corrupt files.")
        return 0

    # --delete and/or --replace: both remove the corrupt file; --replace also re-downloads.
    log_entries = []   # (basename, reason, status)
    deleted = 0
    replaced = 0
    replace_failed = 0

    for path, root_count in corrupt:
        basename = os.path.basename(path)
        reason = "unreadable" if root_count < 0 else "{}_roots".format(root_count)

        if inps.replace:
            ok, msg = download_orbit(basename, orbit_dir)
            if ok:
                # os.replace inside download_orbit already overwrote the corrupt file
                replaced += 1
                status = "replaced"
                print("Replaced: {}".format(basename))
            else:
                # download failed: still remove the corrupt file
                try:
                    os.remove(path)
                except OSError as err:
                    print("WARNING: could not delete {}: {}".format(path, err), file=sys.stderr)
                replace_failed += 1
                status = "replace-failed: {}".format(msg)
                print("Replace FAILED (corrupt file deleted): {} -> {}".format(basename, msg),
                      file=sys.stderr)
        else:
            try:
                os.remove(path)
                deleted += 1
                status = "deleted"
            except OSError as err:
                print("WARNING: could not delete {}: {}".format(path, err), file=sys.stderr)
                status = "delete-failed: {}".format(err)

        log_entries.append((basename, reason, status))

    log_path = write_deleted_log(orbit_dir, log_entries)

    if inps.replace:
        print("\nReplaced {} orbit file(s); {} replacement(s) failed (corrupt originals removed).".format(
            replaced, replace_failed))
    else:
        print("\nDeleted {} corrupt orbit file(s).".format(deleted))
    if log_path:
        print("Wrote log: {}".format(log_path))

    return 0


if __name__ == "__main__":
    sys.exit(main())
