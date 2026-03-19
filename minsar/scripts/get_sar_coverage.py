#!/usr/bin/env python3
"""
Show SAR sensor coverage (orbits, incidence, subswath, acquisition count) for an AOI.

For each platform and flight direction, reports relative orbit numbers ordered by
incidence angle, incidence angles, subswaths (Sentinel-1 only), and optionally
acquisition counts.

Strategy:
  Discovery:
    - S1/BURST: default period 2020-01-01 to 2020-02-01 (--start/--end). SLC maxResults=20, BURST maxResults=200.
    - NISAR: fixed period 2026-01-01 to 2026-02-28 for discovery.
    - ALOS-2: asf.search(maxResults=10000) over --start/--end.
  Counting (always):
    - Date range: full period (2014-10-01 to today) unless --startDate/--endDate are set.
    - S1: search by intersection, then keep only dates where the product footprint covers/contains
      the AOI (Shapely); report touch vs min distance per orbit (verbose); acquisitions not covering
      are removed; orbits with count 0 are omitted from the table.
    - Others: ?output=count HTTP request.
    - Count requests run in parallel (default max_workers=8) to reduce time.

Search product types:
  Sentinel-1 : SLC  +  BURST (last date only, subswath detection)
  NISAR       : RSLC
  ALOS-2      : L1.1  (covers all beam modes incl. WD1/WD2 ScanSAR and stripmap)
"""

import argparse
import concurrent.futures
import datetime
import math
import re
import sys
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

import requests
import asf_search as asf
from shapely import wkt as _shapely_wkt
from shapely.geometry import shape as _shapely_shape
from asf_search.constants import INTERNAL

INTERNAL.CMR_TIMEOUT = 90

EPILOG = """
Examples:
  get_sar_coverage.py "POLYGON((25.3058 36.3221,25.5015 36.3221,25.5015 36.5019,25.3058 36.5019,25.3058 36.3221))"
  get_sar_coverage.py 36.322:36.502,25.306:25.502
  get_sar_coverage.py 36.322:36.502,25.306:25.502 --platforms S1
  get_sar_coverage.py 36.33:36.485,25.32:25.502 --platforms S1 -v
  get_sar_coverage.py 19.30:19.6,-155.8:-154.8 --platforms S1,ALOS2 --all
  get_sar_coverage.py 36.322:36.502,25.306:25.502 --platforms S1 --select   # parseable vars for bash

Select (--select): requires exactly one platform (--platforms S1 or NISAR or ALOS2). Prints asc_relorbit, asc_label, desc_relorbit, desc_label to stdout (progress to stderr). In bash: eval $(get_sar_coverage.py AOI --platforms S1 --select); then use $asc_relorbit, $desc_relorbit, $asc_label, $desc_label.

Notes:
  NISAR RSLC data availability depends on mission phase.
  ALOS-2 L1.1 covers all beam modes; use --platforms ALOS2 to search only ALOS-2.

Caveats:
  Coverage counts may be inaccurate due to orbit variations; only --all gives accurate counts.
  Min distance to footprint edge is approximate (degrees-to-meters at AOI latitude).
"""

# Lat/lon deltas for topsStack.boundingBox expansion (same as convert_bbox.py)
_BBOX_LAT_DELTA = 0.15
_BBOX_LON_DELTA = 1.5

# ASF Search API endpoint used for count-only requests
_ASF_API_URL = "https://api.daac.asf.alaska.edu/services/search/param"

# Number of results fetched for orbit discovery
_DISCOVERY_MAX_RESULTS = 10000
# S1 discovery: default max granules for orbit discovery (override with --max-discovery)
_DISCOVERY_MAX_RESULTS_S1_DEFAULT = 20

# Default date range for acquisition counts when --count (full catalog period unless --startDate/--endDate)
_COUNT_START_DEFAULT = datetime.date(2014, 10, 1)  # S1 operational
_COUNT_MAX_WORKERS = 8  # parallel count requests

# Default discovery end (short window for faster S1/BURST queries)
_DISCOVERY_END_DEFAULT = '2020-02-01'
# NISAR discovery period (mission data in this window)
_NISAR_DISCOVERY_START = datetime.date(2026, 1, 1)
_NISAR_DISCOVERY_END = datetime.date(2026, 2, 28)

# ALOS-2 discovery: 3-year period, HH only (HH+HV section commented out)
_ALOS2_DISCOVERY_START = datetime.date(2020, 1, 1)
_ALOS2_DISCOVERY_END = datetime.date(2022, 12, 31)
_ALOS2_DISCOVERY_MAX_RESULTS = 100

# Approximate mean incidence angles per S1 IW subswath (fallback when API returns None)
_S1_SUBSWATH_INC_APPROX = {'IW1': 33.8, 'IW2': 38.8, 'IW3': 43.2}


# ---------------------------------------------------------------------------
# Input / coordinate helpers
# ---------------------------------------------------------------------------

def parse_aoi(arg: str) -> str:
    """Convert AOI argument to WKT POLYGON string.

    Accepts:
      WKT POLYGON : 'POLYGON((lon lat, ...))'
      bounds      : 'lat_min:lat_max,lon_min:lon_max'
    """
    arg = arg.strip()
    if arg.upper().startswith('POLYGON'):
        return arg
    try:
        lat_part, lon_part = arg.split(',', 1)
        lat_min, lat_max = map(float, lat_part.split(':'))
        lon_min, lon_max = map(float, lon_part.split(':'))
        return (
            f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},"
            f"{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
        )
    except Exception:
        raise ValueError(
            f"Cannot parse AOI: '{arg}'. "
            "Use WKT POLYGON or lat_min:lat_max,lon_min:lon_max"
        )


def parse_bbox(wkt: str) -> Tuple[float, float, float, float]:
    """Extract (lon_min, lat_min, lon_max, lat_max) from a WKT POLYGON string."""
    nums = re.findall(r'[-+]?\d+\.?\d*', wkt)
    pairs = [(float(nums[i]), float(nums[i + 1])) for i in range(0, len(nums) - 1, 2)]
    lons = [p[0] for p in pairs]
    lats = [p[1] for p in pairs]
    return min(lons), min(lats), max(lons), max(lats)


# ---------------------------------------------------------------------------
# Property extraction helpers
# ---------------------------------------------------------------------------

def _get_inc(product) -> Optional[float]:
    """Extract incidence / off-nadir angle from an ASFProduct."""
    for key in ('offNadirAngle', 'offNadir', 'incidenceAngle'):
        val = product.properties.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    for attr in ('OFF_NADIR_ANGLE', 'INCIDENCE_ANGLE'):
        val = product.umm_get(
            product.umm, 'AdditionalAttributes', ('Name', attr), 'Values', 0
        )
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return None


