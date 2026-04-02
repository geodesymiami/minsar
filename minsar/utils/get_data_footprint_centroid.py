#!/usr/bin/env python3
"""
Extract center coordinates from data_footprint attribute in HDFEOS5 files.
Falls back to REF_LAT/REF_LON if data_footprint is not available.

For .csv inputs (SARvey/Insarmaps CSV), uses the mean of latitude and longitude
columns (same column detection as hdfeos5_or_csv_2json_mbtiles.py).
"""
import argparse
import h5py
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_INSARMAPS_UTILS = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "insarmaps_utils"))
if _INSARMAPS_UTILS not in sys.path:
    sys.path.insert(0, _INSARMAPS_UTILS)
from insarmaps_csv_geo import csv_mean_lat_lon

EXAMPLE = """example:
  get_data_foot_centroid.py file.he5
  get_data_foot_centroid.py file.he5 --decimals 6
  get_data_foot_centroid.py timeseries.csv
"""

DESCRIPTION = (
    "Extracts center coordinates (lat, lon) from data_footprint in HDFEOS5 files,\n"
    "or mean lat/lon from CSV (Latitude/Longitude or Y/X, etc.).\n"
    "Outputs space-separated values: CENTER_LAT CENTER_LON"
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
        '--decimals',
        type=int,
        default=4,
        help='Number of decimal places for output (default: 4)'
    )
    return parser


def get_center_coords(he5_file, decimals=4):
    """
    Extract center coordinates from data_footprint attribute (.he5) or mean lat/lon (.csv).
    
    Parameters:
    -----------
    he5_file : str
        Path to HDFEOS5 file or CSV
    decimals : int
        Number of decimal places for output (default: 4)
    
    Returns:
    --------
    center_lat : float
        Center latitude (formatted to specified decimals)
    center_lon : float
        Center longitude (formatted to specified decimals)
    """
    path_str = str(he5_file)
    if path_str.lower().endswith(".csv"):
        try:
            center_lat, center_lon = csv_mean_lat_lon(path_str)
            format_str = f"{{:.{decimals}f}}"
            return format_str.format(center_lat), format_str.format(center_lon)
        except Exception:
            format_str = f"{{:.{decimals}f}}"
            return format_str.format(0.0), format_str.format(0.0)

    try:
        with h5py.File(he5_file, 'r') as f:
            data_footprint = f.attrs.get('data_footprint', '')
            
            if not data_footprint:
                # Fallback to REF_LAT/REF_LON if data_footprint not available
                ref_lat = float(f.attrs.get('REF_LAT', 0.0))
                ref_lon = float(f.attrs.get('REF_LON', 0.0))
                center_lat = ref_lat
                center_lon = ref_lon
            else:
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
                        # Calculate center as midpoint of min/max
                        center_lat = (min(lats) + max(lats)) / 2.0
                        center_lon = (min(lons) + max(lons)) / 2.0
                    else:
                        # Fallback if parsing failed
                        ref_lat = float(f.attrs.get('REF_LAT', 0.0))
                        ref_lon = float(f.attrs.get('REF_LON', 0.0))
                        center_lat = ref_lat
                        center_lon = ref_lon
                else:
                    # Fallback if regex didn't match
                    ref_lat = float(f.attrs.get('REF_LAT', 0.0))
                    ref_lon = float(f.attrs.get('REF_LON', 0.0))
                    center_lat = ref_lat
                    center_lon = ref_lon
            
            # Format to specified decimal places
            format_str = f'{{:.{decimals}f}}'
            center_lat_formatted = format_str.format(center_lat)
            center_lon_formatted = format_str.format(center_lon)
            
            return center_lat_formatted, center_lon_formatted
            
    except Exception as e:
        # Fallback on any error
        try:
            with h5py.File(he5_file, 'r') as f:
                ref_lat = float(f.attrs.get('REF_LAT', 0.0))
                ref_lon = float(f.attrs.get('REF_LON', 0.0))
                format_str = f'{{:.{decimals}f}}'
                center_lat_formatted = format_str.format(ref_lat)
                center_lon_formatted = format_str.format(ref_lon)
                return center_lat_formatted, center_lon_formatted
        except:
            format_str = f'{{:.{decimals}f}}'
            return format_str.format(0.0), format_str.format(0.0)


def main(iargs=None):
    """Main function."""
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    
    center_lat, center_lon = get_center_coords(inps.he5_file, inps.decimals)
    print(f'{center_lat} {center_lon}')
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
