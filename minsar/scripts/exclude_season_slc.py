#!/usr/bin/env python3
"""Move SLC date directories that fall in ssaraopt.excludeSeason into excludeSeason_<SEASON>/.

For MiaplPy / ISCE topsStack ``merged/SLC`` layouts: each acquisition is a
``YYYYMMDD`` directory. Dates whose month-day falls in the seasonal window
``MMDD-MMDD`` are moved to ``<SLC_DIR>/excludeSeason_<SEASON>/<YYYYMMDD>``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

from minsar.utils.exclude_season import date_in_exclude_season, parse_exclude_season

_DATE_DIR_RE = re.compile(r"^\d{8}$")
_EXCLUDE_SEASON_DIR_RE = re.compile(r"^excludeSeason(_|$)")

DESCRIPTION = (
    "Move SLC date directories matching a seasonal exclude window (ssaraopt.excludeSeason) "
    "from SLC_DIR into SLC_DIR/excludeSeason_<SEASON>/."
)

EPILOG = """\
Examples:
  exclude_season_slc.py merged/SLC 1015-0515
  exclude_season_slc.py merged/SLC 0101-0331 --dry-run
  exclude_season_slc.py /scratch/proj/merged/SLC 1101-0430
"""


def exclude_season_dest_name(season: str) -> str:
    """Return destination subdir name, e.g. ``excludeSeason_0101-0331``."""
    parsed = parse_exclude_season(season)
    if parsed is None:
        raise ValueError(f"Empty exclude season: {season!r}")
    start_mmdd, end_mmdd = parsed
    return f"excludeSeason_{start_mmdd}-{end_mmdd}"


def list_slc_date_dirs(slc_dir: Path) -> list[Path]:
    """Return YYYYMMDD subdirectories of ``slc_dir`` (not under excludeSeason*)."""
    if not slc_dir.is_dir():
        raise FileNotFoundError(f"SLC directory not found: {slc_dir}")
    out: list[Path] = []
    for p in sorted(slc_dir.iterdir()):
        if not p.is_dir():
            continue
        if _EXCLUDE_SEASON_DIR_RE.match(p.name):
            continue
        if _DATE_DIR_RE.match(p.name):
            try:
                dt.datetime.strptime(p.name, "%Y%m%d")
            except ValueError:
                continue
            out.append(p)
    return out


def move_exclude_season_slc(
    slc_dir: Path,
    season: str,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Move date dirs in ``season`` (MMDD-MMDD) to ``slc_dir/excludeSeason_<SEASON>``.

    Returns sorted list of YYYYMMDD names that were (or would be) moved.
    """
    parsed = parse_exclude_season(season)
    if parsed is None:
        raise ValueError(f"Empty exclude season: {season!r}")
    start_mmdd, end_mmdd = parsed

    slc_dir = Path(slc_dir).resolve()
    dest_subdir = exclude_season_dest_name(season)
    dest_root = slc_dir / dest_subdir
    moved: list[str] = []

    for date_dir in list_slc_date_dirs(slc_dir):
        date_obj = dt.datetime.strptime(date_dir.name, "%Y%m%d").date()
        if not date_in_exclude_season(date_obj, start_mmdd, end_mmdd):
            continue
        dest = dest_root / date_dir.name
        moved.append(date_dir.name)
        if dry_run:
            print(f"Would move {date_dir} -> {dest}")
            continue
        if dest.exists():
            raise FileExistsError(f"Destination already exists: {dest}")
        dest_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(date_dir), str(dest))
        print(f"Moved {date_dir.name} -> {dest_subdir}/{date_dir.name}")

    return moved


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slc_dir", metavar="SLC_DIR", help="SLC directory with YYYYMMDD subdirs (e.g. merged/SLC)")
    parser.add_argument("season", metavar="SEASON", help="Exclude window MMDD-MMDD (e.g. 1015-0515), same as ssaraopt.excludeSeason")
    parser.add_argument("--dry-run", action="store_true", help="Print moves without changing the filesystem")
    return parser


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        moved = move_exclude_season_slc(Path(inps.slc_dir), inps.season, dry_run=inps.dry_run)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not moved:
        print(f"No date directories in {inps.slc_dir} match season {inps.season}")
    else:
        action = "Would move" if inps.dry_run else "Moved"
        print(f"{action} {len(moved)} date director{'y' if len(moved) == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
