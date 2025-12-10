#!/usr/bin/env python3
"""
Create URLs for HTML files and write them to frames_urls.log.

This script finds HTML files in a directory or from a glob pattern,
creates URLs using REMOTEHOST_DATA and REMOTE_DIR environment variables,
and writes them to frames_urls.log in the output directory.
"""
import os
import sys
import glob
import argparse
from pathlib import Path

from minsar.objects import message_rsmas


def create_parser():
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description='Create URLs for HTML files and write them to frames_urls.log.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    write_insarmaps_framepage_urls.py hvGalapagos
    write_insarmaps_framepage_urls.py hvGalapagos/*html
    write_insarmaps_framepage_urls.py hvGalapagos/*html --outdir hvGalapagos
    cd hvGalapagos; write_insarmaps_framepage_urls.py *html
        """
    )

    parser.add_argument('input', nargs='?', default=None,
                       help='Directory name or glob pattern for HTML files (default: *.html in current directory)')
    parser.add_argument('--outdir', default=None,
                       help='Output directory for frames_urls.log (default: directory containing HTML files)')

    return parser

def cmd_line_parse(iargs=None):
    """Parse command line arguments."""
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    return inps

def find_html_files(input_path, cwd):
    """Find HTML files based on input path or pattern."""
    html_files = []

    if input_path is None:
        # No input: look for *.html in current directory
        html_files = glob.glob(os.path.join(cwd, '*.html'))
    else:
        # Check if input is a directory
        if os.path.isdir(input_path):
            # Input is a directory: find all *.html files in it
            html_files = glob.glob(os.path.join(input_path, '*.html'))
        elif os.path.isfile(input_path):
            # Input is a single file
            if input_path.endswith('.html'):
                html_files = [input_path]
            else:
                print(f"Warning: File '{input_path}' does not have .html extension")
        else:
            # Input might be a glob pattern or doesn't exist yet
            # Try to expand it as a glob pattern
            if not os.path.isabs(input_path):
                # Relative path: try from current directory
                pattern = os.path.join(cwd, input_path)
            else:
                pattern = input_path

            html_files = glob.glob(pattern)

            # If no files found and it looks like a directory name (no extension, no wildcards)
            if not html_files and '*' not in input_path and '.' not in os.path.basename(input_path):
                # Treat as directory name
                if not os.path.isabs(input_path):
                    dir_path = os.path.join(cwd, input_path)
                else:
                    dir_path = input_path
                html_files = glob.glob(os.path.join(dir_path, '*.html'))

    # Convert to absolute paths and sort
    html_files = [os.path.abspath(f) for f in html_files]
    html_files.sort()

    return html_files

def determine_output_dir(html_files, input_path, cwd, outdir_arg):
    """Determine output directory for frames_urls.log."""
    if outdir_arg:
        return os.path.abspath(outdir_arg)

    if not html_files:
        if input_path and os.path.isdir(input_path):
            return os.path.abspath(input_path)
        return cwd

    return os.path.dirname(html_files[0])


def create_urls(html_files, project_dir):
    """Create URLs for HTML files.
    """
    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTE_DIR = '/data/HDF5EOS/'

    if not REMOTEHOST_DATA:
        raise ValueError("REMOTEHOST_DATA environment variable is not set")

    frame_urls = []
    project_dir_abs = os.path.abspath(project_dir)
    project_name = os.path.basename(project_dir_abs)

    for html_file in html_files:
        html_file_abs = os.path.abspath(html_file)

        # Get relative path from project_dir to html_file
        try:
            rel_path = os.path.relpath(html_file_abs, project_dir_abs)
        except ValueError:
            # Paths on different drives (Windows) or can't compute relative path
            # Use filename only
            rel_path = os.path.basename(html_file)

        # Construct URL: http://REMOTEHOST_DATA/REMOTE_DIR/project_name/rel_path
        url = f"http://{REMOTEHOST_DATA}{REMOTE_DIR}{project_name}/{rel_path}"

        frame_urls.append(url)

    return frame_urls


def main(iargs=None):
    """Main function."""
    inps = cmd_line_parse(iargs)

    if iargs is not None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    cwd = os.getcwd()
    html_files = find_html_files(inps.input, cwd)

    out_dir = inps.outdir if inps.outdir else cwd
    out_dir = os.path.abspath(out_dir)
    output_file = os.path.join(out_dir, 'frames_urls.log')
    if os.path.exists(output_file):
        os.remove(output_file)
    project_dir = os.path.dirname(html_files[0])

    frame_urls = create_urls(html_files, project_dir)

    # write URLs
    with open(output_file, 'w') as f:
        for url in frame_urls:
            f.write(url + '\n')

    print(f"Wrote URL(s) to {output_file}")

    return 0

if __name__ == '__main__':
    exit(main())
