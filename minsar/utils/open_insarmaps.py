#!/usr/bin/env python3
"""Open an InsarMaps URL in Safari or Chrome via compiled AppleScript."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

DESCRIPTION = """\
Open an InsarMaps URL in Safari (default) or Chrome via compiled AppleScript.
TARGET is a dataset .h5/.he5 name or a full InsarMaps URL. --layout selects a
preset (etna-south default) or a file containing an InsarMaps URL (center, zoom,
ref point, scale). A full URL supplies host and
startDataset; a dataset name supplies startDataset only. MintPy aliases (--vlim,
--ref-lalo, --lalo, --start-date/--end-date) map to the matching InsarMaps
query parameters. After resizing a window, --print-bounds reports --bounds
values for the front Safari or Chrome window. Quote URLs that contain '&';
otherwise the shell truncates the command before startDataset.
"""

EXAMPLE = """\
Examples:
open_insarmaps.py S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat.h5
open_insarmaps.py S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat.h5 --refPointLat 37.4989 --refPointLon 15.0846
open_insarmaps.py S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat.h5 --layout etna-south
open_insarmaps.py "http://149.165.153.50/start/37.7189/15.3566/8.2384?startDataset=S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat&flyToDatasetCenter=false&refPointLat=37.496&refPointLon=15.09"
open_insarmaps.py S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat.h5 --vlim -2 2 --ref-lalo 37.4989,15.0846
open_insarmaps.py S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat.h5 --layout etna-north --browser chrome
open_insarmaps.py S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat.h5 --layout ~/etna_north1.txt
open_insarmaps.py --print-bounds
"""

_ETNA_BASE = {
    "host": "http://149.165.153.50",
    "lat": "37.6951",
    "lon": "15.1197",
    "zoom": "10.1932",
    "startDataset": "S1_asc_044_egms_IW2_220-221-222_VV_2020_2024_concat",
    "flyToDatasetCenter": "false",
    "refPointLat": "37.4989",
    "refPointLon": "15.0846",
    "colorscale": "velocity",
    "pixelSize": "2",
    "minScale": "-2",
    "maxScale": "2",
}

LAYOUTS = {
    "etna-south": dict(_ETNA_BASE),
    "etna-north": {**_ETNA_BASE, "refPointLat": "37.807", "refPointLon": "15.179"},
}

DEFAULT_BOUNDS = (500, 50, 1100, 1050)
DATASET_SUFFIXES = (".h5", ".he5", ".hdf5")
PATH_KEYS = ("host", "lat", "lon", "zoom")
QUERY_KEY_ORDER = (
    "startDataset",
    "flyToDatasetCenter",
    "pointLat",
    "pointLon",
    "refPointLat",
    "refPointLon",
    "colorscale",
    "pixelSize",
    "minScale",
    "maxScale",
    "autoColorScale",
    "opacity",
    "background",
    "contours",
    "startDate",
    "endDate",
)
CLI_STATE_KEYS = (
    "host",
    "lat",
    "lon",
    "zoom",
    "startDataset",
    "flyToDatasetCenter",
    "refPointLat",
    "refPointLon",
    "pointLat",
    "pointLon",
    "colorscale",
    "pixelSize",
    "opacity",
    "background",
    "contours",
    "autoColorScale",
    "minScale",
    "maxScale",
    "startDate",
    "endDate",
)


_LAT_LON_OPTIONS = frozenset(("--ref-lalo", "--lalo"))


def _looks_like_number(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


def normalize_lat_lon_argv(argv: list[str]) -> list[str]:
    """Rewrite '--ref-lalo LAT LON' / '--lalo LAT LON' to one LAT,LON token.

    argparse nargs='+' would otherwise swallow a following positional (e.g. a URL).
    """
    out: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        arg = argv[i]
        if arg in _LAT_LON_OPTIONS:
            out.append(arg)
            i += 1
            if i >= n:
                break
            first = argv[i]
            i += 1
            if "," in first:
                out.append(first)
            elif i < n and _looks_like_number(first) and _looks_like_number(argv[i]):
                out.append(f"{first},{argv[i]}")
                i += 1
            else:
                out.append(first)
            continue
        out.append(arg)
        i += 1
    return out


def parse_lat_lon(tokens, option):
    """Return (lat, lon) floats from ['lat,lon'] or ['lat', 'lon']."""
    if len(tokens) == 1 and "," in tokens[0]:
        parts = tokens[0].split(",")
        if len(parts) != 2:
            raise ValueError(f"Invalid {option}: {tokens[0]!r}")
        return float(parts[0]), float(parts[1])
    if len(tokens) == 2:
        return float(tokens[0]), float(tokens[1])
    raise ValueError(f"{option} expects LAT LON or LAT,LON; got {tokens!r}")


def _fmt(value) -> str:
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return format(value, ".10g")
    return str(value)


def looks_like_url(target: str) -> bool:
    text = target.strip()
    return text.startswith(("http://", "https://")) or "/start/" in text


def normalize_url(target: str) -> str:
    text = target.strip()
    if not text.startswith(("http://", "https://")):
        text = "http://" + text
    return text


def dataset_name_from_target(target: str) -> str:
    name = Path(target).name
    lower = name.lower()
    for suffix in DATASET_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


def resolve_layout(layout_arg: str | None) -> dict:
    """Return map state from a preset name or a file containing an InsarMaps URL."""
    if layout_arg is None:
        return dict(LAYOUTS["etna-south"])
    if layout_arg in LAYOUTS:
        return dict(LAYOUTS[layout_arg])
    path = Path(layout_arg).expanduser()
    if path.is_file():
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Layout file is empty: {path}")
        return parse_insarmaps_url(content)
    presets = ", ".join(sorted(LAYOUTS))
    raise ValueError(f"Unknown layout {layout_arg!r}; use a preset ({presets}) or a layout file path")


def parse_insarmaps_url(target: str) -> dict:
    """Parse origin, /start/lat/lon/zoom, and query parameters from an InsarMaps URL."""
    parsed = urlparse(normalize_url(target))
    if not parsed.netloc:
        raise ValueError(f"Cannot parse InsarMaps URL: {target}")
    parts = [p for p in parsed.path.split("/") if p]
    try:
        start_index = parts.index("start")
        lat, lon, zoom = parts[start_index + 1], parts[start_index + 2], parts[start_index + 3]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"URL path does not have /start/<lat>/<lon>/<zoom>: {target}") from exc
    state = {
        "host": f"{parsed.scheme}://{parsed.netloc}",
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
    }
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "contour" and "contours" not in state:
            state["contours"] = value
        else:
            state[key] = value
    return state


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument("target", nargs="?", help="Dataset file/name (.h5/.he5 suffix stripped) or full InsarMaps URL")
    parser.add_argument("--layout", metavar="PRESET|FILE", help="Preset view or file with an InsarMaps URL (default: etna-south)")
    parser.add_argument("--browser", choices=("safari", "chrome"), default="safari", help="Browser to open (default: safari)")
    parser.add_argument(
        "--bounds", nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
        default=list(DEFAULT_BOUNDS), help="AppleScript window bounds (default: 500 50 1100 1050)",
    )
    parser.add_argument("--host", "--base-url", dest="host", metavar="HOST", help="InsarMaps origin (default: from layout or URL)")
    parser.add_argument("--lat", metavar="LAT", help="Map center latitude")
    parser.add_argument("--lon", metavar="LON", help="Map center longitude")
    parser.add_argument("--zoom", metavar="ZOOM", help="Map zoom")
    parser.add_argument("--startDataset", help="InsarMaps startDataset name")
    parser.add_argument("--refPointLat", metavar="LAT", help="Reference-point latitude")
    parser.add_argument("--refPointLon", metavar="LON", help="Reference-point longitude")
    parser.add_argument("--ref-lalo", metavar="LAT,LON", help="MintPy alias for --refPointLat/--refPointLon (LAT,LON or LAT LON)")
    parser.add_argument("--pointLat", metavar="LAT", help="Clicked-point latitude")
    parser.add_argument("--pointLon", metavar="LON", help="Clicked-point longitude")
    parser.add_argument("--lalo", metavar="LAT,LON", help="MintPy alias for --pointLat/--pointLon (LAT,LON or LAT LON)")
    parser.add_argument("--vlim", nargs=2, type=float, metavar=("MIN", "MAX"), help="MintPy alias for --minScale/--maxScale")
    parser.add_argument("--minScale", metavar="MIN", help="Color-scale minimum")
    parser.add_argument("--maxScale", metavar="MAX", help="Color-scale maximum")
    parser.add_argument("--pixelSize", metavar="SIZE", help="Marker pixel size")
    parser.add_argument("--colorscale", metavar="NAME", help="Color scale (e.g. velocity)")
    parser.add_argument("--autoColorScale", choices=("true", "false"), help="Auto color scale")
    parser.add_argument("--flyToDatasetCenter", choices=("true", "false"), help="Fly to dataset center")
    parser.add_argument("--startDate", help="Start date YYYYMMDD")
    parser.add_argument("--endDate", help="End date YYYYMMDD")
    parser.add_argument("--start-date", dest="start_date", metavar="YYYYMMDD", help="MintPy alias for --startDate")
    parser.add_argument("--end-date", dest="end_date", metavar="YYYYMMDD", help="MintPy alias for --endDate")
    parser.add_argument("--background", metavar="NAME", help="Map background")
    parser.add_argument("--opacity", metavar="N", help="Overlay opacity")
    parser.add_argument("--contours", "--contour", dest="contours", choices=("true", "false"), help="Show contours")
    parser.add_argument("--dry-run", action="store_true", help="Print URL and AppleScript; do not compile or open")
    parser.add_argument("--print-bounds", action="store_true", help="Print --bounds for the front Safari/Chrome window")
    return parser


def _check_alias_conflicts(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.vlim is not None and (args.minScale is not None or args.maxScale is not None):
        parser.error("use --vlim or --minScale/--maxScale, not both")
    if args.ref_lalo is not None and (args.refPointLat is not None or args.refPointLon is not None):
        parser.error("use --ref-lalo or --refPointLat/--refPointLon, not both")
    if args.lalo is not None and (args.pointLat is not None or args.pointLon is not None):
        parser.error("use --lalo or --pointLat/--pointLon, not both")
    if args.start_date is not None and args.startDate is not None:
        parser.error("use --start-date or --startDate, not both")
    if args.end_date is not None and args.endDate is not None:
        parser.error("use --end-date or --endDate, not both")


def initial_state(args: argparse.Namespace) -> dict:
    target = args.target
    is_url = bool(target) and looks_like_url(target)
    parsed_url = parse_insarmaps_url(target) if is_url else None
    if (
        parsed_url is not None
        and "?" in target
        and not parsed_url.get("startDataset")
        and not args.startDataset
    ):
        raise ValueError(
            "URL has no startDataset; quote the URL so the shell does not split on '&'"
        )

    if not target and not args.layout:
        raise ValueError("TARGET or --layout is required")

    state = resolve_layout(args.layout)
    if parsed_url is not None:
        state["host"] = parsed_url["host"]
        if parsed_url.get("startDataset"):
            state["startDataset"] = parsed_url["startDataset"]
    elif target:
        state["startDataset"] = dataset_name_from_target(target)
    return state


def apply_cli_overrides(state: dict, args: argparse.Namespace) -> None:
    for key in CLI_STATE_KEYS:
        value = getattr(args, key, None)
        if value is not None:
            state[key] = _fmt(value).rstrip("/") if key == "host" else _fmt(value)
    if args.vlim is not None:
        state["minScale"] = _fmt(args.vlim[0])
        state["maxScale"] = _fmt(args.vlim[1])
        state["autoColorScale"] = "false"
    if args.ref_lalo is not None:
        lat, lon = parse_lat_lon([args.ref_lalo], "--ref-lalo")
        state["refPointLat"] = _fmt(lat)
        state["refPointLon"] = _fmt(lon)
    if args.lalo is not None:
        lat, lon = parse_lat_lon([args.lalo], "--lalo")
        state["pointLat"] = _fmt(lat)
        state["pointLon"] = _fmt(lon)
    if args.start_date is not None:
        state["startDate"] = args.start_date
    if args.end_date is not None:
        state["endDate"] = args.end_date


def build_url(state: dict) -> str:
    missing = [key for key in ("host", "lat", "lon", "zoom", "startDataset") if not state.get(key)]
    if missing:
        raise ValueError("missing " + ", ".join(missing) + " (need a TARGET, --layout, or matching options)")
    host = str(state["host"]).rstrip("/")
    params = []
    seen = set()
    for key in QUERY_KEY_ORDER:
        value = state.get(key)
        if value not in (None, ""):
            params.append((key, str(value)))
            seen.add(key)
    for key, value in state.items():
        if key in PATH_KEYS or key in seen or value in (None, ""):
            continue
        params.append((key, str(value)))
    return f"{host}/start/{state['lat']}/{state['lon']}/{state['zoom']}?{urlencode(params)}"


def build_applescript(url: str, browser: str, bounds) -> str:
    left, top, right, bottom = bounds
    quoted = url.replace("\\", "\\\\").replace('"', '\\"')
    bounds_str = f"{{{left}, {top}, {right}, {bottom}}}"
    if browser == "chrome":
        return (
            f'set targetURL to "{quoted}"\n'
            "\n"
            'tell application "Google Chrome"\n'
            "    make new window\n"
            f"    set bounds of front window to {bounds_str}\n"
            "    set URL of active tab of front window to targetURL\n"
            "    activate\n"
            "end tell\n"
        )
    return (
        f'set targetURL to "{quoted}"\n'
        "\n"
        'tell application "Safari"\n'
        "    make new document\n"
        f"    set bounds of front window to {bounds_str}\n"
        "    set URL of front document to targetURL\n"
        "    activate\n"
        "end tell\n"
    )


def _browser_app_name(browser: str) -> str:
    return "Google Chrome" if browser == "chrome" else "Safari"


def parse_bounds_output(text: str) -> tuple[int, int, int, int]:
    cleaned = text.replace("{", " ").replace("}", " ").replace(",", " ")
    nums = [int(tok) for tok in cleaned.split() if tok.lstrip("-").isdigit()]
    if len(nums) < 4:
        raise RuntimeError(f"could not parse window bounds from: {text.strip()!r}")
    return nums[0], nums[1], nums[2], nums[3]


def query_front_window_bounds(browser: str) -> tuple[int, int, int, int]:
    osascript = shutil.which("osascript")
    if not osascript:
        raise RuntimeError("osascript not found; this command requires macOS")
    app = _browser_app_name(browser)
    script = f'tell application "{app}" to get bounds of front window'
    result = subprocess.run([osascript, "-e", script], check=True, capture_output=True, text=True)
    return parse_bounds_output(result.stdout)


def compile_and_run_applescript(script: str) -> None:
    osacompile = shutil.which("osacompile")
    osascript = shutil.which("osascript")
    if not osacompile or not osascript:
        raise RuntimeError("osacompile/osascript not found; this command requires macOS")
    with tempfile.TemporaryDirectory(prefix="open_insarmaps_") as tmp:
        src = Path(tmp) / "open_insarmaps.applescript"
        compiled = Path(tmp) / "open_insarmaps.scpt"
        src.write_text(script, encoding="utf-8")
        subprocess.run([osacompile, "-o", str(compiled), str(src)], check=True)
        subprocess.run([osascript, str(compiled)], check=True)


def main(argv=None) -> int:
    parser = create_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(normalize_lat_lon_argv(argv))
    if args.print_bounds:
        try:
            left, top, right, bottom = query_front_window_bounds(args.browser)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"--bounds {left} {top} {right} {bottom}")
        return 0
    _check_alias_conflicts(parser, args)
    try:
        state = initial_state(args)
        apply_cli_overrides(state, args)
        url = build_url(state)
    except ValueError as exc:
        parser.error(str(exc))
    script = build_applescript(url, args.browser, args.bounds)
    print(url)
    if args.dry_run:
        print()
        print(script, end="" if script.endswith("\n") else "\n")
        return 0
    try:
        compile_and_run_applescript(script)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
