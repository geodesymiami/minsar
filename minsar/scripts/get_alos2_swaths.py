#!/usr/bin/env python3
"""Find ALOS-2 swaths that cover an AOI and, when a template is given, write them there."""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import tempfile
from pathlib import Path

from shapely.geometry import Polygon, box

EPILOG = """
Examples:
  get_alos2_swaths.py 4.107,4.33,9.054,9.36 /scratch/05861/tg851601/CameroonAlos2D89/SLC/
  get_alos2_swaths.py 4.107,4.33,9.054,9.36 /scratch/05861/tg851601/CameroonAlos2D89/SLC/ $TE/CameroonAlos2D89.template
"""

_SNWE_TOKEN = re.compile(r"^-?\d+(\.\d+)?(,-?\d+(\.\d+)?){3}$")
_FRAME_FILE = re.compile(r"-F(\d+)$")


def fix_argv(argv: list[str]) -> list[str]:
    """Keep a leading-minus SNWE token from being parsed as an option."""
    fixed = []
    for token in argv:
        if _SNWE_TOKEN.match(token) and token.startswith("-") and (not fixed or fixed[-1] != "--"):
            fixed.append("--")
        fixed.append(token)
    return fixed


def parse_snwe(text: str) -> tuple[float, float, float, float]:
    """Parse south,north,west,east."""
    if not _SNWE_TOKEN.match(text):
        raise SystemExit(f"SNWE must be south,north,west,east, got {text!r}")
    south, north, west, east = (float(part) for part in text.split(","))
    if south >= north:
        raise SystemExit(f"south must be less than north, got {text}")
    if west == east:
        raise SystemExit(f"west and east must differ, got {text}")
    return south, north, west, east


def template_options(template: Path) -> dict[str, str]:
    from minsar.objects.dataset_template import Template

    return Template(str(template)).get_options()


def reference_date(options: dict[str, str], date_dirs: list[str]) -> str:
    value = options.get("alos2Stack.referenceDate", "").strip()
    if value.lower() in ("", "auto", "none"):
        return date_dirs[0]
    if len(value) == 8 and value.isdigit():
        value = value[2:]
    if value not in date_dirs:
        raise SystemExit(f"alos2Stack.referenceDate {value} is not a directory under SLC")
    return value


def polarization(options: dict[str, str]) -> str:
    value = options.get("alos2Stack.polarization", "HH").strip()
    if value.lower() in ("", "auto", "none"):
        return "HH"
    return value.upper()


def template_swath(options: dict[str, str], key: str) -> int | None:
    """Return a swath number from the template, or None when the key is unset."""
    value = options.get(key, "").strip()
    if value.lower() in ("", "auto", "none"):
        return None
    if not re.fullmatch(r"\d+", value):
        raise SystemExit(f"{key} must be an integer, got {value!r}")
    return int(value)


def product_id(path: Path) -> str:
    """Scene id shared by a leader file and its IMG-*-Fn beams."""
    name = re.sub(r"^IMG-[HV]{2}-", "", path.name)
    name = re.sub(r"^LED-", "", name)
    return re.sub(r"-F\d+$", "", name)


def _meta_int(record, key: str) -> int:
    return int(record.metadata[key])


def _sensing_start(image_data) -> datetime.datetime:
    year = _meta_int(image_data, "Sensor acquisition year")
    day_of_year = _meta_int(image_data, "Sensor acquisition day of year")
    microseconds = image_data.metadata["Sensor acquisition micro-seconds of day"]
    return datetime.datetime(year, 1, 1) + datetime.timedelta(days=day_of_year - 1, seconds=microseconds * 1e-6)


def _look_side(scene_header) -> int:
    clock = float(scene_header.metadata["Sensor clock angle"])
    if clock == 90.0:
        return -1
    if clock == -90.0:
        return 1
    raise SystemExit(f"unknown look side, sensor clock angle {clock}")