def _get_orbit(product) -> Optional[int]:
    """Extract relative orbit / path number from an ASFProduct.

    Tries multiple property names to handle NISAR and other platforms.
    """
    for key in ('pathNumber', 'relativeOrbit'):
        val = product.properties.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    for attr in ('PATH_NUMBER', 'RELATIVE_ORBIT', 'ORBIT'):
        val = product.umm_get(
            product.umm, 'AdditionalAttributes', ('Name', attr), 'Values', 0
        )
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    return None


def _get_subswath_s1(product) -> str:
    """Extract IW subswath (IW1/IW2/IW3) from a Sentinel-1 BURST product."""
    burst_dict = product.properties.get('burst') or {}
    sw = burst_dict.get('subswath') or burst_dict.get('subSwath')
    if sw:
        return str(sw).upper()
    name = product.properties.get('sceneName', '')
    m = re.search(r'IW[123]', name, re.IGNORECASE)
    if m:
        return m.group(0).upper()
    bmt = str(product.properties.get('beamModeType', '') or '')
    if re.match(r'IW[123]', bmt, re.IGNORECASE):
        return bmt.upper()[:3]
    return '-'


def _get_date(product) -> Optional[str]:
    """Extract acquisition date (YYYY-MM-DD)."""
    start = product.properties.get('startTime')
    if start is None:
        return None
    if hasattr(start, 'strftime'):
        return start.strftime('%Y-%m-%d')
    if isinstance(start, str):
        return start[:10]
    return None


def _get_direction(product) -> str:
    """Extract and normalize flight direction ('Ascending' | 'Descending' | '') from an ASFProduct.

    Falls back to UMM AdditionalAttributes when the properties dict has no value,
    which happens for some S1 SLC collections where flightDirection is None.
    """
    raw = product.properties.get('flightDirection')
    if raw:
        s = str(raw).upper().strip()
        if s.startswith('ASC'):
            return 'Ascending'
        if s.startswith('DESC'):
            return 'Descending'
    # Fallback: scan common UMM attribute names
    for attr in ('ASCENDING_DESCENDING', 'PASS_DIRECTION', 'ORBIT_DIRECTION', 'FLIGHT_DIRECTION'):
        val = product.umm_get(
            product.umm, 'AdditionalAttributes', ('Name', attr), 'Values', 0
        )
        if val:
            s = str(val).upper().strip()
            if s.startswith('ASC'):
                return 'Ascending'
            if s.startswith('DESC'):
                return 'Descending'
    return ''


# ---------------------------------------------------------------------------
# ASF API count helper
# ---------------------------------------------------------------------------

# Max granules to fetch when counting ALOS-2 unique acquisitions (avoids inflated granule count)
_ALOS2_COUNT_MAX_RESULTS = 1500

# Max S1 SLC granules to fetch when counting dates that fully cover the AOI (per orbit/direction)
_S1_FULL_COVERAGE_MAX_RESULTS = 5000
_S1_FULL_COVERAGE_MAX_RESULTS_ALL = 10000  # when --all

# Approximate meters per degree at equator; at latitude lat use 111320 * cos(radians(lat))
_METERS_PER_DEGREE_AT_EQUATOR = 111320.0
_MIN_DISTANCE_WARN_METERS = 300.0


def _degrees_to_meters_approx(d_deg: float, lat_deg: float) -> float:
    """Convert a small distance in degrees to meters (approximate, at given latitude)."""
    return d_deg * _METERS_PER_DEGREE_AT_EQUATOR * math.cos(math.radians(lat_deg))


def _s1_orbit_label(orbit: int, direction: str) -> str:
    """Return concise Sentinel-1 orbit label, e.g. 'SenA29' or 'SenD36'."""
    letter = 'A' if direction == 'Ascending' else 'D'
    return f"Sen{letter}{orbit}"


def _orbit_label(platform_short: str, orbit: int, direction: str) -> str:
    """Return concise orbit label, e.g. 'NisarA159' or 'Alos2D24'."""
    letter = 'A' if direction == 'Ascending' else 'D'
    display = 'Nisar' if platform_short == 'NISAR' else ('Alos2' if platform_short == 'ALOS2' else platform_short)
    return f"{display}{letter}{orbit}"


def _min_distance_to_footprint_deg(
    platform_name: str,
    orbit: int,
    direction: str,
    wkt: str,
    count_start,
    count_end,
    aoi_geom,
    max_results: int = 2000,
) -> Optional[float]:
    """Return min distance (degrees) from AOI boundary to footprint edge for covering granules, or None."""
    aoi_boundary = getattr(aoi_geom, 'boundary', None)
    if aoi_boundary is None or aoi_boundary.is_empty:
        return None
    try:
        if platform_name == 'NISAR':
            results = list(asf.search(
                platform=asf.PLATFORM.NISAR,
                processingLevel=asf.PRODUCT_TYPE.RSLC,
                dataset=asf.DATASET.NISAR,
                intersectsWith=wkt,
                start=str(count_start),
                end=str(count_end),
                relativeOrbit=orbit,
                flightDirection=direction.upper(),
                maxResults=max_results,
            ))
        elif platform_name in ('ALOS-2 HH', 'ALOS-2 HH+HV'):
            pol = 'HH+HV' if 'HH+HV' in platform_name else 'HH'
            pol_list = [p.strip() for p in pol.split('+')]
            results = list(asf.search(
                platform=asf.PLATFORM.ALOS,
                dataset=[asf.DATASET.ALOS_2],
                processingLevel=asf.PRODUCT_TYPE.L1_1,
                intersectsWith=wkt,
                start=str(count_start),
                end=str(count_end),
                polarization=pol_list,
                relativeOrbit=orbit,
                flightDirection=direction.upper(),
                maxResults=max_results,
            ))
        else:
            return None
    except Exception:
        return None
    min_deg: Optional[float] = None
    for p in results:
        geom = getattr(p, 'geometry', None) or p.properties.get('geometry')
        if not geom or not isinstance(geom, dict):
            continue
        try:
            footprint = _shapely_shape(geom)
        except Exception:
            continue
        if footprint.is_empty or not footprint.is_valid:
            continue
        if not (footprint.covers(aoi_geom) or aoi_geom.within(footprint)):
            continue
        fp_boundary = getattr(footprint, 'boundary', None)
        if fp_boundary is None or getattr(fp_boundary, 'is_empty', True):
            continue
        d = aoi_boundary.distance(fp_boundary)
        if min_deg is None or d < min_deg:
            min_deg = d
    return min_deg


