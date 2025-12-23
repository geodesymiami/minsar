#!/usr/bin/env python3
"""
Calculate appropriate zoom factor from data_footprint attribute in HDFEOS5 files.
Uses the bounding box extent to determine zoom level that fits the data nicely.
"""
import argparse
import h5py
import re
import sys
import math

EXAMPLE = """example:
  get_zoomfactor_from_data_footprint.py file.he5
  get_zoomfactor_from_data_footprint.py file.he5 --min-zoom 8 --max-zoom 15
  get_zoomfactor_from_data_footprint.py file.he5 --default 11.0
"""

DESCRIPTION = (
    "Calculates appropriate zoom factor from data_footprint attribute in HDFEOS5 files.\n"
    "Uses the bounding box extent to determine zoom level that fits the data.\n"
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
        help='Path to HDFEOS5 file (.he5)'
    )
    parser.add_argument(
        '--min-zoom',
        type=float,
        default=8.0,
        help='Minimum zoom level to allow (default: 8.0)'
    )
    parser.add_argument(
        '--max-zoom',
        type=float,
        default=15.0,
        help='Maximum zoom level to allow (default: 15.0)'
    )
    parser.add_argument(
        '--default',
        type=float,
        default=11.0,
        help='Default zoom level to use if data_footprint is not available (default: 11.0)'
    )
    return parser


def calculate_zoom_from_extent(lat_span, lon_span, min_zoom=8.0, max_zoom=15.0):
    """
    Calculate zoom factor from bounding box extent.
    
    Uses the relationship: delta = 301.2 * exp(-0.7075 * zoom_factor)
    Rearranged to: zoom = -ln(span / (2 * 301.2)) / 0.7075
    
    Where span is the maximum of lat_span and lon_span (in degrees).
    
    Parameters:
    -----------
    lat_span : float
        Latitude span in degrees (max_lat - min_lat)
    lon_span : float
        Longitude span in degrees (max_lon - min_lon)
    min_zoom : float
        Minimum allowed zoom level (default: 8.0)
    max_zoom : float
        Maximum allowed zoom level (default: 15.0)
    
    Returns:
    --------
    zoom_factor : float
        Calculated zoom factor, clamped to [min_zoom, max_zoom]
    """
    # Use the larger span to ensure the entire bounding box fits
    max_span = max(lat_span, lon_span)
    
    # Avoid division by zero or negative values
    if max_span <= 0:
        return (min_zoom + max_zoom) / 2.0  # Return middle zoom if span is invalid
    
    # Calculate zoom using inverted formula from url2plot.py
    # delta = 301.2 * exp(-0.7075 * zoom)
    # For a span, we want delta ≈ span/2 (half span on each side from center)
    # So: span/2 = 301.2 * exp(-0.7075 * zoom)
    # Rearranging: zoom = -ln(span / (2 * 301.2)) / 0.7075
    try:
        zoom_factor = -math.log(max_span / (2.0 * 301.2)) / 0.7075
    except (ValueError, ZeroDivisionError):
        # If calculation fails, return default
        return (min_zoom + max_zoom) / 2.0
    
    # Clamp to min/max bounds
    zoom_factor = max(min_zoom, min(zoom_factor, max_zoom))
    
    return zoom_factor


def get_zoom_factor(he5_file, min_zoom=8.0, max_zoom=15.0, default_zoom=11.0):
    """
    Extract zoom factor from data_footprint attribute.
    
    Parameters:
    -----------
    he5_file : str
        Path to HDFEOS5 file
    min_zoom : float
        Minimum allowed zoom level (default: 8.0)
    max_zoom : float
        Maximum allowed zoom level (default: 15.0)
    default_zoom : float
        Default zoom to use if data_footprint is not available (default: 11.0)
    
    Returns:
    --------
    zoom_factor : float
        Calculated zoom factor
    """
    try:
        with h5py.File(he5_file, 'r') as f:
            data_footprint = f.attrs.get('data_footprint', '')
            
            if not data_footprint:
                # Fallback to default if data_footprint not available
                return default_zoom
            
            # Parse POLYGON string: POLYGON((lon lat,lon lat,lon lat,...))
            # Extract coordinates between the inner parentheses
            match = re.search(r'POLYGON\(\((.*?)\)\)', data_footprint)
            if match:
                coords_str = match.group(1)
                # Split by comma to get coordinate pairs
                pairs = coords_str.split(',')
                lats = []
                lons = []
                for pair in pairs:
                    parts = pair.strip().split()
                    if len(parts) >= 2:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        lons.append(lon)
                        lats.append(lat)
                
                if lats and lons:
                    # Calculate bounding box extent
                    lat_span = max(lats) - min(lats)
                    lon_span = max(lons) - min(lons)
                    
                    # Calculate zoom from extent
                    zoom_factor = calculate_zoom_from_extent(lat_span, lon_span, min_zoom, max_zoom)
                    return zoom_factor
                else:
                    # Fallback if parsing failed
                    return default_zoom
            else:
                # Fallback if regex didn't match
                return default_zoom
            
    except Exception as e:
        # Fallback on any error
        return default_zoom


def main(iargs=None):
    """Main function."""
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    
    zoom_factor = get_zoom_factor(
        inps.he5_file,
        min_zoom=inps.min_zoom,
        max_zoom=inps.max_zoom,
        default_zoom=inps.default
    )
    
    # Format to 1 decimal place
    print(f'{zoom_factor:.1f}')
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
