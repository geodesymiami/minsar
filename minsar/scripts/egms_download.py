#!/usr/bin/env python3
"""List and download European Ground Motion Service (EGMS) products via the archive API.

Requires a CLMS API service key (JSON file). Set its path in password_config.py as:
  clms_service_key="/path/to/clms_service_key.json"

AOI may be S:N,W:E (lat_min:lat_max,lon_min:lon_max) or WKT POLYGON((lon lat,...)).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from minsar.utils.bbox_cli_argv import EGMS_DOWNLOAD_ARGV_KW, fix_argv_for_negative_bbox_sn_we
from minsar.utils.clms_auth import auth_headers, get_access_token, resolve_clms_service_key_path
from minsar.utils.convert_bbox import _input_to_bounds

API_ENDPOINT = "https://egms.land.copernicus.eu/insar-api/archive"
MAX_BBOX_DEG = 5.0
# Used when GET /releases is slow or unavailable (EGMS API is sometimes flaky).
FALLBACK_RELEASES = ["2020-2024", "2019-2023"]

EXAMPLE = """\
List and download EGMS products from the Copernicus Land Monitoring Service archive API.

Requires CLMS service key in ~/accounts/password_config.py (clms_service_key=...) or $SSARAHOME/password_config.py.
"""

EPILOG = """\
Examples:
  egms_download.py --aoi="37.525:37.825,15.050:15.210" --print
  egms_download.py --aoi="Polygon((14.75 37.51, 15.25 37.51, 15.25 37.88, 14.75 37.88, 14.75 37.51))" --print
  egms_download.py --intersectsWith="Polygon((14.75 37.51, 15.25 37.51, 15.25 37.88, 14.75 37.88, 14.75 37.51))" --print
  egms_download.py --aoi="37.525:37.825,15.050:15.210" --level L2A --download --dir=./egms
  egms_download.py --service-key ~/accounts/clms_service_key.json --aoi="37.525:37.825,15.050:15.210" --print
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument("--aoi", metavar="AOI", default=None, help="AOI: S:N,W:E or WKT POLYGON((lon lat,...))")
    parser.add_argument("--intersectsWith", dest="intersects_with", metavar="AOI", default=None, help="Alias for --aoi (ASF-style)")
    parser.add_argument("--level", default="L2A", metavar="LEVEL", help="Product level L2A, L2B, or L3 (default: L2A)")
    parser.add_argument("--releases", default=None, metavar="REL", help="Release id(s), comma-separated (default: latest from API)")
    parser.add_argument("--direction", default=None, metavar="DIR", help="ascending or descending")
    parser.add_argument("--relativeOrbit", dest="relative_orbit", type=int, default=None, metavar="ORBIT", help="Relative orbit")
    parser.add_argument("--swath", default=None, metavar="SWATH", help="Swath (e.g. IW1)")
    parser.add_argument("--print", dest="do_print", action="store_true", help="Print matching granules")
    parser.add_argument("--download", action="store_true", help="Download matching granules")
    parser.add_argument("--dir", dest="outdir", metavar="FOLDER", default=None, help="Download directory (default: ./egms)")
    parser.add_argument(
        "--service-key",
        "-k",
        metavar="PATH",
        default=None,
        help="CLMS service key JSON (default: ~/accounts/clms_service_key.json or password_config.clms_service_key)",
    )
    return parser


def normalize_level(level: str) -> str:
    """Normalize user level string to API form (L2A, L2B, L3)."""
    s = level.strip().upper().replace(" ", "")
    aliases = {"L2A": "L2A", "L2B": "L2B", "L3": "L3", "BASIC": "L2A", "CALIBRATED": "L2B", "ORTHO": "L3"}
    if s not in aliases:
        raise ValueError(f"Unsupported level '{level}'. Use L2A, L2B, or L3.")
    return aliases[s]


def aoi_to_egms_bbox(aoi: str) -> list[list[float]]:
    """Convert AOI string to EGMS bbox [[min_lon, min_lat], [max_lon, max_lat]].

    Raises ValueError if unparseable or span exceeds EGMS 5° limit.
    """
    s = aoi.strip()
    # convert_bbox removeprefix is case-sensitive; normalize WKT keyword
    if s[:7].upper() == "POLYGON":
        s = "POLYGON" + s[7:]
    min_lat, max_lat, min_lon, max_lon = _input_to_bounds(s)
    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon
    if lat_span > MAX_BBOX_DEG or lon_span > MAX_BBOX_DEG:
        raise ValueError(
            f"AOI span {lon_span:.3f}° lon × {lat_span:.3f}° lat exceeds EGMS max of {MAX_BBOX_DEG}°."
        )
    return [[min_lon, min_lat], [max_lon, max_lat]]


# Auth helpers live in minsar.utils.clms_auth (also used by clms_get_access_token.py).


