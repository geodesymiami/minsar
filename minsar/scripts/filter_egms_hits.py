#!/usr/bin/env python3
"""Filter EGMS search JSON hits locally (orbit/swath/direction/level/release).

Used by egms_download.bash after a minimal egms_search.py call that avoids
flaky API combinations (e.g. relativeOrbit + swath).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from minsar.scripts.egms_search import (
    normalize_level,
    print_hits,
    write_curl_script,
    write_json_listing,
    write_url_tsv,
)

EXAMPLE = """\
Filter EGMS archive search hits from --json-in and optionally write curl/URL lists.
"""

EPILOG = """\
Examples:
  filter_egms_hits.py --json-in egms_hits_raw.json --relativeOrbit 44 --swath IW2 --print
  filter_egms_hits.py --json-in egms_hits_raw.json --relativeOrbit 44 --swath IW2 --json-out egms_hits.json --write-curl download_egms.sh --write-urls egms_urls.tsv
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument("--json-in", metavar="FILE", required=True, help="Search result JSON from egms_search.py --json-out")
    parser.add_argument("--json-out", metavar="FILE", default=None, help="Write filtered JSON listing")
    parser.add_argument("--write-curl", metavar="FILE", default=None, help="Write curl download script for filtered hits")
    parser.add_argument("--write-urls", metavar="FILE", default=None, help="Write filename<TAB>url TSV for parallel download")
    parser.add_argument("--dir", dest="outdir", metavar="FOLDER", default="./egms", help="Default outdir embedded in curl script")
    parser.add_argument("--print", dest="do_print", action="store_true", help="Print filtered listing")
    parser.add_argument("--relativeOrbit", dest="relative_orbit", type=int, default=None, metavar="ORBIT", help="Keep hits with this relative orbit")
    parser.add_argument("--swath", default=None, metavar="SWATH", help="Keep hits with this swath (e.g. IW2)")
    parser.add_argument("--direction", default=None, metavar="DIR", help="Keep ascending or descending")
    parser.add_argument("--level", default=None, metavar="LEVEL", help="Keep product level (L2A/L2B/L3)")
    parser.add_argument("--releases", default=None, metavar="REL", help="Keep release id(s), comma-separated")
    return parser


def normalize_relative_orbit(orbit: int | str) -> str:
    """Zero-pad relative orbit for comparison (44 / 044 -> '044')."""
    s = str(orbit).strip()
    n = int(s.lstrip("0") or "0")
    return f"{n:03d}"


def hit_matches(
    hit: dict[str, Any],
    *,
    relative_orbit: int | None = None,
    swath: str | None = None,
    direction: str | None = None,
    level: str | None = None,
    releases: list[str] | None = None,
) -> bool:
    """Return True if hit matches all provided local filters."""
    if relative_orbit is not None:
        ro = hit.get("relativeOrbit")
        if ro is None:
            return False
        if normalize_relative_orbit(ro) != normalize_relative_orbit(relative_orbit):
            return False
    if swath is not None:
        if str(hit.get("swath", "")).upper() != str(swath).strip().upper():
            return False
    if direction is not None:
        if str(hit.get("direction", "")).lower() != str(direction).strip().lower():
            return False
    if level is not None:
        want = normalize_level(level)
        got = str(hit.get("productLevel", "")).upper().replace(" ", "")
        if got != want:
            return False
    if releases:
        rel = str(hit.get("release", "")).strip()
        if rel not in releases:
            return False
    return True


def filter_hits(
    result: dict[str, Any],
    *,
    relative_orbit: int | None = None,
    swath: str | None = None,
    direction: str | None = None,
    level: str | None = None,
    releases: list[str] | None = None,
) -> dict[str, Any]:
    """Return a new result dict with filtered hits (preserves query id)."""
    hits = result.get("hits") or []
    kept = [
        h
        for h in hits
        if hit_matches(
            h,
            relative_orbit=relative_orbit,
            swath=swath,
            direction=direction,
            level=level,
            releases=releases,
        )
    ]
    out = dict(result)
    out["hits"] = kept
    return out


def load_result(path: Path | str) -> dict[str, Any]:
    p = Path(path).expanduser()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {p}")
    if "hits" not in data:
        raise ValueError(f"JSON listing missing 'hits': {p}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.write_curl and not args.write_urls and not args.json_out:
        args.do_print = True

    try:
        result = load_result(args.json_in)
        releases = None
        if args.releases:
            releases = [r.strip() for r in args.releases.split(",") if r.strip()]
        level = normalize_level(args.level) if args.level else None
        filtered = filter_hits(
            result,
            relative_orbit=args.relative_orbit,
            swath=args.swath,
            direction=args.direction,
            level=level,
            releases=releases,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.do_print:
        print_hits(filtered)

    if args.json_out:
        try:
            write_json_listing(filtered, args.json_out)
            print(f"Wrote {args.json_out}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"Error: could not write JSON: {exc}", file=sys.stderr)
            return 1

    if args.write_curl:
        try:
            script = write_curl_script(filtered, args.write_curl, outdir=args.outdir or "./egms")
            print(f"Wrote {script}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"Error: could not write curl script: {exc}", file=sys.stderr)
            return 1

    if args.write_urls:
        try:
            urls = write_url_tsv(filtered, args.write_urls)
            print(f"Wrote {urls}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"Error: could not write URL list: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
