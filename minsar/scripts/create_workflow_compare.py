#!/usr/bin/env python3
"""Write a bash driver to set up SAFE, CSLC Dolphin presets, DISP-S1, and MiaplPy compare runs."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import stat
import sys
from pathlib import Path

from minsar.objects import message_rsmas
from minsar.utils.bbox_cli_argv import fix_argv_for_negative_bbox_sn_we

COMPARE_SUFFIXES = (
    "CSLCDOLPHINSTANDARD",
    "CSLCDOLPHINAUTO",
    "CSLCDOLPHIN-STANDARD",
    "CSLCDOLPHIN-AUTO",
    "CSLCSTANDARD",
    "CSLCAUTO",
    "SAFE",
    "DISP",
    "ISCE2",
    "MIAPLPY",
    "I",
)
ARGV_FIX_KW = {
    "consume_one": (
        "--flight-dir",
        "--start",
        "--start-date",
        "--end",
        "--end-date",
        "--track",
        "--frame-id",
        "--output",
    ),
    "consume_two": (),
    "flags": ("--run",),
}

DESCRIPTION = (
    "Write a bash script with create_isce3_runfiles.py --run (--safe, --data-type cslc with "
    "--preset auto or standard, --disp-S1) and minsarApp.bash (--no-mintpy --miaplpy) "
    "for the same AOI and dates. Each pipeline uses a separate project name under $SCRATCHDIR."
)

EXAMPLE = """Examples:
  create_workflow_compare.py 19.4:19.54,-155.02:-154.80 qqHawaiiPuna --flight-dir desc --start 20250101 --end 20250630
  create_workflow_compare.py 19.4:19.54,-155.02:-154.80 qqHawaiiPuna --flight-dir desc --start 20250101 --end 20250630 --output qqHawaiiPuna_compare.bash
  create_workflow_compare.py 19.4:19.54,-155.02:-154.80 qqHawaiiPuna --flight-dir desc --start 20250101 --end 20250630 --run
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("aoi", metavar="AOI", help="area of interest (S:N,W:E bounds or WKT POLYGON)")
    parser.add_argument(
        "name",
        help="project base name; SAFE/CSLCAuto/CSLCStandard/DISP/I suffixes are appended",
    )
    parser.add_argument("--flight-dir", choices=("asc", "desc"), required=True, help="orbit pass for AOI-based setup")
    parser.add_argument("--start-date", "--start", dest="start_date", required=True, metavar="DATE", help="first date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end-date", "--end", dest="end_date", required=True, metavar="DATE", help="last date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--track", type=int, help="relative orbit (passed to create_isce3_runfiles.py)")
    parser.add_argument("--frame-id", type=int, help="OPERA DISP-S1 frame ID (passed to create_isce3_runfiles.py)")
    parser.add_argument("--output", type=Path, help="bash driver path (default: <base>_compare.bash in cwd)")
    parser.add_argument(
        "--run",
        action="store_true",
        help="after writing the driver, run the create_isce3_runfiles.py commands",
    )
    return parser


def normalize_base_name(name: str) -> str:
    """Strip a trailing pipeline suffix so qqHawaiiPunaSAFE and qqHawaiiPuna both work."""
    for suffix in COMPARE_SUFFIXES:
        if name.upper().endswith(suffix):
            return name[: -len(suffix)]
    return name


def project_names(base: str) -> dict[str, str]:
    """Return scratch project names for each compare pipeline."""
    stem = normalize_base_name(base)
    return {
        "safe": f"{stem}SAFE",
        "cslc_auto": f"{stem}CSLCAuto",
        "cslc_standard": f"{stem}CSLCStandard",
        "disp": f"{stem}DISP",
        "isce2": f"{stem}I",
    }


def _normalize_date(value: str) -> str:
    """Return YYYYMMDD from YYYY-MM-DD or YYYYMMDD."""
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text.replace("-", "")
    if re.fullmatch(r"\d{8}", text):
        return text
    raise ValueError(f"date must be YYYYMMDD or YYYY-MM-DD: {value!r}")


