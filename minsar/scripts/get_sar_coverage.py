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
  Counting (only with --count):
    - Date range: full period (2014-10-01 to today) unless --startDate/--endDate are set.
    - S1: asf.search_count() per (orbit, direction). Others: ?output=count HTTP request.
    - Count requests run in parallel (default max_workers=8) to reduce time.

Search product types:
  Sentinel-1 : SLC  +  BURST (last date only, subswath detection)
  NISAR       : RSLC
  ALOS-2      : L1.1  (covers all beam modes incl. WD1/WD2 ScanSAR and stripmap)
"""

import argparse
import concurrent.futures
import datetime
import re
import sys
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

import requests
import asf_search as asf
from asf_search.constants import INTERNAL

INTERNAL.CMR_TIMEOUT = 90

EPILOG = """
Examples:
  get_sar_coverage.py "POLYGON((25.3058 36.3221,25.5015 36.3221,25.5015 36.5019,25.3058 36.5019,25.3058 36.3221))"
  get_sar_coverage.py 36.322:36.502,25.306:25.502
  get_sar_coverage.py 36.322:36.502,25.306:25.502 --count
  get_sar_coverage.py 36.322:36.502,25.306:25.502 -c --platforms S1
  get_sar_coverage.py 19.30:19.6,-155.8:-154.8 -c --platforms S1,ALOS2

Notes:
  NISAR RSLC data availability depends on mission phase.
  ALOS-2 L1.1 covers all beam modes; use --platforms ALOS2 to search only ALOS-2.
