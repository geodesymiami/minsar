#!/usr/bin/env python3
"""Write sweets.bash with a ``sweets config`` command from a MinSAR template.

Default ``--source`` for the generated command is OPERA CSLC. If CSLC products
are not available for the AOI/date range, the command uses Sentinel-1 bursts
(``--source safe``). Passing ``--source cslc`` or ``--source burst`` skips that
availability check.

Track (``ssaraopt.relativeOrbit``) and swaths (``topsStack.subswath``) are taken
from the template when present. Otherwise they are computed with the same
coverage helpers used by ``get_sar_coverage.py`` / ``create_template.py``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from minsar.objects import message_rsmas
from minsar.objects.auto_defaults import PathFind
from minsar.objects.dataset_template import Template
from minsar.utils.convert_bbox import _input_to_bounds
from minsar.utils.ssaraopt_to_mintpy_plot import parse_ssaraopt_date

pathObj = PathFind()

SWEETS_BASH = "sweets.bash"
S1_START_DEFAULT = "2014-10-01"
CLI_TO_SWEETS_SOURCE = {
    "cslc": "opera-cslc",
    "burst": "safe",
}
IW_ORDER = ("IW1", "IW2", "IW3")

DESCRIPTION = (
    "Create sweets.bash containing a sweets config command from a template.\n"
    "Default source is opera-cslc; falls back to bursts (safe) when no CSLC is available."
)

EXAMPLE = """examples:
  generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template
  generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source cslc
  generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source burst
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("template", help="MinSAR template file")
    parser.add_argument(
        "--source",
        choices=("cslc", "burst"),
        default=None,
        help=(
            "Input source for sweets config. "
            "cslc: opera-cslc. burst: safe (Sentinel-1 bursts). "
            "If omitted, use opera-cslc when products exist, otherwise bursts. "
            "If given, skip the OPERA CSLC availability check."
        ),
    )
    return parser


def iso_date(value: str | None, *, default: str | None = None) -> str:
    """Return YYYY-MM-DD from a template date (YYYYMMDD, ISO, or auto)."""
    parsed = parse_ssaraopt_date(value)
    if parsed is None:
        if default is None:
            raise ValueError(f"Could not parse date: {value!r}")
        return default
    return parsed.strftime("%Y-%m-%d")


def subset_lalo_from_options(options: dict) -> str:
    """Return S:N,W:E from miaplpy/mintpy subset or topsStack.boundingBox."""
    subset = options.get("miaplpy.subset.lalo") or options.get("mintpy.subset.lalo")
    if subset:
        return subset.strip().strip("'\"")
    bbox = options.get("topsStack.boundingBox")
    if not bbox:
        raise ValueError(
            "Template has no miaplpy.subset.lalo, mintpy.subset.lalo, or topsStack.boundingBox"
        )
    parts = bbox.strip().strip("'\"").split()
    if len(parts) != 4:
        raise ValueError(f"Cannot parse topsStack.boundingBox: {bbox!r}")
    south, north, west, east = parts
    return f"{south}:{north},{west}:{east}"


def bbox_wsene(subset_lalo: str) -> tuple[str, str, str, str]:
    """Convert S:N,W:E to sweets --bbox tokens (west south east north)."""
    lat, lon = subset_lalo.split(",", 1)
    south, north = [p.strip() for p in lat.split(":")]
    west, east = [p.strip() for p in lon.split(":")]
    return west, south, east, north


def parse_track(options: dict) -> int | None:
    raw = options.get("ssaraopt.relativeOrbit")
    if raw is None:
        return None
    text = str(raw).strip().strip("'\"")
    if not text:
        return None
    return int(text)


def parse_swaths(options: dict) -> list[str]:
    raw = options.get("topsStack.subswath") or options.get("ssaraopt.beamSwath")
    if raw is None:
        return []
    tokens = str(raw).strip().strip("'\"").replace(",", " ").split()
    swaths: list[str] = []
    for token in tokens:
        upper = token.upper()
        if upper.startswith("IW") and upper[2:].isdigit():
            name = f"IW{upper[2:]}"
        elif token.isdigit():
            name = f"IW{token}"
        else:
            continue
        if name not in swaths:
            swaths.append(name)
    return [name for name in IW_ORDER if name in swaths] or swaths


def flight_direction_from_template(template_path: str) -> str | None:
    """Ascending/Descending from a SenA124 / SenDT87-style template name."""
    name = Path(template_path).stem
    match = re.search(r"Sen(A|D)T?\d+", name, re.IGNORECASE)
    if not match:
        return None
    return "Ascending" if match.group(1).upper() == "A" else "Descending"


def resolve_work_dir(options: dict, cwd: str | None = None) -> str:
    cwd = os.path.abspath(cwd or os.getcwd())
    dataset = options.get("dataset")
    if dataset and dataset in cwd:
        return cwd
    scratch = os.getenv("SCRATCHDIR")
    if scratch and dataset:
        return os.path.join(scratch, dataset)
    return cwd


