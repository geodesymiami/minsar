#!/usr/bin/env python3
"""
Create a MinSAR template file for an AOI and project name.

Runs get_sar_coverage.py --select to determine ascending/descending orbit labels,
reads a dummy template, fills in ssaraopt.relativeOrbit, miaplpy.subset.lalo,
and date range (optional: --quick-run, --period, --start-date/--end-date, or
--last-year for the full previous calendar year), writes the template to CWD,
then creates the opposite-orbit template in AUTO_TEMPLATES.

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
from datetime import date
from pathlib import Path

from minsar.utils.bbox_cli_argv import (
    CREATE_TEMPLATE_ARGV_KW,
    fix_argv_for_negative_bbox_sn_we,
)
from minsar.utils.convert_bbox import _input_to_bounds


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


def _run_get_sar_coverage(aoi: str) -> dict[str, str | int]:
    """Run get_sar_coverage.py --platform S1 --select and parse stdout.

    Returns dict with asc_relorbit, asc_label, desc_relorbit, desc_label,
    processing_subset (if present).
    """
    get_sar = Path(__file__).resolve().parent / "get_sar_coverage.py"
    if not get_sar.exists():
        raise FileNotFoundError(f"get_sar_coverage.py not found: {get_sar}")

    argv = [str(get_sar), aoi, "--platform", "S1", "--select"]
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


def _parse_date_yyyy_mm_dd(s: str) -> str:
    """Convert YYYY-MM-DD to YYYYMMDD."""
    parts = s.split("-")
    if len(parts) != 3:
        raise ValueError(f"Expected YYYY-MM-DD, got: {s}")
    return f"{parts[0]}{parts[1]}{parts[2]}"


def _period_date_to_yyyymmdd(s: str) -> str:
    """Accept YYYYMMDD or YYYY-MM-DD; return YYYYMMDD."""
    t = s.strip().replace("-", "")
    if len(t) != 8 or not t.isdigit():
        raise ValueError(
            f"Invalid date in period (use YYYYMMDD or YYYY-MM-DD): {s!r}"
        )
    return t


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
) -> str:
    """Replace ssaraopt.relativeOrbit, miaplpy.subset.lalo, and dates in template."""
    lines = content.splitlines()
    out = []
    for line in lines:
        if re.match(r"^\s*ssaraopt\.relativeOrbit\s*=", line):
            line = re.sub(r"=\s*[0-9]+", f"= {relative_orbit}", line)
        elif re.match(r"^\s*miaplpy\.subset\.lalo\s*=", line):
            line = re.sub(r"=\s*[^\s#]+", f"= {subset_lalo}", line)
        elif start_date is not None and re.match(r"^\s*ssaraopt\.startDate\s*=", line):
            line = re.sub(r"=\s*[^\s#]+", f"= {start_date}", line)
        elif end_date is not None and re.match(r"^\s*ssaraopt\.endDate\s*=", line):
            line = re.sub(r"=\s*[^\s#]+", f"= {end_date}", line)
        out.append(line)
    return "\n".join(out)


def _get_auto_templates_dir() -> Path:
    """Return AUTO_TEMPLATES directory for opposite-orbit template."""
    auto = os.environ.get("AUTO_TEMPLATES")
    if auto:
        return Path(auto).resolve()
    templates = os.environ.get("TEMPLATES")
    if templates:
        return Path(templates).resolve().parent / "AUTO_TEMPLATES"
    return Path.cwd() / "AUTO_TEMPLATES"


def _run_create_opposite_orbit(
    template_path: Path,
    outdir: Path,
) -> None:
    """Run create_opposite_orbit_template.bash."""
    script = Path(__file__).resolve().parent / "create_opposite_orbit_template.bash"
    if not script.exists():
        raise FileNotFoundError(f"create_opposite_orbit_template.bash not found: {script}")

    env = os.environ.copy()
    env["AUTO_TEMPLATES"] = str(outdir)
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


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a MinSAR template for an AOI, then the opposite-orbit template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  create_template.py 36.331:36.486,25.318:25.492 Santorini
  create_template.py 36.331:36.486,25.318:25.492 Santorini --quick-run 2026
  create_template.py -23.393:-23.097,-68.356:-68.175 Atacama --quick-run 2026
  create_template.py -- -23.393:-23.097,-68.356:-68.175 Atacama   # same (explicit --)
  create_template.py 36.331:36.486,25.318:25.492 Santorini --start-date 2020-01-01 --end-date 2024-12-31
  create_template.py 36.331:36.486,25.318:25.492 Santorini --period 2024
  create_template.py 36.331:36.486,25.318:25.492 Santorini --period 20210101:20221231
  create_template.py 36.331:36.486,25.318:25.492 Santorini --period 2021-01-01:2022-12-31
  create_template.py 36.331:36.486,25.318:25.492 Santorini --last-year
  create_template.py "POLYGON((25.3058 36.3221,25.5015 36.3221,25.5015 36.5019,25.3058 36.5019,25.3058 36.3221))" Santorini
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
        metavar="YYYY-MM-DD",
        help="Start date for ssaraopt.startDate",
    )
    parser.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        help="End date for ssaraopt.endDate",
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
        help="Use Jan 1 - end Feb for the given year (default year: 2026)",
    )
    parser.add_argument(
        "--last-year",
        action="store_true",
        help=(
            "Set ssaraopt.startDate and ssaraopt.endDate to the full previous calendar year "
            "(YYYYMMDD Jan 1 through Dec 31). Mutually exclusive with --quick-run, --period, "
            "and --start-date / --end-date."
        ),
    )
    return parser


def main(iargs: list[str] | None = None) -> int:
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
            return 1

    start_date = None
    end_date = None

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
            return 1
        print(f"Period: {start_date} to {end_date}", file=sys.stderr)
    else:
        if inps.start_date:
            start_date = _parse_date_yyyy_mm_dd(inps.start_date)
        if inps.end_date:
            end_date = _parse_date_yyyy_mm_dd(inps.end_date)

    print("Running get_sar_coverage.py --select ...", file=sys.stderr)
    coverage = _run_get_sar_coverage(aoi)
    asc_relorbit = coverage["asc_relorbit"]
    asc_label = coverage["asc_label"]
    try:
        subset_lalo = coverage.get("processing_subset") or _aoi_to_subset_lalo(aoi)
    except ValueError as exc:
        print(f"Error: cannot derive subset.lalo from AOI: {exc}", file=sys.stderr)
        return 1
    print(f"  asc_label={asc_label} asc_relorbit={asc_relorbit}", file=sys.stderr)

    dummy_path = _get_dummy_template_path()
    if not dummy_path.exists():
        print(f"Error: dummy template not found: {dummy_path}", file=sys.stderr)
        return 1

    content = dummy_path.read_text()
    content = _substitute_template(
        content,
        relative_orbit=int(asc_relorbit),
        subset_lalo=subset_lalo,
        start_date=start_date,
        end_date=end_date,
    )

    out_base = f"{name}{asc_label}"
    out_path = Path.cwd() / f"{out_base}.template"
    out_path.write_text(content)
    print(f"Wrote {out_path}")

    auto_dir = _get_auto_templates_dir()
    auto_dir.mkdir(parents=True, exist_ok=True)
    print(f"Creating opposite-orbit template in {auto_dir} ...", file=sys.stderr)
    _run_create_opposite_orbit(out_path, auto_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
