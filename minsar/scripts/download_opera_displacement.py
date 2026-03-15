#!/usr/bin/env python3
"""
Download OPERA displacement products from ASF for a given area of interest.

Downloads both ascending and descending orbit data. OPERA Surface Displacement
(DISP) products are InSAR-derived displacement data from Sentinel-1. Uses
credentials from password_config.py (asfuser/asfpass), same as asf_search_args.py.
Falls back to .netrc or EARTHDATA_* env vars if password_config is not available.
"""

import argparse
import os
import re
import sys
from datetime import date, datetime


def parse_args():
    parser = argparse.ArgumentParser(
        description='Download OPERA displacement products from ASF for a polygon AOI.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
            Uses credentials from password_config.py (asfuser/asfpass), same as asf_search_args.py.
            Falls back to .netrc or EARTHDATA_* env vars if password_config is not available.

            Example:
            %(prog)s "POLYGON((-86.6038 12.3781,-86.4486 12.3781,-86.4486 12.4899,-86.6038 12.4899,-86.6038 12.3781))" --print
            %(prog)s "POLYGON((-86.6038 12.3781,-86.4486 12.3781,-86.4486 12.4899,-86.6038 12.4899,-86.6038 12.3781))" --download --dir ./opera_disp
                    """,
    )
    parser.add_argument(
        'polygon',
        type=str,
        help='WKT POLYGON string, e.g. POLYGON((-86.6 12.38,-86.45 12.38,-86.45 12.49,-86.6 12.49,-86.6 12.38))',
    )
    parser.add_argument(
        '--dir',
        type=str,
        default='.',
        metavar='FOLDER',
        help='Output directory for downloaded granules (default: current directory)',
    )
    parser.add_argument(
        '--print',
        dest='do_print',
        action='store_true',
        help='List granules only, do not download',
    )
    parser.add_argument(
        '--download',
        action='store_true',
        default=True,
        help='Download the data (default)',
    )
    parser.add_argument(
        '--ext',
        type=str,
        default=None,
        help='Optional file extension filter (e.g., nc, tif). If omitted, download all file types.',
    )

    parser.add_argument('--period', type=str, help='Start and end date for search, format YYYYMMDD:YYYYMMDD or YYYY-MM-DD:YYYY-MM-DD.')
    parser.add_argument('--start-date', type=str, default='20160701', help='Start date (YYYYMMDD or YYYY-MM-DD).')
    parser.add_argument('--end-date', type=str, default=date.today().isoformat(), help='End date (YYYYMMDD or YYYY-MM-DD).')

    args = parser.parse_args()

    try:
        if args.period:
            period = args.period.split(':')
            if len(period) != 2:
                parser.error("Invalid --period. Use START:END (YYYYMMDD or YYYY-MM-DD).")
            args.start_date = _to_iso_date(period[0])
            args.end_date = _to_iso_date(period[1])
        else:
            if args.start_date:
                args.start_date = _to_iso_date(args.start_date)
            if args.end_date:
                args.end_date = _to_iso_date(args.end_date)
    except ValueError as e:
        parser.error(str(e))

    return args


def collect_download_targets(results, ext=None):
    """
    If ext is provided (e.g., 'nc' or '.nc'), return matching file URLs.
    If ext is None/empty, return results unchanged (download all types).
    """
    if not ext:
        return results, "all file types"

    wanted = f".{str(ext).lower().lstrip('.')}"
    urls = []

    for g in results:
        try:
            links = g.data_links() or []
        except Exception:
            links = []

        for u in links:
            base = str(u).split("?", 1)[0].lower()
            if base.endswith(wanted):
                urls.append(str(u))  # keep original URL (with query)

    return urls, wanted


def _to_iso_date(value: str) -> str:
    """Accept YYYYMMDD or YYYY-MM-DD and return YYYY-MM-DD."""
    value = (value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Invalid date '{value}'. Use YYYYMMDD or YYYY-MM-DD.")


def parse_polygon(polygon_str: str) -> tuple[float, float, float, float]:
    """Extract bounding box (min_lon, min_lat, max_lon, max_lat) from WKT POLYGON string."""
    # POLYGON((-86.6038 12.3781,-86.4486 12.3781,...))
    match = re.search(r'POLYGON\s*\(\s*\(\s*(.+?)\s*\)\s*\)', polygon_str, re.DOTALL)
    if not match:
        raise ValueError(f"Cannot parse polygon: {polygon_str}")

    coords_str = match.group(1).strip()
    coords = []
    for pair in coords_str.split(','):
        parts = pair.strip().split()
        if len(parts) >= 2:
            lon, lat = float(parts[0]), float(parts[1])
            coords.append((lon, lat))

    if not coords:
        raise ValueError(f"No coordinates found in polygon: {polygon_str}")

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return min(lons), min(lats), max(lons), max(lats)


def _load_password_config():
    """Load ASF credentials from password_config.py (same as asf_search_args.py)."""
    for path in [
        os.environ.get('SSARAHOME'),
        os.path.join(os.environ.get('MINSAR_HOME', ''), 'minsar', 'utils', 'ssara_ASF'),
        os.path.join(os.environ.get('MINSAR_HOME', ''), 'tools', 'ssara_client'),
    ]:
        if path and os.path.isdir(path):
            if path not in sys.path:
                sys.path.insert(0, path)
            try:
                import password_config
                os.environ['EARTHDATA_USERNAME'] = password_config.asfuser
                os.environ['EARTHDATA_PASSWORD'] = password_config.asfpass
                return
            except (ImportError, AttributeError):
                pass


def main():
    args = parse_args()
    try:
        import earthaccess
    except ImportError:
        print("Error: earthaccess is required. Install with: pip install earthaccess")
        return 1

    # Parse polygon to bounding box
    try:
        min_lon, min_lat, max_lon, max_lat = parse_polygon(args.polygon)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    bbox = (min_lon, min_lat, max_lon, max_lat)
    print(f"Bounding box: {bbox}")
    print(f"Searching OPERA_L3_DISP-S1_V1 granules...")

    # Login to Earthdata - use password_config (same as asf_search_args.py)
    _load_password_config()
    try:
        earthaccess.login()
    except Exception as e:
        print(f"Earthdata login failed: {e}")
        print("Configure password_config.py (asfuser/asfpass) or .netrc or EARTHDATA_* env vars")
        return 1

    # Search for granules - bbox search returns all overlapping granules,
    # including both ascending and descending orbit directions
    # temporal = ('2016-07-01', date.today().isoformat())
    results = list(earthaccess.search_data(
        short_name='OPERA_L3_DISP-S1_V1',
        bounding_box=bbox,
        temporal=(args.start_date, args.end_date),

    ))
    print(f"Found {len(results)} granules (ascending + descending)")

    if not results:
        print("No granules found for this AOI and date range.")
        return 0

    if results:
        print(f"type(results[0]) = {type(results[0]).__name__}")
        try:
            print("data_links count:", len(results[0].data_links() or []))
        except Exception:
            print("No data_links() on first result (likely collection-level result)")

    if args.do_print:
        for g in results:
            try:
                uid = g['meta']['granule_id'] if isinstance(g, dict) else getattr(g, 'granule_id', str(g))
            except (KeyError, TypeError):
                uid = str(g)[:80]
            print(f"  {uid}")
        return 0

    # Download (default when --print not given)
    os.makedirs(args.dir, exist_ok=True)
    print(f"Downloading to {os.path.abspath(args.dir)}...")

    targets, label = collect_download_targets(results, args.ext)

    if isinstance(targets, list):
        print(f"Found {len(targets)} files matching {label}")
        if not targets:
            print("No matching files to download.")
            return 0

    downloaded = earthaccess.download(targets, args.dir)
    print(f"Downloaded {len(downloaded)} files")
    return 0


if __name__ == '__main__':
    exit(main())
