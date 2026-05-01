#!/usr/bin/env python3
"""
Create a MinSAR template file for an AOI and project name.

Runs get_sar_coverage.py --select to determine ascending/descending orbit labels,
reads a dummy template, fills in ssaraopt.relativeOrbit, miaplpy.subset.lalo,
and date range (optional: --quick-run, --period, --start-date/--end-date, or
--last-year for the full previous calendar year), writes the template to CWD.
With dual-pass ``--flight-dir`` values (``asc,desc`` default; also ``desc,asc`` or
legacy ``both``), it also runs create_opposite_orbit_template to write the
complementary pass in the same directory. With single-pass ``--flight-dir asc`` or
``desc``, only that pass is written.

AOI may be lat_min:lat_max,lon_min:lon_max (S:N,W:E), WKT POLYGON((lon lat,...)),
or other formats accepted by convert_bbox.py (e.g. GoogleEarth points).
"""

from __future__ import annotations

import argparse
import calendar
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from minsar.utils.bbox_cli_argv import (
    CREATE_TEMPLATE_ARGV_KW,
    fix_argv_for_negative_bbox_sn_we,
)
from minsar.utils.convert_bbox import _input_to_bounds
from minsar.utils.exclude_season import parse_exclude_season
from minsar.utils.sar_platform import SAR_PLATFORM_KNOWN, normalize_sar_platform_token


def _get_minsar_home() -> Path:
    """Return MINSAR_HOME or infer from script location."""
    home = os.environ.get("MINSAR_HOME")
    if home:
        return Path(home).resolve()
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent


def _get_dummy_template_path() -> Path:
    """Return path to dummy_miaplpy_1.template."""
    base = _get_minsar_home()
    candidates = [
        base / "docs" / "dummy_miaplpy_1.template",
        base / "minsar" / "docs" / "dummy_miaplpy_1.template",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _aoi_to_subset_lalo(aoi_raw: str) -> str:
    """Convert AOI (bounds, POLYGON WKT, or GoogleEarth-style) to S:N,W:E subset string."""
    min_lat, max_lat, min_lon, max_lon = _input_to_bounds(aoi_raw)
    return (
        f"{round(min_lat, 3)}:{round(max_lat, 3)},"
        f"{round(min_lon, 3)}:{round(max_lon, 3)}"
    )


def _run_get_sar_coverage(aoi: str, platform: str = "S1") -> dict[str, str | int]:
    """Run get_sar_coverage.py --platform <platform> --select and parse stdout.

    Returns dict with asc_relorbit, asc_label, desc_relorbit, desc_label,
    processing_subset (if present).
    """
    get_sar = Path(__file__).resolve().parent / "get_sar_coverage.py"
    if not get_sar.exists():
        raise FileNotFoundError(f"get_sar_coverage.py not found: {get_sar}")

    argv = [str(get_sar), aoi, "--platform", platform, "--select"]
    proc = subprocess.run(
        [sys.executable] + argv,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"get_sar_coverage.py failed (exit {proc.returncode}):\n{proc.stderr}"
        )

    result: dict[str, str | int] = {}
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "asc_relorbit":
            result["asc_relorbit"] = int(val)
        elif key == "asc_label":
            result["asc_label"] = val
        elif key == "desc_relorbit":
            result["desc_relorbit"] = int(val)
        elif key == "desc_label":
            result["desc_label"] = val
        elif key == "processing_subset":
            result["processing_subset"] = val

    required = ("asc_relorbit", "asc_label", "desc_relorbit", "desc_label")
    missing = [k for k in required if k not in result]
    if missing:
        raise RuntimeError(
            f"get_sar_coverage.py did not set: {missing}\nstdout:\n{proc.stdout}"
        )
    return result


def _quick_run_dates(year: int) -> tuple[str, str]:
    """Return (startDate, endDate) as YYYYMMDD for Jan 1 through end of Feb."""
    start = f"{year}0101"
    _, last_day = calendar.monthrange(year, 2)
    end = f"{year}02{last_day:02d}"
    return start, end


def _last_calendar_year_full_range(ref: date | None = None) -> tuple[str, str]:
    """Return (startDate, endDate) as YYYYMMDD for the full previous calendar year.

    Uses ``ref``'s calendar year minus one (default: today's date).
    """
    d = ref if ref is not None else date.today()
    y = d.year - 1
    return f"{y}0101", f"{y}1231"


def _parse_cli_date_to_yyyymmdd(s: str) -> str:
    """Normalize a user date to YYYYMMDD for ssaraopt (startDate / endDate).

    Detects format and validates the calendar day:

    - **YYYY-MM-DD** — if the string contains ``-``, three numeric parts
    - **YYYYMMDD** — eight digits, no hyphens (e.g. ``20230101``)

    Raises ValueError with a short message if the value is not valid.
    """
    t = s.strip()
    if not t:
        raise ValueError(f"Empty date: {s!r}")
    if "-" in t:
        # Disallow strptime "flex" forms like 2023-1-1 — require YYYY-MM-DD with zero-padded m/d.
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", t):
            raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {s!r}")
        try:
            dt = datetime.strptime(t, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {s!r}"
            ) from exc
        return dt.strftime("%Y%m%d")
    if len(t) == 8 and t.isdigit():
        try:
            dt = datetime.strptime(t, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(
                f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {s!r}"
            ) from exc
        return dt.strftime("%Y%m%d")
    raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {s!r}")


def _period_date_to_yyyymmdd(s: str) -> str:
    """Accept YYYYMMDD or YYYY-MM-DD; return YYYYMMDD (for --period substrings)."""
    return _parse_cli_date_to_yyyymmdd(s)


def _parse_period(period: str) -> tuple[str, str]:
    """Parse --period into (startDate, endDate) as YYYYMMDD.

    Accepts:
      YYYY — full calendar year (YYYY0101–YYYY1231)
      YYYYMMDD:YYYYMMDD
      YYYY-MM-DD:YYYY-MM-DD
    """
    period = period.strip()
    if ":" in period:
        left, _, right = period.partition(":")
        # Support YYYY-MM-DD:... where first ':' is inside date — use split once from right? 
        # Actually "2021-01-01:2022-12-31" has only one ':' between dates if we use - for dates.
        # "20210101:20221231" — single colon between dates.
        # "2021-01-01:2022-12-31" — the colon between dates is the only colon... 
        # Wait 2021-01-01 has no colon in the middle of the first date. Good.
        # Edge: "20210101:2022-12-31" — partition(":") gives left=20210101, right=2022-12-31. OK.
        start = _period_date_to_yyyymmdd(left)
        end = _period_date_to_yyyymmdd(right)
        return start, end
    if len(period) == 4 and period.isdigit():
        return f"{period}0101", f"{period}1231"
    raise ValueError(
        f"--period must be YYYY, or START:END with dates YYYYMMDD or YYYY-MM-DD; got: {period!r}"
    )


def _substitute_template(
    content: str,
    *,
    relative_orbit: int,
    subset_lalo: str,
    start_date: str | None,
    end_date: str | None,
    exclude_season: str | None,
) -> str:
    """Replace orbit/AOI/date options, optionally adding ssaraopt.excludeSeason."""
    lines = content.splitlines()
    out = []
    exclude_added = False
    exclude_matched = False
    for line in lines:
        if re.match(r"^\s*ssaraopt\.relativeOrbit\s*=", line):
            line = re.sub(r"=\s*[0-9]+", f"= {relative_orbit}", line)
        elif re.match(r"^\s*miaplpy\.subset\.lalo\s*=", line):
            line = re.sub(r"=\s*[^\s#]+", f"= {subset_lalo}", line)
        elif start_date is not None and re.match(r"^\s*ssaraopt\.startDate\s*=", line):
            line = re.sub(r"=\s*[^\s#]+", f"= {start_date}", line)
        elif end_date is not None and re.match(r"^\s*ssaraopt\.endDate\s*=", line):
            line = re.sub(r"=\s*[^\s#]+", f"= {end_date}", line)
            if exclude_season is not None:
                out.append(line)
                out.append(f"ssaraopt.excludeSeason             = {exclude_season}")
                exclude_added = True
                continue
        elif re.match(r"^\s*ssaraopt\.excludeSeason\s*=", line):
            exclude_matched = True
            if exclude_season is not None:
                line = re.sub(r"=\s*[^\s#]+", f"= {exclude_season}", line)
        out.append(line)
    if exclude_season is not None and not exclude_added and not exclude_matched:
        out.append(f"ssaraopt.excludeSeason             = {exclude_season}")
    # End with newline (same as awk output in create_opposite_orbit_template.bash).
    return "\n".join(out) + "\n"


def _run_create_opposite_orbit(
    template_path: Path,
    outdir: Path,
) -> None:
    """Run create_opposite_orbit_template.bash."""
    script = Path(__file__).resolve().parent / "create_opposite_orbit_template.bash"
    if not script.exists():
        raise FileNotFoundError(f"create_opposite_orbit_template.bash not found: {script}")

    env = os.environ.copy()
    python_bin = Path(sys.executable).resolve().parent
    env["PATH"] = f"{python_bin}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        ["bash", str(script), "--outdir", str(outdir), str(template_path)],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=env,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(
            f"create_opposite_orbit_template.bash failed (exit {proc.returncode})"
        )
    if proc.stdout:
        print(proc.stdout.rstrip())


def create_parser(
    *,
    add_help: bool = True,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a MinSAR template for an AOI. By default, also create the "
            "opposite-orbit template in the same directory."
        ),
        add_help=add_help,
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  create_template.py 36.331:36.486,25.318:25.492 Santorini
  create_template.py 36.331:36.486,25.318:25.492 Santorini --quick-run 2026
  create_template.py 36.331:36.486,25.318:25.492 Santorini --last-year
  create_template.py 36.331:36.486,25.318:25.492 Santorini --start-date 20230101 --end-date 20241231
  create_template.py 36.331:36.486,25.318:25.492 Santorini --period 20210101:20221231
  create_template.py 36.331:36.486,25.318:25.492 Santorini --exclude-season 1101-0430
  create_template.py 36.331:36.486,25.318:25.492 Santorini --flight-dir asc
  create_template.py 36.331:36.486,25.318:25.492 Santorini --platform S1
""",
    )
    parser.add_argument(
        "aoi",
        metavar="AOI",
        help=(
            "Area of interest: lat_min:lat_max,lon_min:lon_max (S:N,W:E); "
            "or WKT POLYGON((lon lat,...)) (quote in shell); "
            "or GoogleEarth-style points (see convert_bbox.py). "
            "For latitude ranges starting with a minus sign, use a leading -- or quote the AOI."
        ),
    )
    parser.add_argument(
        "name",
        help="Project name (e.g. Santorini); output will be NAME<asc_label>.template",
    )
    parser.add_argument(
        "--type",
        default="miaplpy",
        choices=["miaplpy"],
        help="Template type (default: miaplpy)",
    )
    parser.add_argument(
        "--start-date",
        metavar="DATE",
        help="Start date for ssaraopt.startDate: YYYY-MM-DD or YYYYMMDD (e.g. 20230101)",
    )
    parser.add_argument(
        "--end-date",
        metavar="DATE",
        help="End date for ssaraopt.endDate: YYYY-MM-DD or YYYYMMDD (e.g. 20241231)",
    )
    parser.add_argument(
        "--period",
        metavar="SPEC",
        help=(
            "Date range for ssaraopt: YYYY (full year); or START:END with "
            "YYYYMMDD:YYYYMMDD or YYYY-MM-DD:YYYY-MM-DD"
        ),
    )
    parser.add_argument(
        "--quick-run",
        type=int,
        metavar="YEAR",
        nargs="?",
        const=2026,
        default=None,
        help="Jan 1 to Feb 28 for the given year (default year: 2026)",
    )
    parser.add_argument(
        "--last-year",
        action="store_true",
        help=(
            "Set ssaraopt.startDate and ssaraopt.endDate to the full previous calendar year "
        ),
    )
    parser.add_argument(
        "--exclude-season",
        metavar="MMDD-MMDD",
        help="Set ssaraopt.excludeSeason, e.g. 1101-0430 to exclude November to April period",
    )
    parser.add_argument(
        "--flight-dir",
        dest="flight_dir",
        default="asc,desc",
        choices=["both", "asc", "desc", "asc,desc", "desc,asc"],
        metavar="DIR",
        help=(
            "Orbit template(s) to write: asc, desc, asc,desc, desc,asc, or both "
            "(default: asc,desc)"
        ),
    )
    parser.add_argument(
        "--platform",
        default="S1",
        metavar="NAME",
        help=(
            "Sensor for get_sar_coverage (default: S1). NISAR/Nisar and ALOS2/Alos2 are not "
            "yet implemented here; use S1 (Sentinel-1). Other accepted names match "
            "get_sar_coverage.py but may be rejected until supported."
        ),
    )
    return parser


def main(
    iargs: list[str] | None = None,
) -> tuple[int, Path | None]:
    argv = sys.argv[1:] if iargs is None else list(iargs)
    argv = fix_argv_for_negative_bbox_sn_we(
        argv,
        **CREATE_TEMPLATE_ARGV_KW,
        multiple_initial_positionals=True,
    )
    parser = create_parser()
    inps = parser.parse_args(argv)

    aoi = inps.aoi.strip()
    name = inps.name.strip()

    if inps.last_year:
        conflicts: list[str] = []
        if inps.quick_run is not None:
            conflicts.append("--quick-run")
        if inps.period is not None:
            conflicts.append("--period")
        if inps.start_date is not None or inps.end_date is not None:
            conflicts.append("--start-date/--end-date")
        if conflicts:
            print(
                f"Error: --last-year cannot be combined with: {', '.join(conflicts)}",
                file=sys.stderr,
            )
            return 1, None

    start_date = None
    end_date = None
    exclude_season = None

    if inps.exclude_season:
        try:
            parsed_exclude = parse_exclude_season(inps.exclude_season)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1, None
        if parsed_exclude:
            exclude_season = f"{parsed_exclude[0]}-{parsed_exclude[1]}"

    if inps.last_year:
        start_date, end_date = _last_calendar_year_full_range()
        y = start_date[:4]
        print(
            f"Last calendar year: {start_date} to {end_date} (full year {y})",
            file=sys.stderr,
        )
    elif inps.quick_run is not None:
        year = inps.quick_run
        start_date, end_date = _quick_run_dates(year)
        print(f"Quick-run: {start_date} to {end_date} (Jan–Feb {year})", file=sys.stderr)
    elif inps.period is not None:
        try:
            start_date, end_date = _parse_period(inps.period)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1, None
        print(f"Period: {start_date} to {end_date}", file=sys.stderr)
    else:
        if inps.start_date:
            try:
                start_date = _parse_cli_date_to_yyyymmdd(inps.start_date)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1, None
        if inps.end_date:
            try:
                end_date = _parse_cli_date_to_yyyymmdd(inps.end_date)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1, None

    platform_for_coverage = normalize_sar_platform_token(inps.platform)
    if platform_for_coverage not in SAR_PLATFORM_KNOWN:
        print(
            "Error: unknown --platform "
            f"{inps.platform!r}. Use the same names as get_sar_coverage.py "
            "(S1, Sentinel-1, Sen, NISAR/Nisar, ALOS2/ALOS).",
            file=sys.stderr,
        )
        return 1, None

    if platform_for_coverage == "NISAR":
        print(
            "Error: NISAR (or Nisar) is not yet implemented for create_template.py. "
            "Use --platform S1 (Sentinel-1) for template generation.",
            file=sys.stderr,
        )
        return 1, None

    if platform_for_coverage == "ALOS2":
        print(
            "Error: ALOS2 (or Alos2) is not yet implemented for create_template.py. "
            "Use --platform S1 (Sentinel-1) for template generation.",
            file=sys.stderr,
        )
        return 1, None

    print("Running get_sar_coverage.py --select ...", file=sys.stderr)
    coverage = _run_get_sar_coverage(aoi, platform_for_coverage)
    asc_relorbit = coverage["asc_relorbit"]
    asc_label = coverage["asc_label"]
    desc_relorbit = coverage["desc_relorbit"]
    desc_label = coverage["desc_label"]
    try:
        subset_lalo = coverage.get("processing_subset") or _aoi_to_subset_lalo(aoi)
    except ValueError as exc:
        print(f"Error: cannot derive subset.lalo from AOI: {exc}", file=sys.stderr)
        return 1, None
    print(f"  asc_label={asc_label} asc_relorbit={asc_relorbit}", file=sys.stderr)
    print(f"  desc_label={desc_label} desc_relorbit={desc_relorbit}", file=sys.stderr)

    if inps.flight_dir in ("desc", "desc,asc"):
        primary_relorbit = int(desc_relorbit)
        primary_label = str(desc_label)
    else:
        primary_relorbit = int(asc_relorbit)
        primary_label = str(asc_label)

    dummy_path = _get_dummy_template_path()
    if not dummy_path.exists():
        print(f"Error: dummy template not found: {dummy_path}", file=sys.stderr)
        return 1, None

    content = dummy_path.read_text()
    content = _substitute_template(
        content,
        relative_orbit=primary_relorbit,
        subset_lalo=subset_lalo,
        start_date=start_date,
        end_date=end_date,
        exclude_season=exclude_season,
    )

    out_base = f"{name}{primary_label}"
    out_path = Path.cwd() / f"{out_base}.template"
    out_path.write_text(content)
    print(f"Wrote {out_path}")

    if inps.flight_dir in ("both", "asc,desc", "desc,asc"):
        same_dir = out_path.parent
        print(f"Creating opposite-orbit template in {same_dir} ...", file=sys.stderr)
        _run_create_opposite_orbit(out_path, same_dir)

    return 0, out_path.resolve()


if __name__ == "__main__":
    r = main()
    if isinstance(r, tuple):
        code, _ = r
    else:
        code = r
    sys.exit(int(code))
