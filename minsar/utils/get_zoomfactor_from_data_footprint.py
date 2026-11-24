#!/usr/bin/env python3
"""
Calculate appropriate zoom factor from data_footprint attribute in HDFEOS5 files.
Uses the bounding box extent to determine the zoom level at which the data cover
about 112% of a typical browser window (slightly overfill it).

For .csv inputs, extent is taken from min/max of latitude and longitude columns
(same column detection as insarmaps_ingester.py).
"""
import argparse
import h5py
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_INSARMAPS_UTILS = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "insarmaps_utils"))
if _INSARMAPS_UTILS not in sys.path:
    sys.path.insert(0, _INSARMAPS_UTILS)
from insarmaps_csv_geo import (
    DEFAULT_ZOOM,
    MAX_ZOOM,
    MIN_ZOOM,
    VIEWPORT_FILL,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    csv_lat_lon_bounds,
    wkt_polygon_bounds,
    zoom_for_bounds,
)

EXAMPLE = """Examples:
  get_zoomfactor_from_data_footprint.py file.he5
  get_zoomfactor_from_data_footprint.py file.he5 --min-zoom 8 --max-zoom 15
  get_zoomfactor_from_data_footprint.py file.he5 --viewport-fill 0.9
  get_zoomfactor_from_data_footprint.py file.he5 --viewport-size 1148 802
  get_zoomfactor_from_data_footprint.py file.he5 --default 11.0
  get_zoomfactor_from_data_footprint.py timeseries.csv
"""

DESCRIPTION = (
    "Calculates the insarmaps zoom from data_footprint in HDFEOS5 files, or from the lat/lon extent in CSV.\n"
    "The zoom is chosen such that the data bounding box covers --viewport-fill (default 1.125) of the map\n"
    "view of a typical browser window (open_insarmaps.py --bounds 304 55 1452 947), along the limiting\n"
    "dimension, using the Web Mercator / Mapbox GL scale (world = 512 * 2^zoom px).\n"
    "Outputs a single zoom factor value."
)


def create_parser():
    """Creates command line argument parser object."""
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE
    )
    parser.add_argument(
        'he5_file',
        help='Path to HDFEOS5 file (.he5) or Insarmaps CSV (.csv)'
    )
    parser.add_argument(
        '--min-zoom',
        type=float,
        default=MIN_ZOOM,
        help=f'Minimum zoom level to allow (default: {MIN_ZOOM})'
    )
    parser.add_argument(
        '--max-zoom',
        type=float,
        default=MAX_ZOOM,
        help=f'Maximum zoom level to allow (default: {MAX_ZOOM})'
    )
    parser.add_argument(
        '--default',
        type=float,
        default=DEFAULT_ZOOM,
        help=f'Default zoom level to use if data_footprint is not available (default: {DEFAULT_ZOOM})'
    )
    parser.add_argument(
        '--viewport-fill',
        type=float,
        default=VIEWPORT_FILL,
        metavar='FRACTION',
        help=f'Fraction of the map view the data should cover; larger zooms in (default: {VIEWPORT_FILL}).'
    )
    parser.add_argument(
        '--viewport-size',
        type=float,
        nargs=2,
        default=[VIEWPORT_WIDTH, VIEWPORT_HEIGHT],
        metavar=('WIDTH', 'HEIGHT'),
        help=f'Map view size in pixels (default: {VIEWPORT_WIDTH} {VIEWPORT_HEIGHT}).'
    )
    return parser


def get_zoom_factor(
    he5_file, min_zoom=MIN_ZOOM, max_zoom=MAX_ZOOM, default_zoom=DEFAULT_ZOOM,
    viewport_fill=VIEWPORT_FILL, viewport_size=(VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
):
    """
    Zoom factor from data_footprint (.he5) or lat/lon extent (.csv).

    Returns default_zoom if the extent is not available.
    """
    path_str = str(he5_file)
    try:
        if path_str.lower().endswith(".csv"):
            bounds = csv_lat_lon_bounds(path_str)
        else:
            with h5py.File(he5_file, 'r') as f:
                data_footprint = f.attrs.get('data_footprint', '')
            if isinstance(data_footprint, bytes):
                data_footprint = data_footprint.decode()
            bounds = wkt_polygon_bounds(data_footprint)
    except Exception:
        return default_zoom

    if bounds is None or (bounds[0] == bounds[1] and bounds[2] == bounds[3]):
        return default_zoom
    return zoom_for_bounds(
        *bounds, viewport_fill=viewport_fill, width=viewport_size[0], height=viewport_size[1],
        min_zoom=min_zoom, max_zoom=max_zoom,
    )


def main(iargs=None):
    """Main function."""
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    
    if inps.viewport_fill <= 0:
        parser.error('--viewport-fill must be positive')
    if min(inps.viewport_size) <= 0:
        parser.error('--viewport-size must be positive')

    zoom_factor = get_zoom_factor(
        inps.he5_file,
        min_zoom=inps.min_zoom,
        max_zoom=inps.max_zoom,
        default_zoom=inps.default,
        viewport_fill=inps.viewport_fill,
        viewport_size=inps.viewport_size,
    )
    
    # Format to 1 decimal place
    print(f'{zoom_factor:.1f}')
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
