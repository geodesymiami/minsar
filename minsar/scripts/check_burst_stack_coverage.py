#!/usr/bin/env python3
"""Per-date SAFE coverage: required subswaths, burst-count homogeneity, azimuth extras.

Writes under SLC/ (or the SAFE parent directory):

  dates_missing_subswath.txt
  dates_inconsistent_burst_count.txt
  dates_extra_azimuth_bursts.txt

Example:
  check_burst_stack_coverage.py 32.25:32.28,48.92:48.95 SLC
  check_burst_stack_coverage.py 32.25:32.28,48.92:48.95 SLC --required-subswaths 1 2
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

SAFE_DATE_RE = re.compile(r'(\d{8})T\d{6}')
IW_RE = re.compile(r'iw([123])', re.IGNORECASE)

DATES_MISSING_SUBSWATH = 'dates_missing_subswath.txt'
DATES_INCONSISTENT_BURST_COUNT = 'dates_inconsistent_burst_count.txt'
DATES_EXTRA_AZIMUTH_BURSTS = 'dates_extra_azimuth_bursts.txt'

_SCRIPT_DIR = Path(__file__).resolve().parent


def _load_sibling_module(name: str):
    path = _SCRIPT_DIR / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_check_aoi = _load_sibling_module('check_if_bursts_includeAOI')
_check_size = _load_sibling_module('check_file_size')

bbox_sn_we_to_polygon = _check_aoi.bbox_sn_we_to_polygon
footprint_polygon_geotiff = _check_aoi.footprint_polygon_geotiff
_burst_count_from_annotation = _check_size._burst_count_from_annotation


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Check SLC/*.SAFE subswath set, burst counts, and azimuth extras vs AOI.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  check_burst_stack_coverage.py 32.25:32.28,48.92:48.95 SLC\n'
            '  check_burst_stack_coverage.py 32.25:32.28,48.92:48.95 SLC --required-subswaths 1 2'
        ),
    )
    parser.add_argument('bbox', metavar='AOI', help='LAT_S:LAT_N,LON_W:LON_E (S:N,W:E)')
    parser.add_argument('slc_dir', help='Directory containing *.SAFE products')
    parser.add_argument(
        '--required-subswaths',
        type=int,
        nargs='+',
        default=None,
        metavar='N',
        help='Required IW subswath numbers (default: modal set among complete SAFEs)',
    )
    return parser


def _subswaths_in_safe(safe_dir: Path) -> Dict[int, int]:
    """Return {subswath_num: burst_count} from annotation XML burstList counts."""
    counts: Dict[int, int] = {}
    annotation_dir = safe_dir / 'annotation'
    if not annotation_dir.is_dir():
        return counts
    for xml_path in sorted(annotation_dir.glob('*.xml')):
        name = xml_path.name.lower()
        match = IW_RE.search(name)
        if not match:
            continue
        swath = int(match.group(1))
        n = _burst_count_from_annotation(xml_path)
        if n > 0:
            counts[swath] = counts.get(swath, 0) + n
    if counts:
        return counts
    measurement_dir = safe_dir / 'measurement'
    if not measurement_dir.is_dir():
        return counts
    for tiff in sorted(measurement_dir.glob('*.tif*')):
        match = IW_RE.search(tiff.name)
        if match:
            swath = int(match.group(1))
            counts[swath] = counts.get(swath, 0) + 1
    return counts


def _total_bursts(subswath_counts: Dict[int, int]) -> int:
    return sum(subswath_counts.values())


def _extra_azimuth_bursts(safe_dir: Path, aoi) -> int:
    """Count measurement TIFFs whose footprint does not intersect the AOI."""
    measurement_dir = safe_dir / 'measurement'
    if not measurement_dir.is_dir():
        return 0
    extra = 0
    for tiff in sorted(measurement_dir.glob('*.tif*')):
        try:
            fp = footprint_polygon_geotiff(tiff)
            if not fp.intersects(aoi):
                extra += 1
        except Exception:
            continue
    return extra


def _date_from_safe(safe_dir: Path) -> Optional[str]:
    match = SAFE_DATE_RE.search(safe_dir.name)
    return match.group(1) if match else None


def _infer_required_subswaths(records: Sequence[dict]) -> Set[int]:
    complete = [r for r in records if r['subswaths']]
    if not complete:
        return set()
    sets = [frozenset(r['subswaths'].keys()) for r in complete]
    modal = Counter(sets).most_common(1)[0][0]
    return set(modal)


def inspect_slc(slc_dir: Path, aoi, required: Set[int]) -> Tuple[List[dict], int]:
    safes = sorted(p for p in slc_dir.glob('*.SAFE') if p.is_dir())
    records: List[dict] = []
    for safe in safes:
        ymd = _date_from_safe(safe)
        if ymd is None:
            continue
        subswaths = _subswaths_in_safe(safe)
        records.append({
            'date': ymd,
            'path': safe,
            'subswaths': subswaths,
            'n_bursts': _total_bursts(subswaths),
            'extra_azimuth': _extra_azimuth_bursts(safe, aoi),
        })

    if not required:
        required = _infer_required_subswaths(records)

    complete = [r for r in records if r['n_bursts'] > 0]
    expected_bursts = 0
    if complete:
        expected_bursts = Counter(r['n_bursts'] for r in complete).most_common(1)[0][0]

    missing_subswath: List[str] = []
    inconsistent: List[str] = []
    extra_azimuth: List[str] = []

    for r in sorted(records, key=lambda x: x['date']):
        ymd = r['date']
        present = set(r['subswaths'].keys())
        if required:
            missing = sorted(required - present)
            if missing:
                missing_subswath.append(
                    f'{ymd} missing=' + ','.join(f'IW{n}' for n in missing)
                )
        if expected_bursts and r['n_bursts'] != expected_bursts:
            inconsistent.append(f'{ymd} bursts={r["n_bursts"]} expected={expected_bursts}')
        if r['extra_azimuth'] > 0:
            extra_azimuth.append(f'{ymd} extra={r["extra_azimuth"]}')

    out_dir = slc_dir.resolve()
    (out_dir / DATES_MISSING_SUBSWATH).write_text(
        ''.join(line + '\n' for line in missing_subswath), encoding='utf-8'
    )
    (out_dir / DATES_INCONSISTENT_BURST_COUNT).write_text(
        ''.join(line + '\n' for line in inconsistent), encoding='utf-8'
    )
    (out_dir / DATES_EXTRA_AZIMUTH_BURSTS).write_text(
        ''.join(line + '\n' for line in extra_azimuth), encoding='utf-8'
    )

    n_issues = len(missing_subswath) + len(inconsistent) + len(extra_azimuth)
    req_str = ','.join(f'IW{n}' for n in sorted(required)) if required else '(none)'
    print(f'slc: {out_dir}')
    print(f'SAFE directories: {len(records)}')
    print(f'Required subswaths: {req_str}')
    print(f'Expected burst count: {expected_bursts}')
    print(f'Missing subswath: {len(missing_subswath)}')
    print(f'Inconsistent burst count: {len(inconsistent)}')
    print(f'Extra azimuth bursts: {len(extra_azimuth)}')
    if missing_subswath:
        print(f'Wrote {out_dir / DATES_MISSING_SUBSWATH}')
    if inconsistent:
        print(f'Wrote {out_dir / DATES_INCONSISTENT_BURST_COUNT}')
    if extra_azimuth:
        print(f'Wrote {out_dir / DATES_EXTRA_AZIMUTH_BURSTS}')

    return records, n_issues


def main(argv: Optional[List[str]] = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(argv)
    slc_dir = Path(inps.slc_dir)
    if not slc_dir.is_dir():
        print(f'ERROR: not a directory: {slc_dir}', file=sys.stderr)
        return 2
    try:
        aoi = bbox_sn_we_to_polygon(inps.bbox)
    except Exception as exc:
        print(f'ERROR: bbox parse failed ({inps.bbox!r}): {exc}', file=sys.stderr)
        return 2

    required: Set[int] = set(inps.required_subswaths) if inps.required_subswaths else set()
    _records, n_issues = inspect_slc(slc_dir, aoi, required)
    if not _records:
        print('No *.SAFE directories found.', file=sys.stderr)
        return 1
    return 1 if n_issues else 0


if __name__ == '__main__':
    sys.exit(main())
