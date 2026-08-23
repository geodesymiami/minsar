#!/usr/bin/env python3
"""Compare burst counts and sizes of SLC/*.SAFE or secondarys/<date> directories."""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SAFE_DATE_RE = re.compile(r'(\d{8})T\d{6}')
DATE_DIR_RE = re.compile(r'^\d{8}$')
BURSTLIST_RE = re.compile(r'<burstList\s+count="(\d+)"', re.IGNORECASE)
BURST_STEM_RE = re.compile(r'^(burst_\d+)', re.IGNORECASE)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Check that SLC/*.SAFE or secondarys/<date> dirs have the same burst count.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n  check_file_size.py SLC\n  check_file_size.py secondarys',
    )
    parser.add_argument('data_dir', help='SLC (*.SAFE) or secondarys (date directories)')
    return parser


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _format_size(n_bytes: int) -> str:
    if n_bytes >= 1024 ** 3:
        return f'{n_bytes / 1024 ** 3:.1f}G'
    if n_bytes >= 1024 ** 2:
        return f'{n_bytes / 1024 ** 2:.0f}M'
    if n_bytes >= 1024:
        return f'{n_bytes / 1024:.0f}K'
    return f'{n_bytes}B'


def _median_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _burst_count_from_annotation(xml_path: Path) -> int:
    try:
        text = xml_path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return 0
    match = BURSTLIST_RE.search(text)
    if match:
        return int(match.group(1))
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return 0
    return sum(1 for el in root.iter() if el.tag.split('}')[-1] == 'burst')


def _date_from_safe_name(name: str) -> str:
    match = SAFE_DATE_RE.search(name)
    return match.group(1) if match else '-'


def detect_mode(data_dir: Path) -> str:
    """Return 'safe' or 'secondarys' from directory name or contents."""
    name = data_dir.name.lower()
    if name == 'slc' or any(p.is_dir() for p in data_dir.glob('*.SAFE')):
        return 'safe'
    if name in ('secondarys', 'secondary'):
        return 'secondarys'
    if any(p.is_dir() and DATE_DIR_RE.match(p.name) for p in data_dir.iterdir()):
        return 'secondarys'
    raise SystemExit(f'ERROR: {data_dir} has no *.SAFE and no YYYYMMDD directories')


def list_targets(data_dir: Path, mode: str) -> list[Path]:
    if mode == 'safe':
        return sorted(p for p in data_dir.glob('*.SAFE') if p.is_dir())
    return sorted(p for p in data_dir.iterdir() if p.is_dir() and DATE_DIR_RE.match(p.name))


def inspect_safe(safe_dir: Path) -> dict:
    annotation_dir = safe_dir / 'annotation'
    measurement_dir = safe_dir / 'measurement'
    tiffs = sorted(measurement_dir.glob('*.tiff')) + sorted(measurement_dir.glob('*.tif'))
    xmls = [p for p in annotation_dir.glob('*.xml') if p.is_file()] if annotation_dir.is_dir() else []
    n_bursts = sum(_burst_count_from_annotation(p) for p in xmls)
    n_products = len(tiffs)
    return {
        'path': safe_dir,
        'name': safe_dir.name,
        'date': _date_from_safe_name(safe_dir.name),
        'n_bytes': _dir_size_bytes(safe_dir),
        'n_products': n_products,
        'n_bursts': n_bursts,
        'empty_reason': 'no measurement TIFF' if n_products == 0 else None,
    }


def inspect_secondary(date_dir: Path) -> dict:
    burst_ids: set[tuple[str, str]] = set()
    for path in date_dir.glob('IW*/burst_*'):
        match = BURST_STEM_RE.match(path.name)
        if match:
            burst_ids.add((path.parent.name, match.group(1)))
    n_bursts = len(burst_ids)
    return {
        'path': date_dir,
        'name': date_dir.name,
        'date': date_dir.name,
        'n_bytes': _dir_size_bytes(date_dir),
        'n_products': n_bursts,
        'n_bursts': n_bursts,
        'empty_reason': 'no burst SLC' if n_bursts == 0 else None,
    }


def main(iargs=None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    data_dir = Path(inps.data_dir)
    if not data_dir.is_dir():
        print(f'ERROR: Not a directory: {data_dir}', file=sys.stderr)
        return 1

    mode = detect_mode(data_dir)
    targets = list_targets(data_dir, mode)
    kind = 'SAFE' if mode == 'safe' else 'date'
    if not targets:
        print(f'No {kind} directories in {data_dir}')
        return 1

    inspect = inspect_safe if mode == 'safe' else inspect_secondary
    records = [inspect(p) for p in targets]
    burst_counts = Counter(r['n_bursts'] for r in records)
    complete = [r for r in records if r['n_bursts'] > 0 and r['n_products'] > 0]
    if complete:
        expected_bursts = Counter(r['n_bursts'] for r in complete).most_common(1)[0][0]
        expected_size = _median_int([r['n_bytes'] for r in complete if r['n_bursts'] == expected_bursts])
    else:
        expected_bursts = 0
        expected_size = 0

    missing = [
        r for r in records
        if r['n_bursts'] < expected_bursts or r['n_products'] == 0 or r['n_bursts'] == 0
    ]
    extra = [r for r in records if r['n_bursts'] > expected_bursts]
    ok = [r for r in records if r not in missing and r not in extra]

    print(f'{mode}: {data_dir.resolve()}')
    print(f'{kind} directories: {len(records)}')
    print(f'Expected bursts: {expected_bursts} (most common among complete dirs)')
    if expected_size:
        print(f'Expected size: ~{_format_size(expected_size)} (median of expected-burst dirs)')
    print('Burst counts:')
    for n_bursts, n_dirs in sorted(burst_counts.items()):
        print(f'  {n_bursts} burst(s): {n_dirs}')
    print(f'OK: {len(ok)}')
    print(f'Missing bursts: {len(missing)}')
    if extra:
        print(f'More bursts than expected: {len(extra)}')

    if missing:
        print()
        print('Files missing bursts:')
        for r in sorted(missing, key=lambda x: (x['date'], x['name'])):
            reason = r['empty_reason'] or f"bursts={r['n_bursts']} < {expected_bursts}"
            print(
                f"  {r['date']}  {_format_size(r['n_bytes']):>5}  bursts={r['n_bursts']}  "
                f"{r['name']}  ({reason})"
            )

    if extra:
        print()
        print('Files with extra bursts:')
        for r in sorted(extra, key=lambda x: (x['date'], x['name'])):
            print(f"  {r['date']}  {_format_size(r['n_bytes']):>5}  bursts={r['n_bursts']}  {r['name']}")

    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
