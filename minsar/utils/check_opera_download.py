#!/usr/bin/env python3
"""Check OPERA DISP-S1 downloads against CMR search; optionally delete corrupt files."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from minsar.objects import message_rsmas

DESCRIPTION = (
    "Compare OPERA*.nc in a directory to CMR search for a frame and date range. "
    "Without --delete, fail if any files are missing or corrupt. "
    "With --delete, remove corrupt files and exit 0 (missing files are listed only)."
)

EXAMPLE = """Examples:
  check_opera_download.py subsets --frame-id 23211 --start-datetime 2025-01-01 --end-datetime 2026-06-30
  check_opera_download.py subsets --frame-id 23211 --start-datetime 2025-01-01 --end-datetime 2026-06-30 --delete
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("download_dir", help="Directory of downloaded OPERA*.nc files")
    parser.add_argument("--frame-id", type=int, required=True, metavar="ID", help="DISP-S1 frame ID")
    parser.add_argument("--start-datetime", required=True, metavar="DATE", help="Start date YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-datetime", required=True, metavar="DATE", help="End date YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--delete", action="store_true", help="Remove incomplete or corrupt files and exit 0")
    return parser


def cli_date_to_datetime(value: str) -> datetime:
    """Return UTC midnight from YYYY-MM-DD or YYYYMMDD."""
    text = value.strip()
    if not text:
        raise ValueError(f"Empty date: {value!r}")
    if "-" in text:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}")
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}") from exc
    elif len(text) == 8 and text.isdigit():
        try:
            parsed = datetime.strptime(text, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}") from exc
    else:
        raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}")
    return parsed.replace(tzinfo=timezone.utc)


def expected_names(frame_id: int, start: datetime, end: datetime) -> list[str]:
    from opera_utils.disp import search

    products = search(frame_id=frame_id, start_datetime=start, end_datetime=end)
    return [Path(str(p.filename)).name for p in products]


def file_is_corrupt(path: Path) -> bool:
    """True if the NetCDF is empty, unreadable, or missing displacement."""
    import h5py

    if path.stat().st_size == 0:
        return True
    try:
        with h5py.File(path, "r") as handle:
            if "displacement" not in handle:
                return True
            _ = handle["displacement"].shape
    except (OSError, KeyError, ValueError):
        return True
    return False


def inspect_download(download_dir: Path, expected: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (missing, corrupt, unexpected) basenames."""
    on_disk = sorted(p.name for p in download_dir.glob("OPERA*.nc"))
    expected_set = set(expected)
    disk_set = set(on_disk)
    missing = sorted(expected_set - disk_set)
    unexpected = sorted(disk_set - expected_set)
    corrupt: list[str] = []
    for name in on_disk:
        if name not in expected_set:
            continue
        if file_is_corrupt(download_dir / name):
            corrupt.append(name)
    return missing, corrupt, unexpected


def run(download_dir: Path, frame_id: int, start: datetime, end: datetime, delete: bool) -> None:
    expected = expected_names(frame_id, start, end)
    missing, corrupt, unexpected = inspect_download(download_dir, expected)
    print(f"on disk: {len(list(download_dir.glob('OPERA*.nc')))}   expected: {len(expected)}")
    if unexpected:
        print("Unexpected (ignored):")
        for name in unexpected:
            print(f"  {name}")

    if delete:
        for name in corrupt:
            path = download_dir / name
            path.unlink()
            print(f"Removed incomplete/corrupt: {name}")
        if missing:
            print("Missing:")
            for name in missing:
                print(f"  {name}")
        if not corrupt and not missing:
            print("Download complete.")
        return

    if missing or corrupt:
        parts: list[str] = []
        if corrupt:
            listed = "\n".join(f"  {name}" for name in corrupt)
            parts.append(f"Incomplete/corrupt:\n{listed}")
        if missing:
            listed = "\n".join(f"  {name}" for name in missing)
            parts.append(f"Missing:\n{listed}")
        raise RuntimeError("\n".join(parts))
    print("Download complete.")


def main(iargs=None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    download_dir = Path(os.path.expandvars(inps.download_dir)).expanduser().resolve()
    if not download_dir.is_dir():
        parser.error(f"download directory not found: {download_dir}")
    try:
        start = cli_date_to_datetime(inps.start_datetime)
        end = cli_date_to_datetime(inps.end_datetime)
    except ValueError as exc:
        parser.error(str(exc))
    if end < start:
        parser.error(f"end date {end.date()} is before start date {start.date()}")

    work_dir = os.getcwd()
    message_rsmas.log(
        work_dir,
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )

    try:
        run(download_dir, inps.frame_id, start, end, inps.delete)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"Error: opera-utils disp search is required ({exc})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