def discovery_window(start_iso: str, end_iso: str) -> tuple[date, date]:
    start = datetime.strptime(start_iso, "%Y-%m-%d").date()
    end = datetime.strptime(end_iso, "%Y-%m-%d").date()
    if end < start:
        raise ValueError(f"end date {end_iso} is before start date {start_iso}")
    disc_end = min(start + timedelta(days=31), end)
    return start, disc_end


def aoi_to_wkt(subset_lalo: str) -> str:
    """Convert S:N,W:E (or other convert_bbox inputs) to POLYGON WKT."""
    lat_min, lat_max, lon_min, lon_max = _input_to_bounds(subset_lalo)
    return (
        f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},"
        f"{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
    )


def _sar_coverage():
    """Import get_sar_coverage only when track/swath lookup needs it."""
    from minsar.scripts import get_sar_coverage as gsc

    return gsc


def unique_swaths_for_orbit(burst_results, orbit: int) -> list[str]:
    gsc = _sar_coverage()
    found: set[str] = set()
    for product in burst_results:
        if gsc._get_orbit(product) != int(orbit):
            continue
        swath = gsc._get_subswath_s1(product)
        if swath and swath != "-":
            found.add(swath.upper())
    return [name for name in IW_ORDER if name in found]


def _best_track_for_direction(rows: list[dict], direction: str | None) -> int | None:
    gsc = _sar_coverage()
    preferred = [direction] if direction else ["Ascending", "Descending"]
    for want in preferred:
        for row in rows:
            if row.get("direction") != want or not row.get("orbits"):
                continue
            best = gsc._best_orbit_for_direction(row["orbits"], want, "Sentinel-1")
            if best is not None:
                return int(best["orbit"])
    return None


def query_track_and_swaths(
    subset_lalo: str,
    start_iso: str,
    end_iso: str,
    *,
    track: int | None,
    swaths: list[str],
    flight_direction: str | None,
) -> tuple[int | None, list[str]]:
    """Fill missing track/swaths using get_sar_coverage helpers."""
    if track is not None and swaths:
        return track, swaths

    gsc = _sar_coverage()
    wkt = aoi_to_wkt(subset_lalo)
    disc_start, disc_end = discovery_window(start_iso, end_iso)
    print(
        f"Querying SAR coverage for track/swath ({disc_start} to {disc_end}) ...",
        file=sys.stderr,
    )
    slc_sample, burst_results = gsc.query_sentinel1(wkt, disc_start, disc_end)
    orbit_sw_map = gsc._build_orbit_metadata_map(burst_results)
    rows = gsc._aggregate(slc_sample, orbit_sw_map, counts=None)

    if track is None:
        track = _best_track_for_direction(rows, flight_direction)
        if track is not None:
            print(f"  track from coverage: {track}", file=sys.stderr)

    if not swaths and track is not None:
        swaths = unique_swaths_for_orbit(burst_results, track)
        if not swaths:
            meta = orbit_sw_map.get(int(track), {})
            swath = meta.get("subswath") if isinstance(meta, dict) else None
            if swath and swath != "-":
                swaths = [str(swath).upper()]
        if swaths:
            print(f"  swaths from coverage: {' '.join(swaths)}", file=sys.stderr)

    return track, swaths


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


def build_from_template(template_file: str, cli_source: str | None) -> tuple[str, str]:
    dataset_template = Template(template_file)
    options = dataset_template.get_options()
    options.update(pathObj.correct_for_ssara_date_format(dict(options)))

    subset_lalo = subset_lalo_from_options(options)
    bbox = bbox_wsene(subset_lalo)
    start = iso_date(options.get("ssaraopt.startDate"), default=S1_START_DEFAULT)
    end = iso_date(options.get("ssaraopt.endDate"), default=date.today().strftime("%Y-%m-%d"))
    track = parse_track(options)
    swaths = parse_swaths(options)
    flight_direction = flight_direction_from_template(template_file)

    need_swaths = cli_source == "burst" or cli_source is None
    if track is None or (need_swaths and not swaths):
        track, swaths = query_track_and_swaths(
            subset_lalo,
            start,
            end,
            track=track,
            swaths=swaths,
            flight_direction=flight_direction,
        )

    source = resolve_sweets_source(cli_source, subset_lalo, start, end, track)
    if source == "safe" and track is None:
        raise RuntimeError(
            "Could not determine --track for burst (safe) source. "
            "Set ssaraopt.relativeOrbit in the template or check AOI coverage."
        )

    command = format_sweets_config_command(
        bbox=bbox,
        start=start,
        end=end,
        source=source,
        track=track,
        swaths=swaths,
    )
    work_dir = resolve_work_dir(options)
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

    command, out_dir = build_from_template(template_file, inps.source)
    path = write_sweets_bash(command, out_dir)
    print(command.rstrip())
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
