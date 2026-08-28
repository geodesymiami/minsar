#!/usr/bin/env python3
"""Write sweets.bash with a ``sweets config`` command from a MinSAR template.

From the template, only ``miaplpy.subset.lalo`` is used. Dates, track, and
flight direction come from the CLI (or defaults for dates). Track and IW swaths
are resolved with ``opera_utils.get_burst_geodataframe()`` for bursts that
intersect the AOI (optionally filtered by ``--flight-dir`` / ``--track``).

Default ``--source`` is OPERA CSLC when products exist for the AOI/dates,
otherwise Sentinel-1 bursts (``--source safe``). Passing ``--source cslc`` or
``--source burst`` skips that check.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

from minsar.objects import message_rsmas
from minsar.objects.auto_defaults import PathFind
from minsar.objects.dataset_template import Template
from minsar.utils.ssaraopt_to_mintpy_plot import parse_ssaraopt_date

pathObj = PathFind()

SWEETS_BASH = "sweets.bash"
S1_START_DEFAULT = "2014-10-01"
CLI_TO_SWEETS_SOURCE = {
    "cslc": "opera-cslc",
    "burst": "safe",
}
IW_ORDER = ("IW1", "IW2", "IW3")
PASS_FROM_FLIGHT_DIR = {
    "asc": "ASCENDING",
    "ascending": "ASCENDING",
    "desc": "DESCENDING",
    "descending": "DESCENDING",
}

DESCRIPTION = (
    "Create sweets.bash from miaplpy.subset.lalo plus CLI dates/track/flight-dir.\n"
    "Track and swaths come from opera_utils burst footprints intersecting the AOI."
)

EXAMPLE = """Examples:
  generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --flight-dir asc
  generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source cslc --start 20200101 --end 20201231
  generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source burst --track 87 --flight-dir desc
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("template", help="MinSAR template (only miaplpy.subset.lalo is read)")
    parser.add_argument(
        "--source",
        choices=("cslc", "burst"),
        default=None,
        help="cslc: opera-cslc. burst: safe. If omitted, prefer opera-cslc when available.",
    )
    parser.add_argument("--start-date", "--start", dest="start_date", help="first date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end-date", "--end", dest="end_date", help="last date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--track", type=int, help="relative orbit; default: from opera_utils bursts over the AOI")
    parser.add_argument("--flight-dir", choices=("asc", "desc"), help="filter opera_utils bursts by orbit pass")
    return parser


def iso_date(value: str | None, *, default: str | None = None) -> str:
    """Return YYYY-MM-DD from a date (YYYYMMDD, ISO, or auto)."""
    parsed = parse_ssaraopt_date(value)
    if parsed is None:
        if default is None:
            raise ValueError(f"Could not parse date: {value!r}")
        return default
    return parsed.strftime("%Y-%m-%d")


def subset_lalo_from_template(template_file: str) -> str:
    """Return S:N,W:E from miaplpy.subset.lalo only."""
    dataset_template = Template(template_file)
    options = dataset_template.get_options()
    options.update(pathObj.correct_for_ssara_date_format(dict(options)))
    subset = options.get("miaplpy.subset.lalo")
    if not subset:
        raise ValueError(f"Template has no miaplpy.subset.lalo: {template_file}")
    return str(subset).strip().strip("'\"")


def bbox_wsene(subset_lalo: str) -> tuple[str, str, str, str]:
    """Convert S:N,W:E to sweets --bbox tokens (west south east north)."""
    lat, lon = subset_lalo.split(",", 1)
    south, north = [p.strip() for p in lat.split(":")]
    west, east = [p.strip() for p in lon.split(":")]
    return west, south, east, north


def aoi_to_wkt(subset_lalo: str) -> str:
    """Convert S:N,W:E to POLYGON WKT."""
    from minsar.utils.convert_bbox import _input_to_bounds

    lat_min, lat_max, lon_min, lon_max = _input_to_bounds(subset_lalo)
    return (
        f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},"
        f"{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
    )


def subset_lalo_from_options(options: dict) -> str:
    """Return S:N,W:E from miaplpy.subset.lalo in template options."""
    subset = options.get("miaplpy.subset.lalo")
    if not subset:
        raise ValueError("Template has no miaplpy.subset.lalo")
    return str(subset).strip().strip("'\"")


def parse_track(options: dict) -> int:
    """Relative orbit from ssaraopt.relativeOrbit."""
    raw = options.get("ssaraopt.relativeOrbit")
    if raw is None or str(raw).strip() == "":
        raise ValueError("Template has no ssaraopt.relativeOrbit")
    return int(str(raw).strip())


def flight_direction_from_template(template_file: str) -> str | None:
    """asc/desc from template options or SenA/SenD in dataset name."""
    dataset_template = Template(template_file)
    options = dataset_template.get_options()
    options.update(pathObj.correct_for_ssara_date_format(dict(options)))
    for key in ("ssaraopt.flightDirection", "flightDirection", "orbitDirection"):
        val = options.get(key)
        if val:
            text = str(val).strip().lower()
            if text.startswith("a"):
                return "asc"
            if text.startswith("d"):
                return "desc"
            raise ValueError(f"unknown flight direction {val!r} in template")
    dataset = options.get("dataset") or Path(template_file).stem.replace(".template", "")
    if re.search(r"SenA\d", dataset, re.I):
        return "asc"
    if re.search(r"SenD\d", dataset, re.I):
        return "desc"
    return None