def read_scene(image_path: Path, leader_path: Path) -> dict:
    """Read one beam's CEOS headers and orbit. The image body is not copied."""
    import isceobj.Sensor.MultiMode as MultiMode
    from isceobj.Planet.AstronomicalHandbook import Const

    with tempfile.TemporaryDirectory() as temporary:
        sensor = MultiMode.createSensor(sensor="ALOS2")
        sensor.configure()
        sensor.leaderFile = str(leader_path)
        sensor.imageFile = str(image_path)
        sensor.outputFile = os.path.join(temporary, "beam.slc")
        sensor.useVirtualFile = True
        image_fdr, image_data = sensor.readImage()
        _leader_fdr, scene_header, platform_position, _facility = sensor.readLeader()
        orbit = sensor.readOrbit(platform_position)

    mode = scene_header.metadata["Sensor ID and mode of operation for this channel"][10:12]
    if mode in ("08", "09"):
        prf = float(image_data.metadata["PRF"]) * 1.0e-3
        swath = _meta_int(image_data, "Scan ID")
    else:
        prf = float(scene_header.metadata["Pulse Repetition Frequency in mHz"]) * 1.0e-3
        swath = 1
    if swath < 1:
        match = _FRAME_FILE.search(image_path.name)
        swath = int(match.group(1)) if match else 1

    rate_mhz = int(scene_header.metadata["Range sampling rate in MHz"])
    range_pixel_size = Const.c / (2.0 * sensor.fsampConst[rate_mhz])
    number_of_samples = _meta_int(image_fdr, "Number of pixels per line per SAR channel")
    number_of_lines = _meta_int(image_fdr, "Number of SAR DATA records")
    starting_range = float(image_data.metadata["Slant range to 1st data sample"])
    return {
        "swath": swath,
        "starting_range": starting_range,
        "ending_range": starting_range + range_pixel_size * (number_of_samples - 1),
        "sensing_start": _sensing_start(image_data),
        "number_of_lines": number_of_lines,
        "prf": prf,
        "orbit": orbit,
        "side": _look_side(scene_header),
    }


def beam_outline(scene: dict) -> list[tuple[float, float]]:
    """Lon/lat samples along the near and far edges. Zero Doppler, ellipsoid height 0."""
    start = scene["sensing_start"]
    line_count = scene["number_of_lines"]
    times = [
        start + datetime.timedelta(seconds=line / scene["prf"])
        for line in (0, (line_count - 1) / 2.0, line_count - 1)
    ]
    ranges = (scene["starting_range"], scene["ending_range"])
    near = []
    far = []
    for azimuth_time in times:
        for index, slant_range in enumerate(ranges):
            llh = scene["orbit"].rdr2geo(azimuth_time, slant_range, height=0.0, side=scene["side"])
            if llh is None:
                raise SystemExit(f"swath {scene['swath']} could not be geolocated")
            point = (float(llh[1]), float(llh[0]))
            (near if index == 0 else far).append(point)
    return near + list(reversed(far))


