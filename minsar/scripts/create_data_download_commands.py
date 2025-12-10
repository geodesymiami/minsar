#!/usr/bin/env python3
"""
Create download commands from data_files.txt.

This script reads paths from data_files.txt (which contains paths relative to SCRATCHDIR),
prepends the remote URL using REMOTEHOST_DATA and REMOTE_DIR, and writes them to download_commands.txt.
"""
import os
import sys
import argparse
from pathlib import Path

from minsar.objects import message_rsmas


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


def get_sort_key(url):
    """Get sort key for URL based on desc, asc, vert, horz priority."""
    url_lower = url.lower()

    # Priority: desc (0), asc (1), vert (2), horz (3), others (4)
    if 'desc' in url_lower:
        return (0, url_lower)
    elif 'asc' in url_lower:
        return (1, url_lower)
    elif 'vert' in url_lower:
        return (2, url_lower)
    elif 'horz' in url_lower:
        return (3, url_lower)
    else:
        return (4, url_lower)


def main(iargs=None):
    inps = cmd_line_parse(iargs)

    if iargs is not None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTE_DIR = os.getenv('REMOTE_DIR', '/data/HDF5EOS/')

    input_path = os.path.abspath(inps.input)

    # Determine output file location (same directory as input file)
    input_dir = os.path.dirname(input_path)
    output_file = os.path.join(input_dir, inps.outfile)

    # Read data_files.txt and create URLs
    download_urls = []
    with open(input_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:  # Skip empty lines
                url = f"wget http://{REMOTEHOST_DATA}{REMOTE_DIR}{line}"
                download_urls.append(url)

    if not download_urls:
        print(f"Warning: No valid paths found in {input_path}")
        return 0

    # Sort URLs: desc, asc, vert, horz, then others
    download_urls.sort(key=get_sort_key)

    # Write download commands to output file
    with open(output_file, 'w') as f:
        for url in download_urls:
            f.write(url + '\n')

    print(f"Wrote wget commands to {output_file}")

    return


if __name__ == '__main__':
    exit(main())