def resolve_work_dir(template_or_options: str | dict, cwd: str | None = None) -> str:
    """Scratch project dir from template path or options dict (dataset key)."""
    if isinstance(template_or_options, dict):
        options = template_or_options
        cwd_abs = os.path.abspath(cwd or os.getcwd())
        dataset = options.get("dataset")
        if dataset and dataset in cwd_abs:
            return cwd_abs
        scratch = os.getenv("SCRATCHDIR")
        if scratch and dataset:
            return os.path.join(scratch, dataset)
        return cwd_abs
    template_file = template_or_options
    cwd = os.path.abspath(cwd or os.getcwd())
    dataset_template = Template(template_file)
    options = dataset_template.get_options()
    dataset = options.get("dataset") or Path(template_file).stem.replace(".template", "")
    if dataset and dataset in cwd:
        return cwd
    scratch = os.getenv("SCRATCHDIR")
    if scratch and dataset:
        return os.path.join(scratch, dataset)
    return cwd


def _normalize_orbit_pass(flight_direction: str | None) -> str | None:
    if not flight_direction:
        return None
    key = flight_direction.strip().lower()
    if key not in PASS_FROM_FLIGHT_DIR:
        raise ValueError(f"unknown flight direction {flight_direction!r}; use asc or desc")
    return PASS_FROM_FLIGHT_DIR[key]


def _burst_gdf_for_aoi(
    subset_lalo: str,
    *,
    track: int | None = None,
    flight_direction: str | None = None,
):
    """GeoDataFrame of OPERA burst footprints intersecting the AOI (filtered)."""
    from opera_utils import get_burst_geodataframe
    from shapely.geometry import box

    west, south, east, north = bbox_wsene(subset_lalo)
    aoi = box(float(west), float(south), float(east), float(north))
    gdf = get_burst_geodataframe()
    hit = gdf[gdf.geometry.intersects(aoi)].copy()
    if hit.empty:
        raise RuntimeError(f"No OPERA burst footprints intersect AOI {subset_lalo}")

    hit["track"] = hit["burst_id_jpl"].str.extract(r"^t(\d+)_", expand=False).astype(int)
    hit["swath"] = hit["burst_id_jpl"].str.extract(r"_(iw\d)$", expand=False).str.upper()

    want_pass = _normalize_orbit_pass(flight_direction)
    if want_pass is not None:
        hit = hit[hit["orbit_pass"].astype(str).str.upper() == want_pass]
        if hit.empty:
            raise RuntimeError(f"No {want_pass} bursts intersect AOI {subset_lalo}")

    if track is not None:
        hit = hit[hit["track"] == int(track)]
        if hit.empty:
            raise RuntimeError(f"Track {track} does not intersect AOI {subset_lalo}")
    return hit


def count_bursts_covering_aoi(
    subset_lalo: str,
    *,
    track: int | None = None,
    flight_direction: str | None = None,
) -> int:
    """Number of distinct OPERA burst footprints intersecting the AOI."""
    print(f"Querying opera_utils burst footprints for AOI {subset_lalo} ...", file=sys.stderr)
    hit = _burst_gdf_for_aoi(subset_lalo, track=track, flight_direction=flight_direction)
    return len(hit)


def bursts_covering_aoi(
    subset_lalo: str,
    *,
    track: int | None = None,
    flight_direction: str | None = None,
) -> tuple[int, list[str]]:
    """Return (track, IW swaths) for bursts intersecting the AOI via opera_utils.

    Uses ``opera_utils.get_burst_geodataframe()`` (WGS84 footprints with
    ``orbit_pass``). Equivalent idea to CLI frame lookup via
    ``opera-utils disp-s1-intersects``, but returns the intersecting IW swaths
    rather than whole DISP frames.
    """
    print(f"Querying opera_utils burst footprints for AOI {subset_lalo} ...", file=sys.stderr)
    hit = _burst_gdf_for_aoi(subset_lalo, track=track, flight_direction=flight_direction)

    if track is not None:
        chosen = int(track)
    else:
        tracks = sorted({int(t) for t in hit["track"].unique()})
        passes = sorted({str(p).upper() for p in hit["orbit_pass"].dropna().unique()})
        want_pass = _normalize_orbit_pass(flight_direction)
        if len(tracks) > 1 and want_pass is None and len(passes) > 1:
            raise RuntimeError(
                f"AOI intersects tracks {tracks} ({', '.join(passes)}); pass --track or --flight-dir"
            )
        counts = hit.groupby("track").size().sort_values(ascending=False)
        chosen = int(counts.index[0])
        if len(counts) > 1:
            listing = ", ".join(f"{int(t)}({int(n)})" for t, n in counts.items())
            print(f"  multiple tracks over AOI: {listing}; using {chosen}", file=sys.stderr)

    track_hits = hit[hit["track"] == chosen]
    swaths = [name for name in IW_ORDER if name in set(track_hits["swath"].dropna())]
    if not swaths:
        raise RuntimeError(f"No IW swaths found for track {chosen} over AOI {subset_lalo}")
    print(f"  track={chosen} swaths={' '.join(swaths)}", file=sys.stderr)
    return chosen, swaths