def footprint_bounds(outline: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lons = [point[0] for point in outline]
    lats = [point[1] for point in outline]
    return min(lats), max(lats), min(lons), max(lons)


def covers_aoi(outline: list[tuple[float, float]], south: float, north: float, west: float, east: float) -> bool:
    swath = Polygon(outline + [outline[0]])
    if not swath.is_valid:
        swath = swath.buffer(0)
    return swath.intersects(box(min(west, east), south, max(west, east), north))


def collect_scenes(date_dir: Path, pol: str) -> list[dict]:
    images = sorted(path for path in date_dir.glob(f"IMG-{pol}-ALOS2*-F*") if path.is_file())
    if not images:
        raise SystemExit(f"no IMG-{pol}-ALOS2*-F* files in {date_dir}")
    leaders = {product_id(path): path for path in date_dir.glob("LED-ALOS2*") if path.is_file()}
    scenes = []
    for image in images:
        leader = leaders.get(product_id(image))
        if leader is None:
            raise SystemExit(f"no leader file for {image.name}")
        scenes.append(read_scene(image, leader))
    return sorted(scenes, key=lambda scene: scene["swath"])


def print_table(rows: list[dict]) -> None:
    header = f"{'swath':>5}  {'near_km':>8}  {'far_km':>8}  {'S':>8}  {'N':>8}  {'W':>9}  {'E':>9}  covers"
    print(header)
    for row in rows:
        south, north, west, east = row["bounds"]
        print(
            f"{row['swath']:5d}  {row['starting_range'] / 1000:8.1f}  {row['ending_range'] / 1000:8.1f}  "
            f"{south:8.3f}  {north:8.3f}  {west:9.3f}  {east:9.3f}  {'yes' if row['covers'] else 'no'}"
        )


def _equals_column(text: str) -> int:
    for line in text.splitlines():
        if line.lstrip().startswith("alos2Stack.") and "=" in line:
            return line.index("=")
    return 38


def _format_key(text: str, key: str, value: str) -> str:
    column = _equals_column(text)
    gap = max(1, column - len(key))
    return f"{key}{' ' * gap}= {value}"


_SWATH_NOTES = {
    "alos2Stack.startingSwath": "auto for the swaths that cover the AOI",
    "alos2Stack.endingSwath": "auto for the swaths that cover the AOI; set both or neither",
}


def _swath_comment(line: str, key: str) -> str:
    """Keep the note after the value. Two spaces, then #, matching processing_Alos2.template."""
    raw = line.split("=", 1)[1] if "=" in line else ""
    raw = raw.split("\n", 1)[0]
    if "#" in raw:
        body = raw.split("#", 1)[1].strip()
    else:
        parts = raw.split(None, 1)
        body = parts[1].strip() if len(parts) > 1 else ""
    body = re.sub(r"^\[int\],\s*", "", body).strip()
    if not body:
        body = _SWATH_NOTES[key]
    return f"  # {body}"


def write_template(template: Path, starting: int, ending: int) -> None:
    text = template.read_text()
    keys = {
        "alos2Stack.startingSwath": str(starting),
        "alos2Stack.endingSwath": str(ending),
    }
    lines = text.splitlines(keepends=True)
    present = set()
    updated = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in keys:
            newline = "\n" if line.endswith("\n") else ""
            updated.append(_format_key(text, key, keys[key]) + _swath_comment(line, key) + newline)
            present.add(key)
        else:
            updated.append(line)
    missing = [key for key in keys if key not in present]
    if missing:
        insert_at = 0
        for index, line in enumerate(updated):
            if line.lstrip().startswith("alos2Stack."):
                insert_at = index + 1
        block = "".join(
            _format_key(text, key, keys[key]) + f"  # {_SWATH_NOTES[key]}\n" for key in missing
        )
        updated.insert(insert_at, block)
    template.write_text("".join(updated))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find ALOS-2 swaths that cover an AOI. With TEMPLATE, write the swath range when it differs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument("snwe", metavar="SNWE", help="south,north,west,east")
    parser.add_argument("slc_dir", metavar="SLC_DIR", help="project SLC directory")
    parser.add_argument("template", nargs="?", metavar="TEMPLATE", help="template to update when the swath range differs")
    args = parser.parse_args(fix_argv(sys.argv[1:] if argv is None else list(argv)))

    south, north, west, east = parse_snwe(args.snwe)
    slc_dir = Path(args.slc_dir)
    if not slc_dir.is_dir():
        raise SystemExit(f"SLC directory not found: {slc_dir}")
    date_dirs = sorted(path.name for path in slc_dir.iterdir() if path.is_dir() and re.fullmatch(r"\d{6}", path.name))
    if not date_dirs:
        raise SystemExit(f"no YYMMDD acquisition directories in {slc_dir}")

    template = Path(args.template) if args.template else None
    if template is not None and not template.is_file():
        raise SystemExit(f"template not found: {template}")
    options = template_options(template) if template is not None else {}
    date = reference_date(options, date_dirs)
    pol = polarization(options)
    scenes = collect_scenes(slc_dir / date, pol)

    rows = []
    for scene in scenes:
        outline = beam_outline(scene)
        rows.append({
            **scene,
            "bounds": footprint_bounds(outline),
            "covers": covers_aoi(outline, south, north, west, east),
        })
    print(f"date {date}  polarization {pol}")
    print_table(rows)

    covering = [row["swath"] for row in rows if row["covers"]]
    if not covering:
        raise SystemExit("no swath covers the AOI")
    starting, ending = min(covering), max(covering)
    print(f"alos2Stack.startingSwath = {starting}")
    print(f"alos2Stack.endingSwath = {ending}")
    if template is None:
        return 0
    current_start = template_swath(options, "alos2Stack.startingSwath")
    current_end = template_swath(options, "alos2Stack.endingSwath")
    if current_start == starting and current_end == ending:
        print(f"{template} already has startingSwath {starting} and endingSwath {ending}")
        return 0
    write_template(template, starting, ending)
    print(f"Wrote {template}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
