#!/usr/bin/env python3
"""
Copy overlay.html and matrix.html from minsar/html into each volcdef_link
destination directory, then copy overlay.html to index.html in each dir.

Reads volcanoes.json (required positional argument), finds all "volcdef_link"
URLs (e.g. "http://149.165.154.65/data/HDF5EOS/CerroAzul/mintpy"), uses the
URL path as the destination directory (/data/HDF5EOS/CerroAzul/mintpy).
Optional --base prepends a root so destinations are base + path.
"""

import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser(
        description="Copy overlay.html and matrix.html into volcdef_link dirs; copy overlay to index.html."
    )
    parser.add_argument(
        "volcanoes_json",
        type=Path,
        help="Path to volcanoes.json (must contain volcanoes[].volcdef_link URLs)",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="Base directory for destination paths (default: use URL path as-is)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without copying",
    )
    args = parser.parse_args()

    volcanoes_path = args.volcanoes_json.resolve()
    if not volcanoes_path.is_file():
        parser.error(f"Not a file: {volcanoes_path}")

    with open(volcanoes_path, encoding="utf-8") as f:
        data = json.load(f)

    volcanoes = data.get("volcanoes") or []
    links = []
    for v in volcanoes:
        link = v.get("volcdef_link")
        if not link or not isinstance(link, str) or not link.strip():
            continue
        link = link.strip()
        if not link.startswith(("http://", "https://")):
            continue
        links.append(link)

    # Unique dirs (same path with/without trailing slash -> one dir)
    seen = set()
    dest_dirs = []
    for link in links:
        parsed = urlparse(link)
        path = (parsed.path or "").rstrip("/")
        if not path or path in seen:
            continue
        seen.add(path)
        if args.base is not None:
            dest = (args.base / path.lstrip("/")).resolve()
        else:
            dest = Path(path)
        dest_dirs.append(dest)

    # Source files: minsar/html/overlay.html and minsar/html/matrix.html
    script_dir = Path(__file__).resolve().parent
    minsar_html = script_dir.parent / "html"
    overlay_src = minsar_html / "overlay.html"
    matrix_src = minsar_html / "matrix.html"

    if not overlay_src.is_file():
        parser.error(f"Source not found: {overlay_src}")
    if not matrix_src.is_file():
        parser.error(f"Source not found: {matrix_src}")

    for dest_dir in dest_dirs:
        if args.dry_run:
            print(f"[dry-run] would create {dest_dir}")
            print(f"  copy {overlay_src} -> {dest_dir / 'overlay.html'}")
            print(f"  copy {matrix_src} -> {dest_dir / 'matrix.html'}")
            print(f"  copy {dest_dir / 'overlay.html'} -> {dest_dir / 'index.html'}")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(overlay_src, dest_dir / "overlay.html")
        shutil.copy2(matrix_src, dest_dir / "matrix.html")
        shutil.copy2(dest_dir / "overlay.html", dest_dir / "index.html")
        print(f"Updated {dest_dir}")

    if not args.dry_run and dest_dirs:
        print(f"Done: {len(dest_dirs)} director{'y' if len(dest_dirs) == 1 else 'ies'}.")


if __name__ == "__main__":
    main()
