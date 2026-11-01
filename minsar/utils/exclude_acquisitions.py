#!/usr/bin/env python3
"""Load curated acquisition exclusions and filter download date lists."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from minsar.utils.sar_platform import normalize_sar_platform_token

_DEFAULT_CSV = Path(__file__).resolve().parents[1] / "exclusions" / "exclude_acquisitions.csv"


def default_csv_path() -> Path:
    return _DEFAULT_CSV


def parse_lat_sn(lat_sn: str) -> tuple[float, float]:
    """Parse ``S:N`` (same lat half as subset.lalo) into (south, north)."""
    token = lat_sn.strip()
    parts = token.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid lat_sn '{lat_sn}'. Expected S:N, e.g. -1.6:1.7.")
    south = float(parts[0])
    north = float(parts[1])
    if south > north:
        south, north = north, south
    return south, north


def lat_ranges_overlap(a_sn: tuple[float, float], b_sn: tuple[float, float]) -> bool:
    """True if closed latitude intervals overlap."""
    a_s, a_n = a_sn
    b_s, b_n = b_sn
    return not (a_n < b_s or b_n < a_s)


def parse_extent_wsen(extent_wsen) -> tuple[float, float, float, float]:
    """Parse extent as W S E N (string or 4 numbers) into floats."""
    if isinstance(extent_wsen, str):
        parts = extent_wsen.split()
    else:
        parts = list(extent_wsen)
    if len(parts) != 4:
        raise ValueError(f"extent must be W S E N (4 values); got {extent_wsen!r}")
    west, south, east, north = (float(x) for x in parts)
    if south > north:
        south, north = north, south
    return west, south, east, north


def load_exclude_rows(csv_path: Path | None = None) -> list[dict]:
    """Load exclusion rows from CSV (allows spaces after commas for readability)."""
    path = Path(csv_path) if csv_path is not None else default_csv_path()
    if not path.is_file():
        raise FileNotFoundError(f"exclude acquisitions CSV not found: {path}")
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        required = {"platform", "relativeOrbit", "date", "lat_sn"}
        if reader.fieldnames is None:
            raise ValueError(f"Empty or headerless CSV: {path}")
        fields = {name.strip() for name in reader.fieldnames}
        missing = required - fields
        if missing:
            raise ValueError(f"CSV {path} missing columns: {sorted(missing)}")
        for raw in reader:
            if not raw or all(not (v or "").strip() for v in raw.values()):
                continue
            platform = normalize_sar_platform_token(raw["platform"].strip())
            rel_orbit = int(raw["relativeOrbit"].strip())
            date_str = raw["date"].strip()
            if len(date_str) != 8 or not date_str.isdigit():
                raise ValueError(f"Invalid date '{date_str}' in {path} (expected YYYYMMDD)")
            lat_sn = raw["lat_sn"].strip()
            parse_lat_sn(lat_sn)  # validate
            note = (raw.get("note") or "").strip()
            rows.append(
                {
                    "platform": platform,
                    "relativeOrbit": rel_orbit,
                    "date": date_str,
                    "lat_sn": lat_sn,
                    "note": note,
                }
            )
    return rows


def dates_to_skip(
    platform: str,
    rel_orbit: int,
    extent_wsen,
    *,
    csv_path: Path | None = None,
) -> frozenset[str]:
    """Return YYYYMMDD dates to skip for this platform/orbit/AOI latitude."""
    plat = normalize_sar_platform_token(platform)
    _, south, _, north = parse_extent_wsen(extent_wsen)
    project_sn = (south, north)
    skipped: set[str] = set()
    for row in load_exclude_rows(csv_path):
        if row["platform"] != plat:
            continue
        if row["relativeOrbit"] != int(rel_orbit):
            continue
        if not lat_ranges_overlap(project_sn, parse_lat_sn(row["lat_sn"])):
            continue
        skipped.add(row["date"])
    return frozenset(skipped)


def filter_iso_dates(
    iso_dates,
    *,
    platform: str,
    rel_orbit: int,
    extent_wsen,
    csv_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Filter ``YYYY-MM-DD`` dates; return ``(kept, skipped)`` preserving order."""
    skip_ymd = dates_to_skip(
        platform, rel_orbit, extent_wsen, csv_path=csv_path
    )
    kept: list[str] = []
    skipped: list[str] = []
    for token in iso_dates:
        compact = token.replace("-", "")
        if compact in skip_ymd:
            skipped.append(token)
        else:
            kept.append(token)
    return kept, skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Filter ISO dates using minsar/exclusions/exclude_acquisitions.csv.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  exclude_acquisitions.py --rel-orbit 106 --extent '-92.0 -1.0 -89.0 1.0' 2026-04-01 2026-04-13
  exclude_acquisitions.py --platform S1 --rel-orbit 128 --extent '-91.2 -0.9 -91.1 -0.8' 2014-12-13
""",
    )
    parser.add_argument("--platform", default="S1", help="SAR platform token (default: S1)")
    parser.add_argument("--rel-orbit", type=int, required=True, help="Relative orbit number")
    parser.add_argument("--extent", required=True, help="Download extent as W S E N (one argument)")
    parser.add_argument("--csv", default=None, help="Override path to exclude_acquisitions.csv")
    parser.add_argument("dates", nargs="*", help="ISO dates YYYY-MM-DD to filter")
    inps = parser.parse_args(argv)

    kept, skipped = filter_iso_dates(
        inps.dates,
        platform=inps.platform,
        rel_orbit=inps.rel_orbit,
        extent_wsen=inps.extent,
        csv_path=Path(inps.csv) if inps.csv else None,
    )
    if skipped:
        print(
            "exclude_acquisitions: skipping "
            + ", ".join(skipped)
            + f" (platform={inps.platform} orbit={inps.rel_orbit} lat overlap)",
            flush=True,
        )
    for d in kept:
        print(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
