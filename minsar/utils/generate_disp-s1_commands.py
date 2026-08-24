#!/usr/bin/env python3
"""Write download_disp-s1.bash with opera-utils DISP-S1 download/rebase commands.

Reads AOI, dates, and track from a MinSAR template. Resolves the DISP-S1 frame
ID from opera-utils (orbit pass + track, largest AOI overlap) unless --frame-id
is given. Optional --start-date / --end-date override ssaraopt dates (same
formats as create_template.py). The bash file also runs dolphin2hdfeos5.py.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime

from minsar.objects import message_rsmas
from minsar.objects.auto_defaults import PathFind
from minsar.objects.dataset_template import Template
from minsar.utils.generate_sweets_config import (
    S1_START_DEFAULT,
    bbox_wsene,
    flight_direction_from_template,
    iso_date,
    parse_track,
    resolve_work_dir,
    subset_lalo_from_options,
)

pathObj = PathFind()

DISP_S1_BASH = "download_disp-s1.bash"
NUM_WORKERS_DEFAULT = 8
OUTPUT_DIR_DEFAULT = "subsets"
DISP_INSTALL_HINT = (
    "pip install --upgrade "
    "'opera-utils[asf,disp,geopandas,tropo] @ git+https://github.com/scottstanie/opera-utils.git@develop-scott'"
)

DESCRIPTION = (
    "Create download_disp-s1.bash with opera-utils DISP-S1 download, rebase, "
    "and dolphin2hdfeos5.py from a template."
)

EXAMPLE = """Examples:
  generate_disp-s1_commands.py $TE/HawaiiPunaSenD87.template
  generate_disp-s1_commands.py $TE/HawaiiPunaSenD87.template --start-date 20200101 --end-date 20240601
  generate_disp-s1_commands.py $TE/HawaiiPunaSenD87.template --frame-id 23211 --url-type S3
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("template", help="MinSAR template file")
    parser.add_argument("--start-date", metavar="DATE", help="ssaraopt.startDate: YYYY-MM-DD or YYYYMMDD (e.g. 20230101)")
    parser.add_argument("--end-date", metavar="DATE", help="ssaraopt.endDate: YYYY-MM-DD or YYYYMMDD (e.g. 20241231)")
    parser.add_argument("--frame-id", type=int, metavar="ID", help="DISP-S1 frame ID (default: largest-overlap frame for AOI, track, and pass)")
    parser.add_argument("--url-type", choices=("HTTPS", "S3"), default="HTTPS", help="opera-utils download URL type (default: HTTPS)")
    return parser


def cli_date_to_iso(value: str) -> str:
    """Return YYYY-MM-DD from YYYY-MM-DD or YYYYMMDD (same rules as create_template.py)."""
    text = value.strip()
    if not text:
        raise ValueError(f"Empty date: {value!r}")
    if "-" in text:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}")
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}") from exc
        return parsed.strftime("%Y-%m-%d")
    if len(text) == 8 and text.isdigit():
        try:
            parsed = datetime.strptime(text, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}") from exc
        return parsed.strftime("%Y-%m-%d")
    raise ValueError(f"Invalid date (use YYYY-MM-DD or YYYYMMDD): {value!r}")


def require_disp_s1_cli() -> None:
    """Fail if opera-utils was installed without the disp extra (CLI hides that ImportError)."""
    try:
        from opera_utils.disp._download import run_download  # noqa: F401
        from opera_utils.disp._reformat import reformat_stack  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "opera-utils has no disp-s1-download/reformat "
            f"(disp extra missing or import failed: {exc}). Install with:\n  {DISP_INSTALL_HINT}"
        ) from exc


def _opera_utils():
    """Import opera-utils (and shapely) only when a frame ID must be resolved."""
    try:
        import opera_utils
        from opera_utils import Bbox
        from shapely.geometry import box, shape
    except ImportError as exc:
        raise RuntimeError(
            "opera-utils (and shapely) are required to resolve --frame-id. "
            f"Install opera-utils or pass --frame-id.\n  {DISP_INSTALL_HINT}"
        ) from exc
    return opera_utils, Bbox, box, shape


def track_from_frame(opera_utils, frame_id: int) -> int | None:
    """Relative orbit from burst IDs (e.g. t087_185681_iw1 -> 87)."""
    bursts = opera_utils.get_burst_ids_for_frame(int(frame_id))
    tracks: set[int] = set()
    for burst in bursts or []:
        prefix = str(burst).split("_", 1)[0]
        if len(prefix) > 1 and prefix[0] in "tT" and prefix[1:].isdigit():
            tracks.add(int(prefix[1:]))
    if len(tracks) == 1:
        return next(iter(tracks))
    return None


def orbit_pass_wanted(flight_direction: str | None) -> str | None:
    if not flight_direction:
        return None
    return "ASCENDING" if flight_direction.lower().startswith("a") else "DESCENDING"