def _s1_search_count_full_coverage(
    wkt: str,
    count_start,
    count_end,
    orbit: int,
    direction: str,
    verbose: bool = False,
    max_results: int = _S1_FULL_COVERAGE_MAX_RESULTS,
) -> Tuple[int, int, int, Optional[float]]:
    """Get S1 SLC count of acquisition dates where the product footprint covers/contains the AOI.

    Searches SLC granules that intersect the AOI, then keeps only those whose footprint
    (Shapely) covers or contains the AOI. Returns (unique_date_count, n_granules_removed, n_total_granules, min_dist_m).
    min_dist_m is None or the min distance to footprint edge in meters. When verbose, prints
    whether any granules touch the AOI boundary. Caller prints min distance and warning.
    """
    try:
        aoi_geom = _shapely_wkt.loads(wkt)
    except Exception as exc:
        if verbose:
            print(f"    [Warning] AOI WKT invalid: {exc}", file=sys.stderr)
        return (-1, 0, 0, None)
    aoi_boundary = getattr(aoi_geom, 'boundary', None)
    if aoi_boundary is not None and aoi_boundary.is_empty:
        aoi_boundary = None

    try:
        results = list(asf.search(
            platform=asf.PLATFORM.SENTINEL1,
            processingLevel=asf.PRODUCT_TYPE.SLC,
            dataset=asf.DATASET.SENTINEL1,
            intersectsWith=wkt,
            start=str(count_start),
            end=str(count_end),
            beamMode=asf.BEAMMODE.IW,
            polarization=['VV', 'VV+VH'],
            relativeOrbit=orbit,
            flightDirection=direction.upper(),
            maxResults=max_results,
        ))
    except Exception as exc:
        if verbose:
            print(f"    [Warning] S1 full-coverage search failed: {exc}", file=sys.stderr)
        return (-1, 0, 0, None)

    n_total = len(results)
    dates_full = set()
    n_removed = 0
    any_touch_boundary = False
    min_boundary_distance: Optional[float] = None

    for p in results:
        geom = getattr(p, 'geometry', None) or p.properties.get('geometry')
        if not geom or not isinstance(geom, dict):
            n_removed += 1
            continue
        try:
            footprint = _shapely_shape(geom)
        except Exception:
            n_removed += 1
            continue
        if footprint.is_empty or not footprint.is_valid:
            n_removed += 1
            continue

        covers_aoi = footprint.covers(aoi_geom) or aoi_geom.within(footprint)
        if covers_aoi:
            d = _get_date(p)
            if d:
                dates_full.add(d)
        else:
            n_removed += 1

        if aoi_boundary is not None and not aoi_boundary.is_empty:
            if footprint.touches(aoi_geom):
                any_touch_boundary = True
            # Min distance only over granules that fully cover the AOI. For partial-coverage
            # granules the footprint boundary touches/crosses the AOI boundary, so distance
            # would be 0 and would dominate the min. For covering granules, distance from
            # AOI boundary to footprint edge is the margin (gap) and is meaningful.
            if covers_aoi:
                fp_boundary = getattr(footprint, 'boundary', None)
                if fp_boundary is not None and not getattr(fp_boundary, 'is_empty', True):
                    d = aoi_boundary.distance(fp_boundary)
                    if min_boundary_distance is None or d < min_boundary_distance:
                        min_boundary_distance = d

    if verbose and any_touch_boundary:
        print(f"    {_s1_orbit_label(orbit, direction)}: some granules touch the AOI boundary")
    min_dist_m: Optional[float] = None
    if min_boundary_distance is not None:
        lat_deg = aoi_geom.centroid.y
        min_dist_m = _degrees_to_meters_approx(min_boundary_distance, lat_deg)
    return (len(dates_full), n_removed, n_total, min_dist_m)


def _alos2_search_count(
    wkt: str, count_start, count_end, orbit: int, direction: str, polarization: str, verbose: bool = False
) -> int:
    """Get ALOS-2 L1.1 **acquisition** count (unique dates) for one (orbit, direction) and polarization.

    Runs a search and counts unique startTime dates. search_count() returns granule count (many
    granules per ScanSAR acquisition), which is not meaningful; this returns unique dates.
    """
    pol_list = [p.strip() for p in polarization.split('+')] if '+' in polarization else [polarization]
    try:
        results = list(asf.search(
            platform=asf.PLATFORM.ALOS,
            dataset=[asf.DATASET.ALOS_2],
            processingLevel=asf.PRODUCT_TYPE.L1_1,
            intersectsWith=wkt,
            start=str(count_start),
            end=str(count_end),
            polarization=pol_list,
            relativeOrbit=orbit,
            flightDirection=direction.upper(),
            maxResults=_ALOS2_COUNT_MAX_RESULTS,
        ))
        dates = {_get_date(p) for p in results if _get_date(p)}
        return len(dates)
    except Exception as exc:
        if verbose:
            print(f"    [Warning] ALOS-2 acquisition count failed: {exc}", file=sys.stderr)
        return -1


def _api_count(params: dict, verbose: bool = False) -> int:
    """Fetch granule count from ASF Search API without downloading granule data.

    Sends a lightweight ?output=count request and parses the integer response.
    Returns -1 on failure.
    """
    p = dict(params, output='count')
    if verbose:
        qs = '&'.join(f'{k}={v}' for k, v in p.items())
        print(f"    count URL: {_ASF_API_URL}?{qs}")
    try:
        resp = requests.get(_ASF_API_URL, params=p, timeout=30)
        resp.raise_for_status()
        text = resp.text.strip()
        # Response is plain integer or JSON integer
        try:
            return int(text)
        except ValueError:
            pass
        data = resp.json()
        if isinstance(data, (int, float)):
            return int(data)
        if isinstance(data, dict):
            for k in ('count', 'hits', 'total'):
                if k in data:
                    return int(data[k])
    except Exception as exc:
        print(f"    [Warning] count request failed: {exc}", file=sys.stderr)
    return -1


# ---------------------------------------------------------------------------
# Platform-specific ASF queries
# ---------------------------------------------------------------------------

def _vprint(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg)


def _print_asf_code(verbose: bool, kwargs: dict) -> None:
    """Print the equivalent asf.search() Python call for manual use in a terminal.

    The WKT polygon is assigned to a separate 'wkt' variable so that terminal
    line-wrapping cannot split the string literal and cause a SyntaxError on paste.
    The code block has no leading indentation so it can be pasted directly.
    """
    if not verbose:
        return
    kw = dict(kwargs)
    wkt = kw.pop('intersectsWith', None)
    lines = ['  --- asf_search code (paste into Python) ---',
             'import asf_search as asf']
    if wkt is not None:
        lines.append(f'wkt = {wkt!r}')
    lines.append('results = asf.search(')
    if wkt is not None:
        lines.append('    intersectsWith=wkt,')
    for k, v in kw.items():
        lines.append(f'    {k}={v!r},')
    lines.append(')')
    lines.append('print(len(results))')
    lines.append("if results: print(results[0].properties)")
    lines.append('  ---')
    print('\n'.join(lines))


