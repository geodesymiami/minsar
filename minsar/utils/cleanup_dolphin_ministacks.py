#!/usr/bin/env python3
"""Remove incomplete Dolphin ministack work dirs under */linked_phase/ before a rerun."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

FINAL_MINISTACK_RE = re.compile(r"^\d{8}_\d{8}$")
TEMP_MINISTACK_RE = re.compile(r"^\d{8}_\d{8}[a-zA-Z0-9]+$")

DESCRIPTION = (
    "Delete incomplete ministack folders under dolphin/*/linked_phase before dolphin run. "
    "Complete ministacks have similarity*.tif inside the dated folder; atomic_output temps "
    "use a random suffix (YYYYMMDD_YYYYMMDDxxxxx)."
)

EXAMPLE = """Examples:
  cleanup_dolphin_ministacks.py dolphin
  cleanup_dolphin_ministacks.py dolphin --dry-run
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "work_directory",
        type=Path,
        help="dolphin work directory (contains t*/linked_phase)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print removals without deleting",
    )
    return parser


def _is_complete_ministack_dir(path: Path, linked_phase: Path) -> bool:
    if any(path.glob("similarity*.tif")):
        return True
    return (linked_phase / f"similarity_{path.name}.tif").is_file()


def _cleanup_linked_phase(linked_phase: Path, dry_run: bool) -> list[Path]:
    removed: list[Path] = []
    if not linked_phase.is_dir():
        return removed
    for path in sorted(linked_phase.iterdir()):
        if not path.is_dir():
            continue
        name = path.name
        reason = None
        if TEMP_MINISTACK_RE.fullmatch(name):
            reason = "orphan atomic_output temp dir"
        elif FINAL_MINISTACK_RE.fullmatch(name) and not _is_complete_ministack_dir(path, linked_phase):
            reason = "missing similarity*.tif (in folder or parent linked_phase)"
        if reason is None:
            continue
        if dry_run:
            print(f"[dry-run] would remove {path} ({reason})")
        else:
            shutil.rmtree(path)
            print(f"Removed {path} ({reason})")
        removed.append(path)
    return removed


def cleanup_dolphin_ministacks(work_directory: Path, dry_run: bool = False) -> list[Path]:
    """Remove incomplete ministack dirs under all */linked_phase/ trees."""
    root = work_directory.expanduser().resolve()
    if not root.is_dir():
        return []
    removed: list[Path] = []
    for linked_phase in sorted(root.glob("*/linked_phase")):
        removed.extend(_cleanup_linked_phase(linked_phase, dry_run))
    return removed


def main(iargs: list[str] | None = None) -> int:
    args = create_parser().parse_args(iargs)
    try:
        removed = cleanup_dolphin_ministacks(args.work_directory, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not removed and not args.dry_run:
        print(f"No incomplete ministack dirs under {args.work_directory.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
