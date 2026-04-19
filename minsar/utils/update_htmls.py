#!/usr/bin/env python3
"""
Copy minsar/html/overlay.html into volcdef data directories.

Two modes (use one):

1) Excel (default): read URLs from the first column of
   tools/webconfig/Holocene_Volcanoes_volcdef_cfg.xlsx (or --xlsx).
   Only destinations whose URL path contains /mintpy or /miaplpy are used.

2) JSON (legacy): pass --volcanoes-json to read volcanoes[].volcdef_link
   from volcanoes.json and also copy matrix.html (same behavior as before).

Optional --base prepends a filesystem root to URL paths.

Destination directories must already exist; this script does not create them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

# minsar/minsar/utils/update_htmls.py -> repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# Prefer MINSAR_HOME when set (matches deployed tree); else repo checkout root
_ROOT = Path(os.environ.get("MINSAR_HOME", str(_REPO_ROOT)))
_DEFAULT_XLSX = _ROOT / "tools" / "webconfig" / "Holocene_Volcanoes_volcdef_cfg.xlsx"


def _dest_dirs_from_xlsx(
    xlsx_path: Path,
    skip_rows: int,
    base: Path | None,
) -> list[Path]:
    import pandas as pd

    df = pd.read_excel(xlsx_path, skiprows=skip_rows)
    if df.shape[1] < 1:
        return []

    col0 = df.iloc[:, 0]
    seen: set[str] = set()
    dest_dirs: list[Path] = []

    for val in col0:
        if pd.isna(val):
            continue
        s = str(val).strip()
        if not s.startswith(("http://", "https://")):
            continue
        parsed = urlparse(s)
        path = (parsed.path or "").rstrip("/")
        if not path:
            continue
        low = path.lower()
        if "/mintpy" not in low and "/miaplpy" not in low:
            continue
        if path in seen:
            continue
        seen.add(path)
        if base is not None:
            dest = (base / path.lstrip("/")).resolve()
        else:
            dest = Path(path)
        dest_dirs.append(dest)

    return dest_dirs


def _dest_dirs_from_volcanoes_json(volcanoes_path: Path, base: Path | None) -> list[Path]:
    with open(volcanoes_path, encoding="utf-8") as f:
        data = json.load(f)

    volcanoes = data.get("volcanoes") or []
    seen: set[str] = set()
    dest_dirs: list[Path] = []

    for v in volcanoes:
        link = v.get("volcdef_link")
        if not link or not isinstance(link, str) or not link.strip():
            continue
        link = link.strip()
        if not link.startswith(("http://", "https://")):
            continue
        parsed = urlparse(link)
        path = (parsed.path or "").rstrip("/")
        if not path or path in seen:
            continue
        seen.add(path)
        if base is not None:
            dest = (base / path.lstrip("/")).resolve()
        else:
            dest = Path(path)
        dest_dirs.append(dest)

    return dest_dirs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy overlay.html into volcdef_link dirs (from Holocene xlsx or volcanoes.json)."
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=None,
        help=f"Holocene Excel with URLs in column A (default: {_DEFAULT_XLSX})",
    )
    parser.add_argument(
        "--volcanoes-json",
        type=Path,
        default=None,
        help="Use volcanoes.json volcdef_link entries instead of --xlsx (also copies matrix.html).",
    )
    parser.add_argument(
        "--skip-rows",
        type=int,
        default=1,
        help="Rows to skip at top of Excel (default: 1, matching Holocene_volcanoes exports).",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="Filesystem root prepended to URL paths (e.g. /var/www)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without copying",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    minsar_html = script_dir.parent / "html"
    overlay_src = minsar_html / "overlay.html"
    matrix_src = minsar_html / "matrix.html"

    if not overlay_src.is_file():
        parser.error(f"Source not found: {overlay_src}")

    use_json = args.volcanoes_json is not None
    if use_json and args.xlsx is not None:
        parser.error("Use either --volcanoes-json or --xlsx, not both.")

    if use_json:
        volcanoes_path = args.volcanoes_json.resolve()
        if not volcanoes_path.is_file():
            parser.error(f"Not a file: {volcanoes_path}")
        dest_dirs = _dest_dirs_from_volcanoes_json(volcanoes_path, args.base)
        copy_matrix = True
    else:
        xlsx_path = (args.xlsx or _DEFAULT_XLSX).resolve()
        if not xlsx_path.is_file():
            parser.error(
                f"Excel not found: {xlsx_path}\n"
                f"Set --xlsx or place Holocene_Volcanoes_volcdef_cfg.xlsx under tools/webconfig/."
            )
        dest_dirs = _dest_dirs_from_xlsx(xlsx_path, args.skip_rows, args.base)
        copy_matrix = False
        if not dest_dirs:
            print(
                f"No http(s) URLs in column A pointing to paths with /mintpy or /miaplpy "
                f"(file: {xlsx_path}, skip_rows={args.skip_rows}).",
                file=sys.stderr,
            )
            return 1

    if copy_matrix and not matrix_src.is_file():
        parser.error(f"Source not found: {matrix_src}")

    if not dest_dirs:
        return 0

    if args.dry_run:
        if copy_matrix:
            print("Would copy overlay.html, matrix.html, index.html into:")
        else:
            print("Would copy overlay.html, index.html into:")
    else:
        if copy_matrix:
            print("Copying overlay.html, matrix.html, index.html into:")
        else:
            print("Copying overlay.html, index.html into:")
    for dest_dir in dest_dirs:
        print(f"  {dest_dir}")

    if args.dry_run:
        return 0

    for dest_dir in dest_dirs:
        shutil.copy2(overlay_src, dest_dir / "overlay.html")
        shutil.copy2(dest_dir / "overlay.html", dest_dir / "index.html")
        if copy_matrix:
            shutil.copy2(matrix_src, dest_dir / "matrix.html")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
