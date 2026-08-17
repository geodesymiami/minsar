#!/usr/bin/env python3
"""Move SLC date directories that fall in seasonal exclude windows into ex.../.

For MiaplPy / ISCE topsStack ``merged/SLC`` layouts: each acquisition is a
``YYYYMMDD`` directory. Dates whose month-day falls in any seasonal window
``MMDD-MMDD`` are moved to a single quarantine folder under ``SLC_DIR``:

- one window: ``exMMDD-MMDD/``
- multiple windows: ``exMMDD-MMDD_MMDD-MMDD/`` (e.g. ``ex1101-1215_0315-0430/``)
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

from minsar.utils.exclude_season import (
    date_in_exclude_season,
    exclude_seasons_dir_name,
    parse_exclude_season,
)

_DATE_DIR_RE = re.compile(r"^\d{8}$")
_EXCLUDE_SEASON_DIR_RE = re.compile(r"^ex[0-9]{4}-[0-9]{4}(_[0-9]{4}-[0-9]{4})*$")

DESCRIPTION = (
    "Move SLC date directories matching one or more seasonal exclude windows "
    "from SLC_DIR into a single quarantine folder (exMMDD-MMDD or ex..._...)."
)

EPILOG = """\
Examples:
  exclude_season_slc.py merged/SLC 1015-0515
  exclude_season_slc.py merged/SLC 1101-1215 0315-0430
  exclude_season_slc.py merged/SLC 0101-0331 --dry-run
  exclude_season_slc.py /scratch/proj/merged/SLC 1101-0430
"""


def exclude_season_dest_name(seasons: str | list[str]) -> str:
    """Return destination subdir name for one or more exclude windows."""
    if isinstance(seasons, str):
        return exclude_seasons_dir_name([seasons])
    return exclude_seasons_dir_name(seasons)


def list_slc_date_dirs(slc_dir: Path) -> list[Path]:
    """Return YYYYMMDD subdirectories of ``slc_dir`` (not under exclude quarantine dirs)."""
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
    seasons: str | list[str],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Move date dirs matching any window into one ``slc_dir/ex.../`` folder.

    Returns sorted list of YYYYMMDD names that were (or would be) moved.
    """
    season_list = [seasons] if isinstance(seasons, str) else list(seasons)
    if not season_list:
        raise ValueError("No exclude seasons given")

    parsed_seasons: list[tuple[str, str]] = []
    for season in season_list:
        parsed = parse_exclude_season(season)
        if parsed is None:
            raise ValueError(f"Empty exclude season: {season!r}")
        parsed_seasons.append(parsed)

    slc_dir = Path(slc_dir).resolve()
    dest_subdir = exclude_season_dest_name(season_list)
    dest_root = slc_dir / dest_subdir
    moved: list[str] = []

    for date_dir in list_slc_date_dirs(slc_dir):
        date_obj = dt.datetime.strptime(date_dir.name, "%Y%m%d").date()
        if not any(
            date_in_exclude_season(date_obj, start_mmdd, end_mmdd)
            for start_mmdd, end_mmdd in parsed_seasons
        ):
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
    parser.add_argument(
        "seasons",
        metavar="SEASON",
        nargs="+",
        help="One or more exclude windows MMDD-MMDD (e.g. 1101-1215 0315-0430)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print moves without changing the filesystem")
    return parser


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        moved = move_exclude_season_slc(Path(inps.slc_dir), inps.seasons, dry_run=inps.dry_run)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not moved:
        seasons_str = ", ".join(inps.seasons)
        print(f"No date directories in {inps.slc_dir} match season(s) {seasons_str}")
    else:
        action = "Would move" if inps.dry_run else "Moved"
        print(f"{action} {len(moved)} date director{'y' if len(moved) == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
