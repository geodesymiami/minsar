#!/usr/bin/env python3
"""
Create download commands from data_files.txt.

Reads paths from data_files.txt (relative to SCRATCHDIR or absolute), prepends
REMOTEHOST_DATA and REMOTE_DIR, and writes grouped wget lines to
download_commands.txt (radar-coded, geocoded .he5, then matching .gpkg).
"""
import argparse
import os
import re

GEOCODE_LALO_STEP_RE = re.compile(
    r'^#\s*geocode-lalo-step\s+(\S+)\s+(\S+)\s*$',
    re.IGNORECASE,
)

SECTION_RADAR = 'radar'
SECTION_GEOCODED = 'geocoded'
SECTION_GPKG = 'gpkg'


def create_parser():
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description='Create download commands from data_files.txt.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    create_data_download_commands.py hvGalapagos/data_files.txt
    create_data_download_commands.py data_files.txt --outfile download_urls.txt
        """
    )

    parser.add_argument('input', help='Path to data_files.txt file')
    parser.add_argument('--outfile', default='download_commands.txt',
                        help='Output file name (default: download_commands.txt)')

    return parser


def cmd_line_parse(iargs=None):
    """Parse command line arguments."""
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    return inps


def is_geocoded_path(rel_path):
    """True for geo_* LOS, vert, or horz products (not radar-coded LOS)."""
    stem = os.path.basename(rel_path).lower()
    if stem.endswith('.gpkg'):
        stem = stem[:-5]
    return stem.startswith('geo_') or 'vert' in stem or 'horz' in stem


def path_section(rel_path):
    """Return radar, geocoded, or gpkg section for one data_files.txt entry."""
    if rel_path.lower().endswith('.gpkg'):
        return SECTION_GPKG
    if is_geocoded_path(rel_path):
        return SECTION_GEOCODED
    return SECTION_RADAR


def format_geocode_posting(geocode_meta):
    """Format horzvert geocode posting for section headers."""
    if not geocode_meta:
        return None
    lat = geocode_meta.get('lat_step')
    lon = geocode_meta.get('lon_step')
    if lat and lon:
        return f'--lalo-step {lat} {lon}'
    if lat:
        return f'--lat-step {lat}'
    return None


def geocoded_section_header(geocode_meta):
    """Section header for geocoded .he5 products."""
    posting = format_geocode_posting(geocode_meta)
    if posting:
        return f'# geocoded ({posting}):'
    return '# geocoded:'


def get_sort_key(rel_path):
    """Sort: desc before asc; geo LOS before vert/horz; stable by path."""
    lower = os.path.basename(rel_path).lower()
    stem = lower[:-5] if lower.endswith('.gpkg') else lower

    if 'vert' in stem:
        group = 4
    elif 'horz' in stem:
        group = 5
    elif stem.startswith('geo_'):
        group = 1 if '_desc_' in stem or stem.startswith('s1_desc') else 3
    elif '_desc_' in stem or stem.startswith('s1_desc'):
        group = 0
    elif '_asc_' in stem or stem.startswith('s1_asc'):
        group = 2
    else:
        group = 6

    return (group, rel_path.lower())


def remove_scratchdir_from_path(path, scratchdir=None):
    scratchdir = os.getenv('SCRATCHDIR')
    if not scratchdir:
        return path
    scratchdir_resolved = os.path.realpath(scratchdir)
    path_resolved = os.path.realpath(path)

    if path_resolved.startswith(scratchdir_resolved):
        return os.path.relpath(path_resolved, scratchdir_resolved)
    return path


def parse_data_files(text):
    """Parse data_files.txt; return geocode metadata and file paths."""
    geocode_meta = {}
    paths = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = GEOCODE_LALO_STEP_RE.match(line)
        if match:
            geocode_meta['lat_step'] = match.group(1)
            geocode_meta['lon_step'] = match.group(2)
            continue
        if line.startswith('#'):
            continue
        paths.append(line)
    return geocode_meta, paths


def build_wget_url(rel_path, remote_host, remote_dir):
    """Build one wget command for a relative data path."""
    protocol = 'https' if 'insarmaps.miami.edu' in rel_path else 'http'
    return f'wget {protocol}://{remote_host}{remote_dir}{rel_path}'


def group_paths_by_section(rel_paths):
    """Split sorted paths into radar, geocoded .he5, and .gpkg lists."""
    grouped = {
        SECTION_RADAR: [],
        SECTION_GEOCODED: [],
        SECTION_GPKG: [],
    }
    for rel_path in rel_paths:
        grouped[path_section(rel_path)].append(rel_path)
    return grouped


def write_download_commands(output_file, grouped, remote_host, remote_dir, geocode_meta):
    """Write grouped wget sections to download_commands.txt."""
    sections = [
        (SECTION_RADAR, '# radar-coded:'),
        (SECTION_GEOCODED, geocoded_section_header(geocode_meta)),
        (SECTION_GPKG, '# same as *.gpkg files:'),
    ]

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('# MinSAR data downloads.\n')
        first = True
        for section_key, header in sections:
            paths = grouped[section_key]
            if not paths:
                continue
            if not first:
                f.write('\n')
            first = False
            f.write(header + '\n')
            for rel_path in paths:
                f.write(build_wget_url(rel_path, remote_host, remote_dir) + '\n')


def main(iargs=None):
    inps = cmd_line_parse(iargs)

    remote_host = os.getenv('REMOTEHOST_DATA')
    remote_dir = os.getenv('REMOTE_DIR', '/data/HDF5EOS/')

    input_path = os.path.abspath(inps.input)
    input_dir = os.path.dirname(input_path)
    output_file = os.path.join(input_dir, inps.outfile)

    with open(input_path, 'r', encoding='utf-8') as f:
        geocode_meta, rel_paths = parse_data_files(f.read())

    rel_paths = [remove_scratchdir_from_path(p) for p in rel_paths]
    rel_paths.sort(key=get_sort_key)
    grouped = group_paths_by_section(rel_paths)

    write_download_commands(
        output_file, grouped, remote_host, remote_dir, geocode_meta,
    )

    print(f'Wrote wget commands to {output_file}')

    return


if __name__ == '__main__':
    exit(main())