def opera_cslc_available(
    subset_lalo: str,
    start_iso: str,
    end_iso: str,
    track: int | None,
) -> bool:
    """True if at least one OPERA CSLC-S1 granule intersects the AOI/date range."""
    import asf_search as asf

    wkt = aoi_to_wkt(subset_lalo)
    kwargs = dict(
        dataset=asf.DATASET.OPERA_S1,
        processingLevel=asf.PRODUCT_TYPE.CSLC,
        intersectsWith=wkt,
        start=start_iso,
        end=end_iso,
        maxResults=1,
    )
    if track is not None:
        kwargs["relativeOrbit"] = int(track)
    try:
        results = list(asf.search(**kwargs))
    except Exception as exc:
        print(f"OPERA CSLC search failed ({exc}); treating as unavailable.", file=sys.stderr)
        return False
    return len(results) > 0


def resolve_sweets_source(
    cli_source: str | None,
    subset_lalo: str,
    start_iso: str,
    end_iso: str,
    track: int | None,
) -> str:
    """Return sweets --source value (opera-cslc or safe)."""
    if cli_source is not None:
        return CLI_TO_SWEETS_SOURCE[cli_source]
    if opera_cslc_available(subset_lalo, start_iso, end_iso, track):
        print("OPERA CSLC available; using --source opera-cslc", file=sys.stderr)
        return "opera-cslc"
    print("No OPERA CSLC available; using --source safe (bursts)", file=sys.stderr)
    return "safe"


def format_sweets_config_command(
    *,
    bbox: tuple[str, str, str, str],
    start: str,
    end: str,
    source: str,
    track: int | None,
    swaths: list[str],
    out_dir: str = "./data",
    work_dir: str = ".",
    output: str = "sweets_config.yaml",
) -> str:
    west, south, east, north = bbox
    parts = [
        "sweets config",
        f"--bbox {west} {south} {east} {north}",
        f"--start {start}",
        f"--end {end}",
        f"--source {source}",
    ]
    if track is not None:
        parts.append(f"--track {track}")
    if source == "safe" and swaths:
        parts.append(f"--swaths {' '.join(swaths)}")
    parts.extend(
        [
            f"--out-dir {out_dir}",
            f"--work-dir {work_dir}",
            f"--output {output}",
        ]
    )
    config_line = " ".join(parts)
    run_line = f"sweets run {output}"
    return f"{config_line}\n{run_line}\n"


def write_sweets_bash(command: str, work_dir: str, filename: str = SWEETS_BASH) -> str:
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, filename)
    body = command.rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
        if not body.endswith("\n"):
            handle.write("\n")
    os.chmod(path, 0o755)
    return path


def build_from_template(
    template_file: str,
    cli_source: str | None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    track: int | None = None,
    flight_direction: str | None = None,
) -> tuple[str, str]:
    """Build sweets config+run text. Template contributes only miaplpy.subset.lalo."""
    subset_lalo = subset_lalo_from_template(template_file)
    bbox = bbox_wsene(subset_lalo)
    start = iso_date(start_date, default=S1_START_DEFAULT)
    end = iso_date(end_date, default=date.today().strftime("%Y-%m-%d"))

    need_swaths = cli_source == "burst" or cli_source is None
    parsed_track = int(track) if track is not None else None
    swaths: list[str] = []
    if need_swaths or parsed_track is None:
        parsed_track, swaths = bursts_covering_aoi(
            subset_lalo,
            track=parsed_track,
            flight_direction=flight_direction,
        )

    source = resolve_sweets_source(cli_source, subset_lalo, start, end, parsed_track)
    if source == "safe":
        if not swaths:
            parsed_track, swaths = bursts_covering_aoi(
                subset_lalo,
                track=parsed_track,
                flight_direction=flight_direction,
            )
        if parsed_track is None:
            raise RuntimeError(
                "Could not determine --track for burst (safe) source. "
                "Pass --track or --flight-dir, or check AOI coverage."
            )

    command = format_sweets_config_command(
        bbox=bbox,
        start=start,
        end=end,
        source=source,
        track=parsed_track,
        swaths=swaths if source == "safe" else [],
    )
    work_dir = resolve_work_dir(template_file)
    return command, work_dir


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    template_file = os.path.abspath(os.path.expandvars(inps.template))
    if not os.path.isfile(template_file):
        parser.error(f"template not found: {template_file}")

    work_dir = os.getcwd()
    message_rsmas.log(
        work_dir,
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )

    command, out_dir = build_from_template(
        template_file,
        inps.source,
        start_date=inps.start_date,
        end_date=inps.end_date,
        track=inps.track,
        flight_direction=inps.flight_dir,
    )
    path = write_sweets_bash(command, out_dir)
    print(command.rstrip())
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
