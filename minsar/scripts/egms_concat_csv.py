#!/usr/bin/env python3
"""Concatenate EGMS L2a/L2b burst CSV files into one CSV (streaming).

Accepts .csv and/or .zip (reads the CSV inside the zip). Files are ordered by
default west→east, then north→south using a median lon/lat sample per file.

CLMS download docs do not define CSV merge; EGMS-toolkit can merge with
optional duplicate removal — this script does a simple header-compatible row
concat for trying mosaics before wiring into egms_download.bash.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterator, TextIO

EXAMPLE = """\
Concatenate EGMS burst CSVs (or CSVs inside .zip) into one output CSV.
"""

EPILOG = """\
Examples:
  egms_concat_csv.py EGMS_L2a_044_022*_IW2_*.zip
  egms_concat_csv.py EGMS_L2a_044_022*_IW2_*.csv
  egms_concat_csv.py --dir ./egms --pattern 'EGMS_L2a_044_*_IW2_*.zip'
  egms_concat_csv.py a.zip b.zip c.zip --sort name -o custom_concat.csv
"""

FILENAME_RE = re.compile(
    r"EGMS_L(?P<level>2[ab]|3)_(?P<orbit>\d{3})_(?P<burst>\d{4})_(?P<swath>IW\d)_"
    r"(?:(?P<pol>[A-Z]{2})_(?P<yr_start>\d{4})_(?P<yr_end>\d{4}))?",
    re.IGNORECASE,
)
SWATH_NUM_RE = re.compile(r"^IW(\d+)$", re.IGNORECASE)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="FILE",
        help="Input .csv and/or .zip paths (globs expanded by the shell)",
    )
    parser.add_argument(
        "--dir",
        metavar="FOLDER",
        default=None,
        help="Directory to search when using --pattern (default: .)",
    )
    parser.add_argument(
        "--pattern",
        metavar="GLOB",
        default=None,
        help="Glob under --dir (e.g. 'EGMS_L2a_044_*_IW2_*.zip')",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Output CSV (default: S1_<asc|desc>_<orbit>_egms_<swath>_<bursts>_<pol>_<years>_concat.csv)",
    )
    parser.add_argument(
        "--flight-direction",
        choices=("A", "D", "ASC", "DESC", "asc", "desc", "ASCENDING", "DESCENDING"),
        default=None,
        help="Orbit pass for default output name (default: infer from track_angle in CSV, else asc)",
    )
    parser.add_argument(
        "--sort",
        choices=("geo", "name", "none"),
        default="geo",
        help="Input order: geo=W→E then N→S (default), name=filename, none=CLI order",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=5000,
        metavar="N",
        help="Rows sampled per file for --sort geo median lon/lat (default: 5000)",
    )
    parser.add_argument(
        "--allow-mixed",
        action="store_true",
        help="Allow mixing orbit/level/polarization (mixed IW subswaths on same orbit are OK)",
    )
    return parser


def resolve_inputs(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    for raw in args.inputs:
        p = Path(raw).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Input not found: {p}")
        paths.append(p.resolve())
    if args.pattern:
        base = Path(args.dir or ".").expanduser().resolve()
        matched = sorted(base.glob(args.pattern))
        if not matched:
            raise FileNotFoundError(f"No files match {base}/{args.pattern}")
        paths.extend(m.resolve() for m in matched)
    # de-dupe preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    if not out:
        raise SystemExit("Error: provide FILE args and/or --dir/--pattern")
    return out


def open_csv_text(path: Path) -> tuple[TextIO, Any]:
    """Return (text stream, closer) for CSV path or CSV inside zip."""
    if path.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(path)
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            zf.close()
            raise ValueError(f"No CSV inside zip: {path}")
        if len(names) > 1:
            zf.close()
            raise ValueError(f"Multiple CSVs in zip (unsupported): {path}")
        raw: BinaryIO = zf.open(names[0])  # type: ignore[assignment]
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        return text, zf
    text = path.open("r", encoding="utf-8", newline="")
    return text, text


def parse_filename_meta(path: Path) -> dict[str, str]:
    m = FILENAME_RE.search(path.name)
    if not m:
        return {}
    out = {
        "level": m.group("level").lower(),
        "orbit": m.group("orbit"),
        "burst": m.group("burst"),
        "swath": m.group("swath").upper(),
    }
    if m.group("pol"):
        out["pol"] = m.group("pol").upper()
    if m.group("yr_start"):
        out["yr_start"] = m.group("yr_start")
    if m.group("yr_end"):
        out["yr_end"] = m.group("yr_end")
    return out


def format_burst_tag(bursts: set[str]) -> str:
    """Unique burst indices in numeric order, e.g. {0220,0221,0222} → 220-221-222."""
    nums = sorted(int(b) for b in bursts)
    return "-".join(str(n) for n in nums)


def format_swath_tag(swaths: set[str]) -> str:
    """Combine IW subswaths into one tag: {IW1,IW2} → IW12 (numeric order)."""
    nums: list[int] = []
    for swath in swaths:
        m = SWATH_NUM_RE.match(swath.upper())
        if not m:
            raise ValueError(f"Unexpected swath token: {swath}")
        nums.append(int(m.group(1)))
    nums.sort()
    return "IW" + "".join(str(n) for n in nums)


def normalize_flight_direction(raw: str) -> str:
    """Return ``asc`` or ``desc`` for output filenames."""
    val = raw.strip().upper()
    if val in ("A", "ASC", "ASCENDING"):
        return "asc"
    if val in ("D", "DESC", "DESCENDING"):
        return "desc"
    raise ValueError(f"Invalid flight direction: {raw!r} (use asc/desc or A/D)")


def flight_direction_from_track_angle(track_angle: float) -> str:
    """Match egms2insarmaps / EGMS metadata: ~north → asc, ~south → desc."""
    ang = float(track_angle) % 360.0
    if ang >= 270.0 or ang < 90.0:
        return "asc"
    return "desc"


def sample_track_angle(path: Path, max_rows: int = 200) -> float | None:
    """Mean track_angle (degrees) from up to max_rows rows, if column exists."""
    text, closer = open_csv_text(path)
    try:
        reader = csv.DictReader(text)
        if not reader.fieldnames or "track_angle" not in reader.fieldnames:
            return None
        values: list[float] = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            raw = row.get("track_angle")
            if raw is None or not str(raw).strip():
                continue
            try:
                values.append(float(raw))
            except ValueError:
                continue
        if not values:
            return None
        return sum(values) / len(values)
    finally:
        text.close()
        if closer is not text:
            closer.close()


def resolve_flight_direction(paths: list[Path], cli: str | None = None) -> str:
    if cli:
        return normalize_flight_direction(cli)
    for path in paths:
        track_angle = sample_track_angle(path)
        if track_angle is not None:
            fd = flight_direction_from_track_angle(track_angle)
            print(
                f"Inferred flight direction {fd} from track_angle≈{track_angle:.1f}° ({path.name})",
                file=sys.stderr,
            )
            return fd
    print(
        "Warning: could not infer flight direction; defaulting to asc "
        "(override with --flight-direction)",
        file=sys.stderr,
    )
    return "asc"


def default_output_path(paths: list[Path], flight_direction: str = "asc") -> Path:
    """Derive Insarmaps-style concat CSV path from EGMS input filenames."""
    if not paths:
        raise ValueError("no inputs")

    parents = {p.parent for p in paths}
    if len(parents) != 1:
        return Path.cwd() / "concat.csv"
    out_dir = paths[0].parent

    metas = [parse_filename_meta(p) for p in paths]
    if not all(metas):
        return out_dir / "concat.csv"

    orbits = {m["orbit"] for m in metas}
    swaths = {m["swath"] for m in metas}
    if len(orbits) != 1:
        return out_dir / "concat.csv"

    orbit = next(iter(orbits))
    fd = normalize_flight_direction(flight_direction)
    burst_tag = format_burst_tag({m["burst"] for m in metas})
    swath_tag = format_swath_tag(swaths)

    pols = {m["pol"] for m in metas if "pol" in m}
    yr_starts = {m["yr_start"] for m in metas if "yr_start" in m}
    yr_ends = {m["yr_end"] for m in metas if "yr_end" in m}
    if len(pols) == 1 and yr_starts and yr_ends:
        pol = next(iter(pols))
        yr_start = min(yr_starts)
        yr_end = max(yr_ends)
        name = f"S1_{fd}_{orbit}_egms_{swath_tag}_{burst_tag}_{pol}_{yr_start}_{yr_end}_concat.csv"
    else:
        name = f"S1_{fd}_{orbit}_egms_{swath_tag}_{burst_tag}_concat.csv"

    return out_dir / name


def sample_lon_lat(path: Path, sample_rows: int) -> tuple[float, float]:
    """Return (median_lon, median_lat) from up to sample_rows data rows."""
    text, closer = open_csv_text(path)
    try:
        reader = csv.DictReader(text)
        if not reader.fieldnames:
            raise ValueError(f"Empty CSV header: {path}")
        lons: list[float] = []
        lats: list[float] = []
        for i, row in enumerate(reader):
            if i >= sample_rows:
                break
            lon = row.get("longitude") or row.get("Longitude")
            lat = row.get("latitude") or row.get("Latitude")
            if lon is None or lat is None:
                raise ValueError(f"Missing latitude/longitude columns: {path}")
            lons.append(float(lon))
            lats.append(float(lat))
        if not lons:
            raise ValueError(f"No data rows to sample: {path}")
        lons.sort()
        lats.sort()
        mid = len(lons) // 2
        return lons[mid], lats[mid]
    finally:
        text.close()
        if closer is not text:
            closer.close()


def sort_paths(paths: list[Path], mode: str, sample_rows: int) -> list[Path]:
    if mode == "none":
        return list(paths)
    if mode == "name":
        return sorted(paths, key=lambda p: p.name)
    # geo: west→east (lon asc), then north→south (lat desc)
    keyed: list[tuple[float, float, Path]] = []
    for p in paths:
        lon, lat = sample_lon_lat(p, sample_rows)
        keyed.append((lon, -lat, p))
        print(f"  sort geo: {p.name}  median_lon={lon:.5f}  median_lat={lat:.5f}", file=sys.stderr)
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [p for _, __, p in keyed]


def check_compatible(paths: list[Path], allow_mixed: bool) -> None:
    metas = [parse_filename_meta(p) for p in paths]
    if not any(metas):
        return
    orbits = {m.get("orbit") for m in metas if m}
    levels = {m.get("level") for m in metas if m}
    pols = {m.get("pol") for m in metas if m and m.get("pol")}
    if allow_mixed:
        return
    problems: list[str] = []
    if len(orbits) > 1:
        problems.append(f"orbit={sorted(orbits)}")
    if len(levels) > 1:
        problems.append(f"level={sorted(levels)}")
    if len(pols) > 1:
        problems.append(f"pol={sorted(pols)}")
    if problems:
        raise ValueError(
            f"Mixed products ({', '.join(problems)}). Pass --allow-mixed to override."
        )


def iter_data_rows(path: Path, expected_header: list[str]) -> Iterator[list[str]]:
    text, closer = open_csv_text(path)
    try:
        reader = csv.reader(text)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"Empty CSV: {path}")
        if header != expected_header:
            raise ValueError(
                f"Header mismatch in {path.name}:\n"
                f"  expected {len(expected_header)} cols, got {len(header)} cols"
            )
        for row in reader:
            yield row
    finally:
        text.close()
        if closer is not text:
            closer.close()


def read_header(path: Path) -> list[str]:
    text, closer = open_csv_text(path)
    try:
        reader = csv.reader(text)
        header = next(reader, None)
        if not header:
            raise ValueError(f"Empty CSV header: {path}")
        return header
    finally:
        text.close()
        if closer is not text:
            closer.close()


def concatenate(paths: list[Path], output: Path) -> int:
    header = read_header(paths[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    n_rows = 0
    with output.open("w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(header)
        for i, path in enumerate(paths, 1):
            print(f"[{i}/{len(paths)}] {path.name}", file=sys.stderr)
            for row in iter_data_rows(path, header):
                writer.writerow(row)
                n_rows += 1
    return n_rows


SCRIPT_NAME = Path(__file__).name


def work_log_path() -> Path:
    return Path.cwd() / "log"


def append_work_log(message: str) -> None:
    with open(work_log_path(), "a", encoding="utf-8") as f:
        f.write(message + "\n")


def log_session_start(argv: list[str]) -> None:
    append_work_log("####################################")
    ts = datetime.now().strftime("%Y%m%d:%H-%M")
    cmd = " ".join([SCRIPT_NAME, *argv]) if argv else SCRIPT_NAME
    append_work_log(f"{ts} * {cmd}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = create_parser()
    args = parser.parse_args(argv)
    log_session_start(argv)
    try:
        paths = resolve_inputs(args)
        check_compatible(paths, args.allow_mixed)
        print(f"Sorting {len(paths)} file(s) with --sort={args.sort}", file=sys.stderr)
        paths = sort_paths(paths, args.sort, args.sample_rows)
        print("Concat order:", file=sys.stderr)
        for p in paths:
            print(f"  {p.name}", file=sys.stderr)
        if args.output:
            out = Path(args.output).expanduser()
        else:
            flight_direction = resolve_flight_direction(paths, args.flight_direction)
            out = default_output_path(paths, flight_direction)
            print(f"Default output: {out}", file=sys.stderr)
        n_rows = concatenate(paths, out)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        append_work_log(f"Error: {exc}")
        return 1
    msg = f"Wrote {out}  ({n_rows} data rows from {len(paths)} file(s))"
    print(msg, file=sys.stderr)
    append_work_log(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