def _last_date_from_results(results: List) -> Optional[datetime.date]:
    """Return the most recent acquisition date found in results."""
    dates = [_get_date(p) for p in results if _get_date(p)]
    if not dates:
        return None
    return datetime.date.fromisoformat(max(dates))


def query_sentinel1(
    wkt: str, start, end, verbose: bool = False, max_results_s1: int = _DISCOVERY_MAX_RESULTS_S1_DEFAULT
) -> Tuple[List, List]:
    """Fetch S1 SLC products (orbit/direction discovery) plus a 30-day BURST query
    for subswath and incidence angle detection across all active orbits.

    max_results_s1: max SLC granules to fetch for discovery (default 20). Use --max-discovery to increase.
    Returns (slc_sample, burst_results).
    """
    _vprint(verbose, f"  query 1 (SLC, maxResults={max_results_s1}): "
                     f"platform=SENTINEL1  processingLevel=SLC  "
                     f"dataset=SENTINEL1  polarization=VV+VH")
    _s1_slc_kwargs = dict(
        platform=asf.PLATFORM.SENTINEL1,
        processingLevel=asf.PRODUCT_TYPE.SLC,
        intersectsWith=wkt,
        start=str(start),
        end=str(end),
        polarization=['VV', 'VV+VH'],
        dataset=[asf.DATASET.SENTINEL1],
        maxResults=max_results_s1,
    )
    _print_asf_code(verbose, _s1_slc_kwargs)
    slc_sample = []
    try:
        slc_sample = list(asf.search(**_s1_slc_kwargs))
    except Exception as exc:
        print(f"  [Warning] S1 SLC query failed: {exc}", file=sys.stderr)
    _vprint(verbose, f"  → {len(slc_sample)} results")

    # BURST query: same period as query 1, for subswath + incidence per orbit.
    burst_results = []
    if slc_sample:
        _vprint(verbose, f"  query 2 (BURST, same period, maxResults=200): start={start}  end={end}  "
                         f"(subswath + incidence detection for all orbits)")
        _s1_burst_kwargs = dict(
            platform=asf.PLATFORM.SENTINEL1,
            processingLevel=asf.PRODUCT_TYPE.BURST,
            intersectsWith=wkt,
            start=str(start),
            end=str(end),
            polarization=['VV'],
            dataset=[asf.DATASET.SLC_BURST],
            maxResults=200,
        )
        _print_asf_code(verbose, _s1_burst_kwargs)
        try:
            burst_results = list(asf.search(**_s1_burst_kwargs))
        except Exception as exc:
            print(f"  [Warning] S1 BURST query failed: {exc}", file=sys.stderr)
        _vprint(verbose, f"  → {len(burst_results)} results")
    else:
        _vprint(verbose, "  query 2 (BURST): skipped (no SLC results)")

    return slc_sample, burst_results


def query_nisar(wkt: str, start, end, verbose: bool = False) -> List:
    """Fetch up to 250 NISAR RSLC products for orbit/direction discovery."""
    _vprint(verbose, f"  query (RSLC, maxResults={_DISCOVERY_MAX_RESULTS}): "
                     f"dataset=NISAR  processingLevel=RSLC")
    _vprint(verbose, "  Note: if 0 results, NISAR RSLC may not yet be available for this AOI")
    _nisar_kwargs = dict(
        intersectsWith=wkt,
        start=str(start),
        end=str(end),
        dataset=['NISAR'],
        processingLevel=['RSLC'],
        maxResults=_DISCOVERY_MAX_RESULTS,
    )
    _print_asf_code(verbose, _nisar_kwargs)
    try:
        results = list(asf.search(**_nisar_kwargs))
        _vprint(verbose, f"  → {len(results)} results")
        return results
    except Exception as exc:
        print(f"  [Warning] NISAR query failed: {exc}", file=sys.stderr)
        return []


