#!/usr/bin/env python3
"""Create a compare folder for VolcDef_web from two product directories.

Copies ``overlay.html`` and ``index.html`` from the first directory and writes
concatenated ``insarmaps.log``, ``download_commands.txt`` (used by overlay.html
for the Data download link), and ``data_files.txt`` when present (DIR1 then DIR2).
Output directory name is always ``{product}_compare`` with no dates
(e.g. ``miaplpy_202501_202606`` → ``miaplpy_compare``).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REQUIRED_HTML = ("overlay.html", "index.html")
LOG_NAME = "insarmaps.log"
DOWNLOAD_COMMANDS = "download_commands.txt"
DATA_FILES = "data_files.txt"
PRODUCT_PREFIXES = ("miaplpy", "mintpy", "sarvey", "dolphin", "opera", "egms")


def product_prefix(dirname: str) -> str:
    """Return product family for a dir name (strip dates / suffixes).

    ``miaplpy``, ``miaplpy_202501_202606`` → ``miaplpy``;
    unknown names fall back to the full basename.
    """
    lower = (dirname or "").lower()
    for prefix in PRODUCT_PREFIXES:
        if lower == prefix or lower.startswith(prefix + "_"):
            return prefix
    return dirname


def compare_dir_name(first: Path) -> str:
    """Return output folder basename: ``miaplpy_compare``, ``mintpy_compare``, etc."""
    return f"{product_prefix(first.name)}_compare"


def resolve_product_dir(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Not a directory: {path_str}")
    return path


def read_nonempty_lines(path: Path, *, required: bool) -> list[str]:
    """Return non-empty lines (newline characters stripped)."""
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Missing {path.name}: {path}")
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line.rstrip("\n\r") for line in text.splitlines() if line.strip()]


def write_concat_text(out_path: Path, lines: list[str]) -> None:
    text = "\n".join(lines)
    if text:
        text += "\n"
    out_path.write_text(text, encoding="utf-8")


def concat_named_file(
    first: Path,
    second: Path,
    filename: str,
    *,
    required: bool,
) -> list[str]:
    """Concatenate filename from DIR1 then DIR2; return lines written."""
    lines = read_nonempty_lines(first / filename, required=required) + read_nonempty_lines(
        second / filename, required=required
    )
    return lines


def build_compare_folder(first: Path, second: Path, out_dir: Path | None = None) -> Path:
    """Create compare folder; return its path."""
    for name in REQUIRED_HTML:
        src = first / name
        if not src.is_file():
            raise FileNotFoundError(f"Missing {name} in first directory: {src}")

    log_lines = concat_named_file(first, second, LOG_NAME, required=True)
    # overlay.html fetch('download_commands.txt') — required for Data download link
    download_lines = concat_named_file(first, second, DOWNLOAD_COMMANDS, required=True)
    data_file_lines = concat_named_file(first, second, DATA_FILES, required=False)

    if out_dir is None:
        out_dir = first.parent / compare_dir_name(first)
    else:
        out_dir = Path(out_dir).expanduser().resolve()

    out_dir.mkdir(parents=True, exist_ok=True)

    for name in REQUIRED_HTML:
        shutil.copy2(first / name, out_dir / name)

    write_concat_text(out_dir / LOG_NAME, log_lines)
    write_concat_text(out_dir / DOWNLOAD_COMMANDS, download_lines)
    if data_file_lines:
        write_concat_text(out_dir / DATA_FILES, data_file_lines)

    return out_dir


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a compare folder for VolcDef_web from two product directories. "
            "Copies overlay.html and index.html from DIR1; concatenates "
            "insarmaps.log, download_commands.txt, and data_files.txt (DIR1 then DIR2) "
            "into {product}_compare (e.g. miaplpy_compare)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  compare_insarmaps.py miaplpy miaplpy_202501_202606\n"
            "  compare_insarmaps.py miaplpy_202501_202606 miaplpy\n"
            "  compare_insarmaps.py mintpy mintpy_201801_201901\n"
            "  compare_insarmaps.py /data/HDF5EOS/LaPalma/miaplpy /data/HDF5EOS/LaPalma/miaplpy_202501_202606"
        ),
    )
    parser.add_argument(
        "dir1",
        metavar="DIR1",
        help="First product directory (source of overlay.html, index.html, and first log/download entries)",
    )
    parser.add_argument(
        "dir2",
        metavar="DIR2",
        help="Second product directory (appended to insarmaps.log and download_commands.txt)",
    )
    parser.add_argument(
        "--outdir",
        metavar="DIR",
        default=None,
        help="Output directory (default: sibling miaplpy_compare / mintpy_compare / … next to DIR1)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        first = resolve_product_dir(args.dir1)
        second = resolve_product_dir(args.dir2)
        out = build_compare_folder(first, second, out_dir=args.outdir)
    except (FileNotFoundError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Created {out}")
    print(f"  overlay.html, index.html  <- {first}")
    print(f"  {LOG_NAME}, {DOWNLOAD_COMMANDS}  <- {first.name} then {second.name}")
    if (out / DATA_FILES).is_file():
        print(f"  {DATA_FILES}  <- {first.name} then {second.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