def fetch_releases(headers: dict[str, str], api_endpoint: str = API_ENDPOINT) -> list[str]:
    r = requests.get(f"{api_endpoint}/releases", headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        raise RuntimeError(f"Failed to list releases: {data}")
    return list(data)


def pick_latest_release(releases: list[str]) -> str:
    """Pick latest release by end year then start year (e.g. 2020-2024 > 2019-2023)."""
    if not releases:
        raise ValueError("No releases available from EGMS API")

    def sort_key(rel: str) -> tuple[int, int]:
        parts = rel.replace("_", "-").split("-")
        try:
            nums = [int(p) for p in parts if p.isdigit()]
            if len(nums) >= 2:
                return (nums[1], nums[0])
            if nums:
                return (nums[0], nums[0])
        except ValueError:
            pass
        return (0, 0)

    return sorted(releases, key=sort_key)[-1]


def resolve_releases(headers: dict[str, str], explicit: str | None) -> list[str]:
    """Return release id(s) from --releases or latest from API (with fallback)."""
    if explicit:
        return [r.strip() for r in explicit.split(",") if r.strip()]
    try:
        available = fetch_releases(headers)
        latest = pick_latest_release(available)
        print(f"Using latest release: {latest}", file=sys.stderr)
        return [latest]
    except Exception as exc:  # noqa: BLE001
        latest = pick_latest_release(FALLBACK_RELEASES)
        print(
            f"Warning: could not fetch releases from EGMS API ({exc}); using {latest}",
            file=sys.stderr,
        )
        return [latest]


def build_search_query(
    *,
    bbox: list[list[float]],
    level: str,
    releases: list[str],
    direction: str | None = None,
    relative_orbit: int | None = None,
    swath: str | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "id": None,
        "bbox": bbox,
        "levels": [level],
        "releases": releases,
    }
    if direction:
        query["direction"] = direction.lower()
    if relative_orbit is not None:
        query["relativeOrbit"] = relative_orbit
    if swath:
        query["swath"] = swath
    return query


def search_products(
    headers: dict[str, str],
    query: dict[str, Any],
    api_endpoint: str = API_ENDPOINT,
) -> dict[str, Any]:
    r = requests.post(
        f"{api_endpoint}/search",
        headers=headers,
        data=json.dumps(query),
        timeout=120,
    )
    r.raise_for_status()
    result = r.json()
    if result.get("message") and not result.get("status", True) and not result.get("hits"):
        raise RuntimeError(result["message"])
    return result


def format_filesize(nbytes: int | None) -> str:
    if nbytes is None:
        return "?"
    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{int(size)}B" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}GB"


def format_hit_line(hit: dict[str, Any]) -> str:
    parts = [
        hit.get("filename", "?"),
        hit.get("productLevel", ""),
        hit.get("productType", ""),
        hit.get("release", ""),
        format_filesize(hit.get("filesize")),
    ]
    for key in ("direction", "relativeOrbit", "swath", "burstId", "tileId"):
        if hit.get(key) is not None:
            parts.append(f"{key}={hit[key]}")
    return "  ".join(str(p) for p in parts if p != "")


def print_hits(result: dict[str, Any]) -> None:
    hits = result.get("hits") or []
    print(f"Found {len(hits)} product(s)  query_id={result.get('id', '')}")
    for hit in hits:
        print(format_hit_line(hit))


def download_url(api_endpoint: str, filename: str, query_id: str) -> str:
    return f"{api_endpoint}/download/{filename}?id={query_id}"


def download_hits(
    headers: dict[str, str],
    result: dict[str, Any],
    outdir: Path,
    api_endpoint: str = API_ENDPOINT,
) -> list[Path]:
    hits = result.get("hits") or []
    query_id = result.get("id")
    if not query_id:
        raise RuntimeError("Search result has no query id; cannot download")
    outdir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for i, hit in enumerate(hits, 1):
        filename = hit.get("filename")
        if not filename:
            continue
        dest = outdir / filename
        url = download_url(api_endpoint, filename, query_id)
        print(f"[{i}/{len(hits)}] Downloading {filename} → {dest}")
        with requests.get(url, headers=headers, stream=True, timeout=600) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        saved.append(dest)
    return saved


def resolve_aoi(args: argparse.Namespace) -> str:
    aoi = args.aoi or args.intersects_with
    if not aoi:
        raise SystemExit("Error: provide --aoi (or --intersectsWith) with S:N,W:E or WKT POLYGON")
    return aoi


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    raw = fix_argv_for_negative_bbox_sn_we(raw, **EGMS_DOWNLOAD_ARGV_KW)
    parser = create_parser()
    args = parser.parse_args(raw)

    if not args.download:
        args.do_print = True

    try:
        level = normalize_level(args.level)
        aoi = resolve_aoi(args)
        bbox = aoi_to_egms_bbox(aoi)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        token_path = resolve_clms_service_key_path(args.service_key)
        access_token = get_access_token(token_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: authentication failed: {exc}", file=sys.stderr)
        return 1

    headers = auth_headers(access_token)

    try:
        releases = resolve_releases(headers, args.releases)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: could not determine releases: {exc}", file=sys.stderr)
        return 1

    query = build_search_query(
        bbox=bbox,
        level=level,
        releases=releases,
        direction=args.direction,
        relative_orbit=args.relative_orbit,
        swath=args.swath,
    )

    try:
        result = search_products(headers, query)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: search failed: {exc}", file=sys.stderr)
        return 1

    if args.do_print:
        print_hits(result)

    if args.download:
        outdir = Path(os.path.expandvars(args.outdir or "./egms")).expanduser()
        try:
            paths = download_hits(headers, result, outdir)
        except Exception as exc:  # noqa: BLE001
            print(f"Error: download failed: {exc}", file=sys.stderr)
            return 1
        print(f"Downloaded {len(paths)} file(s) to {outdir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