def query_alos2(
    wkt: str, start, end, polarization: str, max_results: int = _ALOS2_DISCOVERY_MAX_RESULTS, verbose: bool = False
) -> List:
    """Fetch ALOS-2 L1.1 products for one polarization (HH or HH+HV) for orbit/direction discovery."""
    pol_list = [p.strip() for p in polarization.split('+')] if '+' in polarization else [polarization]
    _vprint(verbose, f"  query (L1.1, polarization={polarization}, maxResults={max_results}): "
                     f"platform=ALOS  dataset=ALOS_2  processingLevel=L1.1  start={start}  end={end}")
    _alos2_kwargs = dict(
        platform=asf.PLATFORM.ALOS,
        dataset=[asf.DATASET.ALOS_2],
        processingLevel=asf.PRODUCT_TYPE.L1_1,
        intersectsWith=wkt,
        start=str(start),
        end=str(end),
        polarization=pol_list,
        maxResults=max_results,
    )
    _print_asf_code(verbose, _alos2_kwargs)
    try:
        results = list(asf.search(**_alos2_kwargs))
        _vprint(verbose, f"  → {len(results)} results")
        return results
    except Exception as exc:
        print(f"  [Warning] ALOS-2 polarization {polarization} query failed: {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Count-per-orbit via ASF API
# ---------------------------------------------------------------------------

# Map platform name to ASF API parameter values (ALOS-2 split by polarization for counts)
_COUNT_API_PARAMS = {
    'Sentinel-1':   {'platform': 'SENTINEL-1', 'processingLevel': 'SLC'},
    'NISAR':       {'platform': 'NISAR',       'processingLevel': 'RSLC'},
    'ALOS-2 HH':   {'platform': 'ALOS', 'dataset': 'ALOS_2', 'processingLevel': 'L1.1', 'polarization': 'HH'},
    # 'ALOS-2 HH+HV': {'platform': 'ALOS', 'dataset': 'ALOS_2', 'processingLevel': 'L1.1', 'polarization': 'HH+HV'},
}


def _fetch_one_count(
    platform_name: str,
    orbit: int,
    direction: str,
    wkt: str,
    count_start,
    count_end,
    verbose: bool,
    s1_max_results: int = _S1_FULL_COVERAGE_MAX_RESULTS,
) -> Tuple[Tuple[int, str], int, int, int, Optional[float]]:
    """Fetch count for one (orbit, direction). Returns ((orbit, direction), count, n_removed, n_total, min_dist_m)."""
    n_removed = 0
    n_total = 0
    min_dist_m: Optional[float] = None
    if platform_name == 'Sentinel-1':
        cnt, n_removed, n_total, min_dist_m = _s1_search_count_full_coverage(
            wkt, count_start, count_end, orbit, direction, verbose=verbose, max_results=s1_max_results
        )
    elif platform_name in ('ALOS-2 HH', 'ALOS-2 HH+HV'):
        pol = 'HH+HV' if 'HH+HV' in platform_name else 'HH'
        cnt = _alos2_search_count(wkt, count_start, count_end, orbit, direction, pol, verbose=False)
    else:
        base = _COUNT_API_PARAMS.get(platform_name, {})
        params = dict(
            base,
            intersectsWith=wkt,
            relativeOrbit=orbit,
            flightDirection=direction.upper(),
            start=str(count_start),
            end=str(count_end),
        )
        cnt = _api_count(params, verbose=False)
    return ((orbit, direction), cnt, n_removed, n_total, min_dist_m)


def fetch_orbit_counts(
    platform_name: str,
    orbit_directions: List[Tuple[int, str]],
    wkt: str,
    count_start,
    count_end,
    verbose: bool = False,
    parallel: bool = True,
    s1_max_results: int = _S1_FULL_COVERAGE_MAX_RESULTS,
) -> Tuple[Dict[Tuple[int, str], int], Dict[Tuple[int, str], int], Dict[Tuple[int, str], int], Dict[Tuple[int, str], Optional[float]]]:
    """Fetch acquisition count for each (orbit, direction) pair.

    Uses count_start/count_end for the date range (full period by default).
    For Sentinel-1: search by intersection then keep only dates where footprint covers AOI;
    returns (counts_dict, removed_per_key, total_per_key, min_dist_per_key). Others use ASF API
    ?output=count; removed_per_key, total_per_key, min_dist_per_key are empty. When parallel=True
    (default), runs concurrently.
    """
    if not orbit_directions:
        return ({}, {}, {}, {})
    removed_per_key: Dict[Tuple[int, str], int] = {}
    total_per_key: Dict[Tuple[int, str], int] = {}
    min_dist_per_key: Dict[Tuple[int, str], Optional[float]] = {}
    if verbose:
        print(f"  count date range: {count_start} to {count_end}")
        if platform_name == 'Sentinel-1':
            print("  S1: counting only dates where product footprint covers/contains AOI")
        if parallel and len(orbit_directions) > 1:
            print(f"  fetching {len(orbit_directions)} counts in parallel (max_workers={_COUNT_MAX_WORKERS})")
    counts: Dict[Tuple[int, str], int] = {}
    if parallel and len(orbit_directions) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=_COUNT_MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    _fetch_one_count,
                    platform_name,
                    orbit,
                    direction,
                    wkt,
                    count_start,
                    count_end,
                    verbose,
                    s1_max_results,
                ): (orbit, direction)
                for orbit, direction in orbit_directions
            }
            for fut in concurrent.futures.as_completed(futures):
                try:
                    (orbit, direction), cnt, n_rem, n_tot, min_d = fut.result()
                    key = (orbit, direction)
                    counts[key] = cnt
                    if platform_name == 'Sentinel-1':
                        removed_per_key[key] = n_rem
                        total_per_key[key] = n_tot
                        min_dist_per_key[key] = min_d
                    if verbose and platform_name != 'Sentinel-1':
                        print(f"  counted {platform_name} orbit={orbit} dir={direction}: {cnt}")
                except Exception as exc:
                    key = futures[fut]
                    counts[key] = -1
                    if verbose:
                        print(f"  [Warning] count failed for {key}: {exc}", file=sys.stderr)
    else:
        for orbit, direction in orbit_directions:
            if verbose and platform_name != 'Sentinel-1':
                print(f"  counting {platform_name} orbit={orbit} dir={direction}")
            if platform_name == 'Sentinel-1':
                cnt, n_rem, n_tot, min_d = _s1_search_count_full_coverage(
                    wkt, count_start, count_end, orbit, direction, verbose=verbose, max_results=s1_max_results
                )
                key = (orbit, direction)
                counts[key] = cnt
                removed_per_key[key] = n_rem
                total_per_key[key] = n_tot
                min_dist_per_key[key] = min_d
            elif platform_name in ('ALOS-2 HH', 'ALOS-2 HH+HV'):
                pol = 'HH+HV' if 'HH+HV' in platform_name else 'HH'
                counts[(orbit, direction)] = _alos2_search_count(
                    wkt, count_start, count_end, orbit, direction, pol, verbose=verbose
                )
            else:
                params = dict(
                    _COUNT_API_PARAMS.get(platform_name, {}),
                    intersectsWith=wkt,
                    relativeOrbit=orbit,
                    flightDirection=direction.upper(),
                    start=str(count_start),
                    end=str(count_end),
                )
                counts[(orbit, direction)] = _api_count(params, verbose=verbose)
    return (counts, removed_per_key, total_per_key, min_dist_per_key)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _build_orbit_metadata_map(burst_results: List) -> Dict[int, Dict]:
    """Build orbit → {'subswath': str, 'inc': float|None} from BURST results.

    Uses the most common subswath per orbit. Incidence is averaged across bursts;
    if the API returns None, falls back to the _S1_SUBSWATH_INC_APPROX table.
    """
    orbit_sws: Dict[int, List[str]] = defaultdict(list)
    orbit_incs: Dict[int, List[float]] = defaultdict(list)
    for p in burst_results:
        orbit = _get_orbit(p)
        if orbit is None:
            continue
        sw = _get_subswath_s1(p)
        if sw and sw != '-':
            orbit_sws[orbit].append(sw)
        inc = _get_inc(p)
        if inc is not None:
            orbit_incs[orbit].append(inc)

    result: Dict[int, Dict] = {}
    for orbit in set(orbit_sws) | set(orbit_incs):
        sws = orbit_sws.get(orbit, [])
        subswath = max(set(sws), key=sws.count) if sws else '-'
        incs = orbit_incs.get(orbit, [])
        inc: Optional[float]
        if incs:
            inc = round(sum(incs) / len(incs), 1)
        else:
            inc = _S1_SUBSWATH_INC_APPROX.get(subswath)
        result[orbit] = {'subswath': subswath, 'inc': inc}
    return result