def _isce3_command(
    aoi: str,
    project: str,
    *,
    flight_dir: str,
    start: str,
    end: str,
    data_flag: str | None = None,
    preset: str | None = None,
    track: int | None,
    frame_id: int | None,
    run: bool = False,
) -> str:
    parts = [
        "create_isce3_runfiles.py",
        shlex.quote(aoi),
        shlex.quote(project),
        "--flight-dir",
        flight_dir,
        "--start",
        start,
        "--end",
        end,
    ]
    if preset is not None:
        parts.extend(["--data-type", "cslc", "--preset", preset])
    elif data_flag is not None:
        parts.append(data_flag)
    else:
        raise ValueError("data_flag or preset is required")
    if track is not None:
        parts.extend(["--track", str(track)])
    if frame_id is not None and data_flag in {"--disp-S1", "--disp"}:
        parts.extend(["--frame-id", str(frame_id)])
    if run:
        parts.append("--run")
    return " ".join(parts)


def _minsar_app_command(
    aoi: str,
    project: str,
    *,
    flight_dir: str,
    start: str,
    end: str,
) -> str:
    return (
        f"minsarApp.bash {shlex.quote(aoi)} {shlex.quote(project)} "
        f"--flight-dir {flight_dir} --start-date {start} --end-date {end} "
        f"--no-mintpy --miaplpy"
    )


def build_compare_script(
    aoi: str,
    base: str,
    *,
    flight_dir: str,
    start_date: str,
    end_date: str,
    track: int | None = None,
    frame_id: int | None = None,
) -> tuple[str, dict[str, str]]:
    """Return bash script text and project names keyed by pipeline."""
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    names = project_names(base)
    stem = normalize_base_name(base)
    lines = [
        "#!/usr/bin/env bash",
        "set -e",
        f"# Compare SAFE, CSLC auto/standard, DISP-S1 (ISCE3), and MiaplPy for {stem}",
        _isce3_command(aoi, names["safe"], flight_dir=flight_dir, start=start, end=end, data_flag="--safe", track=track, frame_id=frame_id, run=True),
        _isce3_command(
            aoi,
            names["cslc_auto"],
            flight_dir=flight_dir,
            start=start,
            end=end,
            preset="auto",
            track=track,
            frame_id=frame_id,
            run=True,
        ),
        _isce3_command(
            aoi,
            names["cslc_standard"],
            flight_dir=flight_dir,
            start=start,
            end=end,
            preset="standard",
            track=track,
            frame_id=frame_id,
            run=True,
        ),
        _isce3_command(aoi, names["disp"], flight_dir=flight_dir, start=start, end=end, data_flag="--disp-S1", track=track, frame_id=frame_id, run=True),
        _minsar_app_command(aoi, names["isce2"], flight_dir=flight_dir, start=start, end=end),
        "",
    ]
    return "\n".join(lines), names


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(iargs: list[str] | None = None) -> int:
    argv = fix_argv_for_negative_bbox_sn_we(
        sys.argv[1:] if iargs is None else iargs,
        **ARGV_FIX_KW,
        multiple_initial_positionals=True,
    )
    parser = create_parser()
    inps = parser.parse_args(argv)
    work_dir = Path.cwd().resolve()
    stem = normalize_base_name(inps.name)
    out_path = inps.output or work_dir / f"{stem}_compare.bash"
    message_rsmas.log(
        str(work_dir),
        os.path.basename(__file__) + " " + " ".join(argv),
    )
    try:
        body, names = build_compare_script(
            inps.aoi,
            inps.name,
            flight_dir=inps.flight_dir,
            start_date=inps.start_date,
            end_date=inps.end_date,
            track=inps.track,
            frame_id=inps.frame_id,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    out_path.write_text(body, encoding="utf-8")
    _make_executable(out_path)
    print()
    for line in body.splitlines():
        if line.startswith("create_isce3_runfiles.py"):
            print(line)
    print(f"Wrote {out_path.name}")

    if inps.run:
        import subprocess

        for spec in (
            {"data_flag": "--safe", "project": names["safe"]},
            {"preset": "auto", "project": names["cslc_auto"]},
            {"preset": "standard", "project": names["cslc_standard"]},
            {"data_flag": "--disp-S1", "project": names["disp"]},
        ):
            command = _isce3_command(
                inps.aoi,
                spec["project"],
                flight_dir=inps.flight_dir,
                start=_normalize_date(inps.start_date),
                end=_normalize_date(inps.end_date),
                data_flag=spec.get("data_flag"),
                preset=spec.get("preset"),
                track=inps.track,
                frame_id=inps.frame_id,
                run=True,
            )
            print(f"Running: {command}", file=sys.stderr)
            completed = subprocess.run(command, shell=True, cwd=work_dir, check=False)
            if completed.returncode != 0:
                return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
