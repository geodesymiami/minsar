#!/usr/bin/env python3
"""Load curated acquisition exclusions and filter download date lists."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from minsar.utils.sar_platform import normalize_sar_platform_token

_DATE_RE = re.compile(r"^\d{8}$")
_LAT_SN_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?):([+-]?\d+(?:\.\d+)?)$")

DEFAULT_CSV = (
    Path(__file__).resolve().parents[1] / "exclusions" / "exclude_acquisitions.csv"
)


def default_csv_path() -> Path:
    """Return path to minsar/exclusions/exclude_acquisitions.csv."""
    return DEFAULT_CSV


def parse_lat_sn(lat_sn: str) -> tuple[float, float]:
    """Parse S:N latitude band; return (south, north)."""
    token = lat_sn.strip()
    match = _LAT_SN_RE.match(token)
    if not match:
        raise ValueError(f"Invalid lat_sn '{lat_sn}'. Expected S:N, e.g. -1.6:1.7.")
    south = float(match.group(1))
    north = float(match.group(2))
    if south > north:
        raise ValueError(f"Invalid lat_sn '{lat_sn}': south > north.")
    return south, north


def lat_ranges_overlap(a_sn: tuple[float, float], b_sn: tuple[float, float]) -> bool:
    """True if inclusive latitude intervals [S,N] overlap."""
    a_s, a_n = a_sn
    b_s, b_n = b_sn
    return a_s <= b_n and b_s <= a_n


def _extent_lat_sn(extent_wsen) -> tuple[float, float]:
    """Extract (S, N) from extent W S E N (iterable or whitespace string)."""
    if isinstance(extent_wsen, str):
        parts = extent_wsen.split()
    else:
        parts = list(extent_wsen)
    if len(parts) != 4:
        raise ValueError(f"extent must be W S E N (4 values); got {extent_wsen!r}")
    south = float(parts[1])
    north = float(parts[3])
    if south > north:
        south, north = north, south
    return south, north


def _iter_csv_lines(path: Path):
    """Yield (lineno, line), skipping blanks and full-line # comments."""
    with path.open(newline="", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            yield lineno, line


def load_exclude_acquisitions(csv_path: Path | None = None) -> list[dict]:
    """
    Load exclusion rows from CSV.

    Columns: platform, relativeOrbit, date, lat_sn, note (note optional).
    Blank padding around fields is stripped.
    A line whose first non-whitespace character is # is ignored.
    A row whose date starts with # is ignored.
    """
    path = Path(csv_path) if csv_path is not None else default_csv_path()
    if not path.is_file():
        raise FileNotFoundError(f"Exclusion CSV not found: {path}")

    lines = list(_iter_csv_lines(path))
    rows: list[dict] = []
    if not lines:
        return rows

    reader = csv.DictReader((line for _, line in lines), skipinitialspace=True)
    if reader.fieldnames is None:
        return rows
    fieldnames = [name.strip() for name in reader.fieldnames]
    reader.fieldnames = fieldnames
    required = {"platform", "relativeOrbit", "date", "lat_sn"}
    missing = required - set(fieldnames)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")

    for (lineno, _), raw in zip(lines[1:], reader):
        platform = (raw.get("platform") or "").strip()
        orbit_s = (raw.get("relativeOrbit") or "").strip()
        date_s = (raw.get("date") or "").strip()
        lat_sn = (raw.get("lat_sn") or "").strip()
        note = (raw.get("note") or "").strip()
        if date_s.startswith("#"):
            continue
        if not any((platform, orbit_s, date_s, lat_sn, note)):
            continue
        if not platform or not orbit_s or not date_s or not lat_sn:
            raise ValueError(f"{path}:{lineno}: incomplete row {raw!r}")
        if not _DATE_RE.match(date_s):
            raise ValueError(f"{path}:{lineno}: invalid date '{date_s}' (need YYYYMMDD)")
        try:
            orbit = int(orbit_s)
        except ValueError as exc:
            raise ValueError(f"{path}:{lineno}: invalid relativeOrbit '{orbit_s}'") from exc
        parse_lat_sn(lat_sn)  # validate
        rows.append(
            {
                "platform": normalize_sar_platform_token(platform),
                "relativeOrbit": orbit,
                "date": date_s,
                "lat_sn": lat_sn,
                "note": note,
            }
        )
    return rows


def dates_to_skip(platform: str, rel_orbit: int, extent_wsen, csv_path: Path | None = None) -> frozenset[str]:
    """Return YYYYMMDD dates to skip for this platform, orbit, and extent lat band."""
    plat = normalize_sar_platform_token(platform)
    orbit = int(rel_orbit)
    proj_lat = _extent_lat_sn(extent_wsen)
    skip: set[str] = set()
    for row in load_exclude_acquisitions(csv_path):
        if row["platform"] != plat:
            continue
        if row["relativeOrbit"] != orbit:
            continue
        if not lat_ranges_overlap(proj_lat, parse_lat_sn(row["lat_sn"])):
            continue
        skip.add(row["date"])
    return frozenset(skip)


def filter_iso_dates(iso_dates, platform: str, rel_orbit: int, extent_wsen, csv_path: Path | None = None):
    """
    Drop ISO YYYY-MM-DD dates that match an exclusion row.

    Returns (kept_iso_dates, skipped_iso_dates).
    """
    skip_ymd = dates_to_skip(platform, rel_orbit, extent_wsen, csv_path=csv_path)
    kept = []
    skipped = []
    for token in iso_dates:
        compact = token.replace("-", "")
        if compact in skip_ymd:
            skipped.append(token)
        else:
            kept.append(token)
    return kept, skipped


def main(argv=None) -> int:
    """CLI: filter ISO dates. Usage: exclude_acquisitions.py PLATFORM REL_ORBIT W S E N DATE..."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 6:
        print(
            "usage: exclude_acquisitions.py PLATFORM REL_ORBIT W S E N [YYYY-MM-DD ...]",
            file=sys.stderr,
        )
        return 2
    platform, rel_orbit, w, s, e, n, *dates = args
    kept, skipped = filter_iso_dates(dates, platform, int(rel_orbit), (w, s, e, n))
    if skipped:
        print(
            "Excluded acquisitions (platform+orbit+lat): "
            + ", ".join(skipped),
            file=sys.stderr,
        )
    for d in kept:
        print(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