"""

# Lat/lon deltas for topsStack.boundingBox expansion (same as convert_polygon_string.py)
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

def _s1_search_count(
    wkt: str, start, end, orbit: int, direction: str, verbose: bool = False
) -> int:
    """Get S1 SLC count for one (orbit, direction) using asf.search_count() when available.

    Falls back to _api_count() if search_count is missing or fails. direction should be
    'Ascending' or 'Descending'. Returns count, or -1 on failure.
    """
    search_count = getattr(asf, 'search_count', None)
    if search_count is not None:
        try:
            cnt = search_count(
                platform=asf.PLATFORM.SENTINEL1,
                processingLevel=asf.PRODUCT_TYPE.SLC,
                dataset=asf.DATASET.SENTINEL1,
                intersectsWith=wkt,
                start=str(start),
                end=str(end),
                beamMode=asf.BEAMMODE.IW,
                polarization=['VV', 'VV+VH'],
                relativeOrbit=orbit,
                flightDirection=direction.upper(),
            )
            return int(cnt) if cnt is not None else -1
        except Exception as exc:
            if verbose:
                print(f"    [Warning] asf.search_count failed: {exc}", file=sys.stderr)
    # Fallback: same params as _COUNT_API_PARAMS['Sentinel-1']
    params = dict(
        platform='SENTINEL-1',
        processingLevel='SLC',
        intersectsWith=wkt,
        relativeOrbit=orbit,
        flightDirection=direction.upper(),
        start=str(start),
        end=str(end),
    )
    return _api_count(params, verbose=verbose)


# Max granules to fetch when counting ALOS-2 unique acquisitions (avoids inflated granule count)
_ALOS2_COUNT_MAX_RESULTS = 1500


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
) -> Tuple[Tuple[int, str], int]:
    """Fetch count for one (orbit, direction). Returns ((orbit, direction), count)."""
    if platform_name == 'Sentinel-1':
        cnt = _s1_search_count(wkt, count_start, count_end, orbit, direction, verbose=False)
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
    return ((orbit, direction), cnt)


def fetch_orbit_counts(
    platform_name: str,
    orbit_directions: List[Tuple[int, str]],
    wkt: str,
    count_start,
    count_end,
    verbose: bool = False,
    parallel: bool = True,
) -> Dict[Tuple[int, str], int]:
    """Fetch acquisition count for each (orbit, direction) pair.

    Uses count_start/count_end for the date range (full period by default).
    For Sentinel-1 uses asf.search_count(); others use ASF API ?output=count.
    When parallel=True (default), runs count requests concurrently.
    """
    if not orbit_directions:
        return {}
    if verbose:
        print(f"  count date range: {count_start} to {count_end}")
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
                ): (orbit, direction)
                for orbit, direction in orbit_directions
            }
            for fut in concurrent.futures.as_completed(futures):
                try:
                    (orbit, direction), cnt = fut.result()
                    counts[(orbit, direction)] = cnt
                    if verbose:
                        print(f"  counted {platform_name} orbit={orbit} dir={direction}: {cnt}")
                except Exception as exc:
                    key = futures[fut]
                    counts[key] = -1
                    if verbose:
                        print(f"  [Warning] count failed for {key}: {exc}", file=sys.stderr)
    else:
        for orbit, direction in orbit_directions:
            if verbose:
                print(f"  counting {platform_name} orbit={orbit} dir={direction}")
            if platform_name == 'Sentinel-1':
                counts[(orbit, direction)] = _s1_search_count(
                    wkt, count_start, count_end, orbit, direction, verbose=verbose
                )
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
    return counts


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

    W_PLAT  = 12
    W_DIR   = 11
    W_ORBIT =  8   # 'relOrbit'
    W_INC   =  8   # 'incAngle'
    W_SW    =  8   # 'subswath'
    W_CNT   =  5
    S = ' '

    def _orbit_header() -> str:
        h = f"{S}{'relOrbit':^{W_ORBIT}}{S}{'incAngle':^{W_INC}}"
        if show_sw:
            h += f"{S}{'subswath':^{W_SW}}"
        if do_count:
            h += f"{S}{'count':>{W_CNT}}"
        return h

    header = f"{'Platform':<{W_PLAT}}{S}{'flightDir':<{W_DIR}}"
    for _ in range(max_orbits):
        header += _orbit_header()
    print(header)
    print('-' * len(header))

    for platform_name, rows in all_rows:
        for row in rows:
            if not row['orbits']:
                print(f"{platform_name:<{W_PLAT}}{S}{row['direction']:<{W_DIR}}  (no coverage)")
                continue
            line = f"{platform_name:<{W_PLAT}}{S}{row['direction']:<{W_DIR}}"
            for orb in row['orbits']:
                inc_str = f"{orb['inc']:.1f}" if orb['inc'] is not None else '-'
                line += f"{S}{str(orb['orbit']):^{W_ORBIT}}{S}{inc_str:^{W_INC}}"
                if show_sw:
                    line += f"{S}{orb['subswath']:^{W_SW}}"
                if do_count:
                    cnt = orb['count']
                    line += f"{S}{str(cnt) if cnt is not None and cnt >= 0 else '?':>{W_CNT}}"
            print(line)


def print_bbox_info(wkt: str) -> None:
    """Print topsStack/mintpy bbox strings (same format as convert_polygon_string.py)."""
    lon_min, lat_min, lon_max, lat_max = parse_bbox(wkt)

    lat_min_r = round(lat_min, 3)
    lat_max_r = round(lat_max, 3)
    lon_min_r = round(lon_min, 3)
    lon_max_r = round(lon_max, 3)

    lat_min_bbox = round(lat_min_r - _BBOX_LAT_DELTA, 1)
    lat_max_bbox = round(lat_max_r + _BBOX_LAT_DELTA, 1)
    lon_min_bbox = round(lon_min_r - _BBOX_LON_DELTA, 1)
    lon_max_bbox = round(lon_max_r + _BBOX_LON_DELTA, 1)

    subset_str = f"{lat_min_r}:{lat_max_r},{lon_min_r}:{lon_max_r}"

    print(f"\nmintpy.subset.lalo                   = {subset_str}    #[S:N,W:E / no], auto for no")
    print(f"miaplpy.subset.lalo                  = {subset_str}    #[S:N,W:E / no], auto for no\n")


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
    parser.add_argument('--count', '-c', action='store_true', default=False,
                        help='Show acquisition count per orbit (fast API count request)')
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
                        help='Start date for acquisition counts when --count (default: 2014-10-01). Only used with --count.')
    parser.add_argument('--endDate', default=None, metavar='YYYY-MM-DD',
                        help='End date for acquisition counts when --count (default: today). Only used with --count.')
    parser.add_argument('--max-discovery', type=int, default=_DISCOVERY_MAX_RESULTS_S1_DEFAULT,
                        metavar='N',
                        help='Max S1 SLC granules fetched for orbit discovery (default: %(default)s). Increase if orbits are missing.')
    parser.add_argument('--verbose', '-v', action='store_true', default=False,
                        help='Print query parameters and URLs')
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

    _vprint(inps.verbose, f"AOI (WKT) : {wkt}")
    _vprint(inps.verbose, f"Discovery date range: {start} to {end}")
    if inps.count:
        _vprint(inps.verbose, f"Count date range: {count_start} to {count_end} (use --startDate/--endDate to override)")
    _vprint(inps.verbose, f"Platforms : {', '.join(sorted(platforms))}\n")

    all_rows = []

    if 'S1' in platforms:
        print("\nQuerying Sentinel-1...")
        _vprint(inps.verbose, "  [Sentinel-1]")
        slc_sample, burst_results = query_sentinel1(
            wkt, start, end, verbose=inps.verbose, max_results_s1=inps.max_discovery
        )
        orbit_sw_map = _build_orbit_metadata_map(burst_results)

        counts = None
        if inps.count:
            orbit_dirs = list(dict.fromkeys([
                (int(orb), _get_direction(p))
                for p in slc_sample
                for orb in [_get_orbit(p)]
                if orb is not None and _get_direction(p)
            ]))
            _vprint(inps.verbose, f"  [Sentinel-1 counts via API]")
            counts = fetch_orbit_counts(
                'Sentinel-1', orbit_dirs, wkt, count_start, count_end,
                verbose=inps.verbose,
            )

        rows = _aggregate(slc_sample, orbit_sw_map, counts, verbose=inps.verbose)
        all_rows.append(('Sentinel-1', rows))

    if 'NISAR' in platforms:
        print("\nQuerying NISAR...")
        _vprint(inps.verbose, "  [NISAR]")
        nisar_sample = query_nisar(
            wkt, _NISAR_DISCOVERY_START, _NISAR_DISCOVERY_END, verbose=inps.verbose
        )

        counts = None
        if inps.count and nisar_sample:
            orbit_dirs = list(dict.fromkeys([
                (int(orb), _get_direction(p))
                for p in nisar_sample
                for orb in [_get_orbit(p)]
                if orb is not None and _get_direction(p)
            ]))
            _vprint(inps.verbose, "  [NISAR counts via API]")
            counts = fetch_orbit_counts(
                'NISAR', orbit_dirs, wkt, count_start, count_end,
                verbose=inps.verbose,
            )

        if not inps.verbose:
            print(f"  {len(nisar_sample)} results (orbit discovery)")
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
            if inps.count and alos_sample:
                orbit_dirs = list(dict.fromkeys([
                    (int(orb), _get_direction(p))
                    for p in alos_sample
                    for orb in [_get_orbit(p)]
                    if orb is not None and _get_direction(p)
                ]))
                _vprint(inps.verbose, f"  [{pol_label} counts via API]")
                counts = fetch_orbit_counts(
                    pol_label, orbit_dirs, wkt, count_start, count_end,
                    verbose=inps.verbose,
                )

            if not inps.verbose and alos_sample:
                print(f"  {len(alos_sample)} results (orbit discovery)")
            rows = _aggregate(alos_sample, None, counts, verbose=inps.verbose)
            all_rows.append((pol_label, rows))

    print()
    print_table(all_rows, inps.count)
    print_bbox_info(wkt)


if __name__ == '__main__':
    main()