def _aggregate(
    results: List,
    orbit_subswath_map: Optional[Dict],
    counts: Optional[Dict[Tuple[int, str], int]],
    verbose: bool = False,
) -> List[Dict]:
    """Aggregate results into per-(direction, orbit) rows.

    counts: if provided, {(orbit, direction): count} from the count API.
    Orbits sorted by incidence angle; unknown incidence goes last.
    """
    data: Dict[str, Dict] = defaultdict(lambda: defaultdict(lambda: {'incs': []}))

    n_skipped = 0
    n_no_dir = 0
    for p in results:
        direction = _get_direction(p)
        orbit = _get_orbit(p)
        if orbit is None:
            n_skipped += 1
            continue
        if not direction:
            n_no_dir += 1
            continue
        inc = _get_inc(p)
        if inc is not None:
            data[direction][orbit]['incs'].append(inc)
        else:
            # Ensure the orbit appears even without incidence data
            _ = data[direction][orbit]

    if verbose and n_skipped:
        print(f"  [Note] {n_skipped} results skipped (orbit number unavailable)")
    if verbose and n_no_dir:
        print(f"  [Note] {n_no_dir} results skipped (flight direction unavailable)")

    rows = []
    for direction in ['Ascending', 'Descending']:
        orbits = data.get(direction, {})
        orbit_records = []
        for orbit, info in orbits.items():
            incs = info['incs']
            mean_inc = round(sum(incs) / len(incs), 1) if incs else None

            meta = (orbit_subswath_map or {}).get(orbit, {})
            subswath = meta.get('subswath', '-') if isinstance(meta, dict) else str(meta)
            # Use incidence from BURST metadata when SLC products have none
            if mean_inc is None and isinstance(meta, dict):
                mean_inc = meta.get('inc')

            count = None
            if counts is not None:
                count = counts.get((orbit, direction))
                # Omit orbits with count 0 from the summary table
                if count == 0:
                    continue

            orbit_records.append({
                'orbit': orbit,
                'inc': mean_inc,
                'subswath': subswath,
                'count': count,
            })

        orbit_records.sort(key=lambda x: (x['inc'] is None, x['inc'] or 0))
        rows.append({'direction': direction, 'orbits': orbit_records})

    return rows


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _platform_key(platform_display_name: str) -> str:
    """Return short key for parseable output: S1, NISAR, ALOS2."""
    if platform_display_name == 'Sentinel-1':
        return 'S1'
    if platform_display_name == 'NISAR':
        return 'NISAR'
    if platform_display_name.startswith('ALOS-2'):
        return 'ALOS2'
    return platform_display_name.replace('-', '').replace(' ', '_')


def _best_orbit_for_direction(orbit_records: List[Dict], direction: str, platform_display_name: str) -> Optional[Dict]:
    """From orbit_records (same direction), return the orbit with highest incAngle, or first if no inc.

    Returns dict with 'orbit', 'label'. Label uses SenA29 / NisarA57 / Alos2D109 style (concatenated).
    """
    if not orbit_records:
        return None
    # Sort by inc descending (None last so we prefer known incidence)
    sorted_orbits = sorted(
        orbit_records,
        key=lambda x: (x['inc'] is None, -(x['inc'] or 0)),
    )
    best = sorted_orbits[0]
    orbit = best['orbit']
    if platform_display_name == 'Sentinel-1':
        label = _s1_orbit_label(orbit, direction)
    elif platform_display_name == 'NISAR':
        label = _orbit_label('NISAR', orbit, direction)
    else:
        label = _orbit_label('ALOS2', orbit, direction)
    return {'orbit': orbit, 'label': label}


def print_best_only(all_rows: List[Tuple[str, List[Dict]]], stream) -> None:
    """Print parseable key=value lines for best Asc/Desc orbit (max incAngle).

    Call only when exactly one platform is in all_rows (enforced by --select validation).
    Format: asc_relorbit=29, asc_label="SenA29", desc_relorbit=36, desc_label="SenD36".
    Suitable for: eval $(get_sar_coverage.py AOI --platforms S1 --select) in bash.
    """
    if not all_rows:
        return
    platform_display_name, rows = all_rows[0]
    best_by_dir = {}
    for row in rows:
        if not row['orbits']:
            continue
        direction = row['direction']
        best = _best_orbit_for_direction(row['orbits'], direction, platform_display_name)
        if best is not None:
            best_by_dir[direction] = best
    # Print relorbits first, then labels (expected by shell callers).
    for direction, key_prefix in [('Ascending', 'asc'), ('Descending', 'desc')]:
        if direction in best_by_dir:
            b = best_by_dir[direction]
            print(f"{key_prefix}_relorbit={b['orbit']}", file=stream)
    for direction, key_prefix in [('Ascending', 'asc'), ('Descending', 'desc')]:
        if direction in best_by_dir:
            b = best_by_dir[direction]
            print(f"{key_prefix}_label=\"{b['label']}\"", file=stream)


def _subset_str_from_wkt(wkt: str) -> str:
    """Return subset string lat_min:lat_max,lon_min:lon_max rounded to 3 decimals."""
    lon_min, lat_min, lon_max, lat_max = parse_bbox(wkt)
    lat_min_r = round(lat_min, 3)
    lat_max_r = round(lat_max, 3)
    lon_min_r = round(lon_min, 3)
    lon_max_r = round(lon_max, 3)
    return f"{lat_min_r}:{lat_max_r},{lon_min_r}:{lon_max_r}"


def _has_s1_coverage(all_rows: List[Tuple[str, List[Dict]]]) -> bool:
    for name, rows in all_rows:
        if name == 'Sentinel-1':
            for row in rows:
                if row['orbits']:
                    return True
    return False


def print_table(all_rows: List[Tuple[str, List[Dict]]], do_count: bool) -> None:
    show_sw = _has_s1_coverage(all_rows)

    max_orbits = max(
        (len(r['orbits']) for _, rows in all_rows for r in rows if r['orbits']),
        default=1,
    )

    W_PLAT  = 11  # was 12; remove 1 space before flightDir
    W_DIR   =  9  # was 11; remove 2 spaces after flightDir; Asc/Desc centered
    W_ORBIT =  8   # 'relOrbit'
    W_INC   =  8   # 'incAngle'
    W_SW    =  8   # 'subswath'
    W_CNT   =  5
    S = ' '
    V = '|'
    S_DIR   = ''   # no space between Platform and flightDir (removes 1 more before flightDir)

    def _dir_short(direction: str) -> str:
        return 'Asc' if direction == 'Ascending' else 'Desc'

    def _orbit_header() -> str:
        h = f" {V}{S}{'relOrbit':^{W_ORBIT}}{S}{'incAngle':^{W_INC}}"
        if show_sw:
            h += f"{S}{'subswath':^{W_SW}}"
        if do_count:
            h += f"{S}{'count':>{W_CNT}}"
        return h

    header = f"{'Platform':<{W_PLAT}}{S_DIR}{'flightDir':^{W_DIR}}"
    for _ in range(max_orbits):
        header += _orbit_header()
    print(header)
    sep = ''.join('|' if c == '|' else '-' for c in header)
    print(sep)

    for platform_name, rows in all_rows:
        for row in rows:
            dir_short = _dir_short(row['direction'])
            if not row['orbits']:
                print(f"{platform_name:<{W_PLAT}}{S_DIR}{dir_short:^{W_DIR}}  (no coverage)")
                continue
            line = f"{platform_name:<{W_PLAT}}{S_DIR}{dir_short:^{W_DIR}}"
            for i in range(max_orbits):
                if i < len(row['orbits']):
                    orb = row['orbits'][i]
                    inc_str = f"{orb['inc']:.1f}" if orb['inc'] is not None else '-'
                    line += f" {V}{S}{str(orb['orbit']):^{W_ORBIT}}{S}{inc_str:^{W_INC}}"
                    if show_sw:
                        line += f"{S}{orb['subswath']:^{W_SW}}"
                    if do_count:
                        cnt = orb['count']
                        line += f"{S}{str(cnt) if cnt is not None and cnt >= 0 else '?':>{W_CNT}}"
                else:
                    line += f" {V}{S}{'-':^{W_ORBIT}}{S}{'-':^{W_INC}}"
                    if show_sw:
                        line += f"{S}{'-':^{W_SW}}"
                    if do_count:
                        line += f"{S}{'':>{W_CNT}}"
            print(line)