def resolve_frame_id(
    bbox: tuple[str, str, str, str],
    *,
    track: int | None,
    flight_direction: str | None,
) -> int:
    """Pick the DISP-S1 frame that matches pass/track and covers the most of the AOI."""
    opera_utils, Bbox, box, shape = _opera_utils()
    west, south, east, north = (float(v) for v in bbox)
    aoi = box(west, south, east, north)
    frames = opera_utils.get_intersecting_frames(Bbox(left=west, bottom=south, right=east, top=north))
    features = list(frames.get("features") or [])
    if not features:
        raise RuntimeError(f"No DISP-S1 frames intersect AOI bbox {west} {south} {east} {north}")

    want_pass = orbit_pass_wanted(flight_direction)
    matched: list[dict] = []
    summaries: list[str] = []
    for feat in features:
        frame_id = int(feat["id"])
        orbit_pass = str(feat.get("properties", {}).get("orbit_pass", "")).upper()
        frame_track = track_from_frame(opera_utils, frame_id)
        overlap = shape(feat["geometry"]).intersection(aoi).area
        frac = (overlap / aoi.area) if aoi.area else 0.0
        summaries.append(f"{frame_id} {orbit_pass or '?'} t{frame_track if frame_track is not None else '?'} {frac:.0%}")
        if want_pass and orbit_pass != want_pass:
            continue
        if track is not None and frame_track is not None and frame_track != int(track):
            continue
        matched.append({"id": frame_id, "orbit_pass": orbit_pass, "track": frame_track, "frac": frac})

    if not matched:
        raise RuntimeError(
            "No DISP-S1 frame matches "
            f"pass={want_pass or 'any'} track={track if track is not None else 'any'}. "
            f"Intersecting frames: {', '.join(summaries)}"
        )

    matched.sort(key=lambda row: row["frac"], reverse=True)
    best = matched[0]
    print(
        f"  frame from coverage: {best['id']} "
        f"({best['orbit_pass'] or '?'} track {best['track'] if best['track'] is not None else '?'}, "
        f"overlap {best['frac']:.0%})",
        file=sys.stderr,
    )
    return int(best["id"])


def format_disp_s1_bash(
    *,
    frame_id: int,
    bbox: tuple[str, str, str, str],
    start: str,
    end: str,
    url_type: str,
    stack_name: str,
    num_workers: int = NUM_WORKERS_DEFAULT,
    output_dir: str = OUTPUT_DIR_DEFAULT,
) -> str:
    west, south, east, north = bbox
    download = (
        f"opera-utils disp-s1-download --frame-id {frame_id} "
        f"--bbox {west} {south} {east} {north} "
        f"--start-datetime {start} --end-datetime {end} "
        f"--url-type {url_type} --num-workers {num_workers} "
        f"--output-dir {output_dir}"
    )
    check = (
        f"check_opera_download.py {output_dir} --frame-id {frame_id} "
        f"--start-datetime {start} --end-datetime {end}"
    )
    reformat = (
        f"opera-utils disp-s1-reformat --input-files {output_dir}/OPERA*.nc "
        f"--output-name {stack_name} --reference-method BORDER "
        f"--quality-datasets None --drop-vars shp_counts estimated_phase_quality"
    )
    return (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f"mkdir -p {output_dir}\n"
        f"{download}\n"
        f"{check} --delete\n"
        f"{download}\n"
        f"{check}\n"
        "\n"
        f"{reformat}\n"
        f"dolphin2hdfeos5.py {stack_name}\n"
        "ingest_insarmaps.bash timeseries\n"
    )


def write_disp_s1_bash(command: str, work_dir: str, filename: str = DISP_S1_BASH) -> str:
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, filename)
    body = command.rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(path, 0o755)
    return path


def build_from_template(
    template_file: str,
    *,
    start_date: str | None,
    end_date: str | None,
    frame_id: int | None,
    url_type: str,
) -> tuple[str, str]:
    dataset_template = Template(template_file)
    options = dataset_template.get_options()
    options.update(pathObj.correct_for_ssara_date_format(dict(options)))

    subset_lalo = subset_lalo_from_options(options)
    bbox = bbox_wsene(subset_lalo)
    start = iso_date(options.get("ssaraopt.startDate"), default=S1_START_DEFAULT)
    end = iso_date(options.get("ssaraopt.endDate"), default=date.today().strftime("%Y-%m-%d"))
    if start_date:
        start = cli_date_to_iso(start_date)
    if end_date:
        end = cli_date_to_iso(end_date)
    if datetime.strptime(end, "%Y-%m-%d").date() < datetime.strptime(start, "%Y-%m-%d").date():
        raise ValueError(f"end date {end} is before start date {start}")

    dataset = options.get("dataset") or os.path.splitext(os.path.basename(template_file))[0]
    stack_name = f"{dataset}-stack.nc"
    require_disp_s1_cli()

    if frame_id is None:
        track = parse_track(options)
        flight_direction = flight_direction_from_template(template_file)
        print("Querying DISP-S1 frames for AOI ...", file=sys.stderr)
        frame_id = resolve_frame_id(bbox, track=track, flight_direction=flight_direction)

    command = format_disp_s1_bash(
        frame_id=int(frame_id),
        bbox=bbox,
        start=start,
        end=end,
        url_type=url_type,
        stack_name=stack_name,
    )
    work_dir = resolve_work_dir(options)
    return command, work_dir


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    template_file = os.path.abspath(os.path.expandvars(inps.template))
    if not os.path.isfile(template_file):
        parser.error(f"template not found: {template_file}")
    try:
        if inps.start_date:
            cli_date_to_iso(inps.start_date)
        if inps.end_date:
            cli_date_to_iso(inps.end_date)
    except ValueError as exc:
        parser.error(str(exc))

    work_dir = os.getcwd()
    message_rsmas.log(
        work_dir,
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )

    try:
        command, out_dir = build_from_template(
            template_file,
            start_date=inps.start_date,
            end_date=inps.end_date,
            frame_id=inps.frame_id,
            url_type=inps.url_type,
        )
    except ValueError as exc:
        parser.error(str(exc))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    path = write_disp_s1_bash(command, out_dir)
    print(command.rstrip())
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