def print_bbox_info(wkt: str) -> None:
    """Print topsStack/mintpy bbox strings (same format as convert_bbox.py)."""
    lon_min, lat_min, lon_max, lat_max = parse_bbox(wkt)

    lat_min_r = round(lat_min, 3)
    lat_max_r = round(lat_max, 3)
    lon_min_r = round(lon_min, 3)
    lon_max_r = round(lon_max, 3)

    lat_min_bbox = round(lat_min_r - _BBOX_LAT_DELTA, 1)
    lat_max_bbox = round(lat_max_r + _BBOX_LAT_DELTA, 1)
    lon_min_bbox = round(lon_min_r - _BBOX_LON_DELTA, 1)
    lon_max_bbox = round(lon_max_r + _BBOX_LON_DELTA, 1)

    subset_str = _subset_str_from_wkt(wkt)
    print(f"mintpy.subset.lalo                   = {subset_str}    #[S:N,W:E / no], auto for no")
    print(f"miaplpy.subset.lalo                  = {subset_str}    #[S:N,W:E / no], auto for no")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Show SAR sensor coverage (orbits, incidence, subswath, count) for an AOI.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument('aoi', help="WKT POLYGON or lat_min:lat_max,lon_min:lon_max")
    parser.add_argument('--platforms', default='all', metavar='PLATFORMS',
                        help=(
                            'Comma-separated platform list, or "all" (default). '
                            'Accepted names: '
                            'S1 / Sentinel-1 / SENTINEL-1 / SENTINEL1 for Sentinel-1; '
                            'NISAR for NISAR; '
                            'ALOS2 / ALOS-2 for ALOS-2. '
                            'Example: --platforms S1,ALOS2'
                        ))
    parser.add_argument('--start', default='2020-01-01', metavar='YYYY-MM-DD',
                        help='Start date for discovery queries (default: 2020-01-01)')
    parser.add_argument('--end', default=_DISCOVERY_END_DEFAULT, metavar='YYYY-MM-DD',
                        help='End date for discovery queries (default: 2020-02-01). S1 and BURST use this; NISAR uses 2026-01-01 to 2026-02-28.')
    parser.add_argument('--startDate', default=None, metavar='YYYY-MM-DD',
                        help='Start date for acquisition count range (default: 2014-10-01).')
    parser.add_argument('--endDate', default=None, metavar='YYYY-MM-DD',
                        help='End date for acquisition count range (default: today).')
    parser.add_argument('--max-discovery', type=int, default=_DISCOVERY_MAX_RESULTS_S1_DEFAULT,
                        metavar='N',
                        help='Max S1 SLC granules fetched for orbit discovery (default: %(default)s). Increase if orbits are missing.')
    parser.add_argument('--all', action='store_true', default=False,
                        help='Use full operating period and up to 10000 granules per orbit for accurate coverage counts (slower).')
    parser.add_argument('--verbose', '-v', action='store_true', default=False,
                        help='Print query parameters and URLs')
    parser.add_argument('--select', action='store_true', default=False,
                        help='Print parseable key=value lines for best Asc/Desc orbit (max incAngle). Requires exactly one --platforms (e.g. S1). '
                             'Bash: eval $(get_sar_coverage.py AOI --platforms S1 --select); then use $asc_relorbit, $desc_relorbit, $asc_label, $desc_label. Python: parse stdout line by line (split on "=").')
    return parser


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(iargs)

    try:
        wkt = parse_aoi(inps.aoi)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        start = datetime.datetime.strptime(inps.start, '%Y-%m-%d').date()
    except ValueError:
        print(f"Error: --start must be YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    try:
        end = datetime.datetime.strptime(inps.end, '%Y-%m-%d').date()
    except ValueError:
        print(f"Error: --end must be YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    # Count date range: full period (2014-10-01 to today) unless --startDate/--endDate
    count_start = _COUNT_START_DEFAULT
    count_end = datetime.date.today()
    if inps.startDate is not None:
        try:
            count_start = datetime.datetime.strptime(inps.startDate, '%Y-%m-%d').date()
        except ValueError:
            print(f"Error: --startDate must be YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    if inps.endDate is not None:
        try:
            count_end = datetime.datetime.strptime(inps.endDate, '%Y-%m-%d').date()
        except ValueError:
            print(f"Error: --endDate must be YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)

    def _normalize_platform(name: str) -> str:
        n = name.strip().upper().replace('-', '').replace('_', '')
        if n in ('S1', 'SENTINEL1'):
            return 'S1'
        if n == 'NISAR':
            return 'NISAR'
        if n in ('ALOS2', 'ALOS'):
            return 'ALOS2'
        return n  # pass through so unknown names produce a useful error

    platforms = {_normalize_platform(p) for p in inps.platforms.split(',')}
    if 'ALL' in platforms:
        platforms = {'S1', 'NISAR', 'ALOS2'}

    known = {'S1', 'NISAR', 'ALOS2'}
    unknown = platforms - known
    if unknown:
        print(f"Error: unknown platform(s): {', '.join(sorted(unknown))}. "
              f"Use S1, NISAR, ALOS2 (or 'all').", file=sys.stderr)
        sys.exit(1)

    if inps.select and len(platforms) != 1:
        print("Error: --select requires exactly one platform. Use --platforms S1 (or NISAR or ALOS2).", file=sys.stderr)
        sys.exit(1)

    if inps.select:
        inps._select_stdout = sys.stdout
        sys.stdout = sys.stderr

    _vprint(inps.verbose, f"AOI (WKT) : {wkt}")
    _vprint(inps.verbose, f"Discovery date range: {start} to {end}")
    _vprint(inps.verbose, f"Count date range: {count_start} to {count_end} (use --startDate/--endDate to override)")
    _vprint(inps.verbose, f"Platforms : {', '.join(sorted(platforms))}\n")
    print_bbox_info(wkt)

    aoi_geom = None
    try:
        aoi_geom = _shapely_wkt.loads(wkt)
    except Exception:
        pass

    s1_removed_per_key: Dict[Tuple[int, str], int] = {}
    s1_total_per_key: Dict[Tuple[int, str], int] = {}
    all_rows = []

    if 'S1' in platforms:
        print("\nQuerying Sentinel-1...")
        _vprint(inps.verbose, "  [Sentinel-1]")
        slc_sample, burst_results = query_sentinel1(
            wkt, start, end, verbose=inps.verbose, max_results_s1=inps.max_discovery
        )
        orbit_sw_map = _build_orbit_metadata_map(burst_results)

        orbit_dirs = list(dict.fromkeys([
            (int(orb), _get_direction(p))
            for p in slc_sample
            for orb in [_get_orbit(p)]
            if orb is not None and _get_direction(p)
        ]))
        _vprint(inps.verbose, "  [Sentinel-1 counts: footprint covers AOI]")
        s1_max = _S1_FULL_COVERAGE_MAX_RESULTS_ALL if inps.all else _S1_FULL_COVERAGE_MAX_RESULTS
        counts, removed_per_key, total_per_key, min_dist_per_key = fetch_orbit_counts(
            'Sentinel-1', orbit_dirs, wkt, count_start, count_end,
            verbose=inps.verbose,
            s1_max_results=s1_max,
        )
        s1_removed_per_key = removed_per_key
        s1_total_per_key = total_per_key

        if not inps.verbose:
            print(f"  {len(orbit_dirs)} orbit(s) found")
        for (orbit, direction) in sorted(orbit_dirs):
            n_rem = s1_removed_per_key.get((orbit, direction), 0)
            if n_rem > 0:
                n_tot = s1_total_per_key.get((orbit, direction), 0)
                if n_tot and n_rem == n_tot:
                    print(f"    {_s1_orbit_label(orbit, direction)}: all acquisitions removed by AOI check")
                else:
                    print(f"    {_s1_orbit_label(orbit, direction)}: {n_rem} out of {n_tot} acquisitions removed by AOI check")
        print()
        for (orbit, direction) in sorted(orbit_dirs):
            dist_m = min_dist_per_key.get((orbit, direction))
            if dist_m is not None:
                warn = " [Warning] [ AOI coverage may not apply to all dates; use --all ]." if dist_m < _MIN_DISTANCE_WARN_METERS else ""
                print(f"    {_s1_orbit_label(orbit, direction)}: min distance to footprint edge = {int(round(dist_m))} m{warn}")
        if inps.select:
            print()

        rows = _aggregate(slc_sample, orbit_sw_map, counts, verbose=inps.verbose)
        all_rows.append(('Sentinel-1', rows))

    if 'NISAR' in platforms:
        print("\nQuerying NISAR...")
        _vprint(inps.verbose, "  [NISAR]")
        nisar_sample = query_nisar(
            wkt, _NISAR_DISCOVERY_START, _NISAR_DISCOVERY_END, verbose=inps.verbose
        )

        counts = None
        if nisar_sample:
            orbit_dirs = list(dict.fromkeys([
                (int(orb), _get_direction(p))
                for p in nisar_sample
                for orb in [_get_orbit(p)]
                if orb is not None and _get_direction(p)
            ]))
            _vprint(inps.verbose, "  [NISAR counts via API]")
            counts, _, _, _ = fetch_orbit_counts(
                'NISAR', orbit_dirs, wkt, count_start, count_end,
                verbose=inps.verbose,
            )
            if not inps.verbose:
                print(f"  {len(orbit_dirs)} orbit(s) found")
            if aoi_geom is not None:
                for (orbit, direction) in sorted(orbit_dirs):
                    min_deg = _min_distance_to_footprint_deg(
                        'NISAR', orbit, direction, wkt, count_start, count_end, aoi_geom
                    )
                    if min_deg is not None:
                        lat_deg = aoi_geom.centroid.y
                        dist_m = _degrees_to_meters_approx(min_deg, lat_deg)
                        warn = " [Warning] [ AOI coverage may not apply to all dates; use --all ]." if dist_m < _MIN_DISTANCE_WARN_METERS else ""
                        print(f"    {_orbit_label('NISAR', orbit, direction)}: min distance to footprint edge = {int(round(dist_m))} m{warn}")
                if inps.select:
                    print()
        rows = _aggregate(nisar_sample, None, counts, verbose=inps.verbose)
        all_rows.append(('NISAR', rows))

    if 'ALOS2' in platforms:
        for pol_label, polarization in [('ALOS-2 HH', 'HH')]:  # ('ALOS-2 HH+HV', 'HH+HV') commented out
            print(f"\nQuerying {pol_label}...")
            _vprint(inps.verbose, f"  [{pol_label}]")
            alos_sample = query_alos2(
                wkt, _ALOS2_DISCOVERY_START, _ALOS2_DISCOVERY_END,
                polarization=polarization, max_results=_ALOS2_DISCOVERY_MAX_RESULTS, verbose=inps.verbose,
            )

            counts = None
            if alos_sample:
                orbit_dirs = list(dict.fromkeys([
                    (int(orb), _get_direction(p))
                    for p in alos_sample
                    for orb in [_get_orbit(p)]
                    if orb is not None and _get_direction(p)
                ]))
                _vprint(inps.verbose, f"  [{pol_label} counts via API]")
                counts, _, _, _ = fetch_orbit_counts(
                    pol_label, orbit_dirs, wkt, count_start, count_end,
                    verbose=inps.verbose,
                )
                if not inps.verbose:
                    print(f"  {len(orbit_dirs)} orbit(s) found")
                if aoi_geom is not None:
                    for (orbit, direction) in sorted(orbit_dirs):
                        min_deg = _min_distance_to_footprint_deg(
                            pol_label, orbit, direction, wkt, count_start, count_end, aoi_geom
                        )
                        if min_deg is not None:
                            lat_deg = aoi_geom.centroid.y
                            dist_m = _degrees_to_meters_approx(min_deg, lat_deg)
                            warn = " [Warning] [ AOI coverage may not apply to all dates; use --all ]." if dist_m < _MIN_DISTANCE_WARN_METERS else ""
                            print(f"    {_orbit_label('ALOS2', orbit, direction)}: min distance to footprint edge = {int(round(dist_m))} m{warn}")
                    if inps.select:
                        print()

            rows = _aggregate(alos_sample, None, counts, verbose=inps.verbose)
            all_rows.append((pol_label, rows))

    if inps.select:
        if hasattr(inps, '_select_stdout'):
            sys.stdout = inps._select_stdout
        print(f"processing_subset=\"{_subset_str_from_wkt(wkt)}\"", file=sys.stdout)
        print_best_only(all_rows, sys.stdout)
    else:
        print()
        print_table(all_rows, do_count=True)


if __name__ == '__main__':
    main()
