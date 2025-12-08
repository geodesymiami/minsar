#!/usr/bin/env python3
"""
Extract flight direction from HDF5/HDFEOS file.

This script extracts the ORBIT_DIRECTION or flight_direction attribute
from an HDF5/HDFEOS file and returns 'asc' for ascending or 'desc' for descending.

Based on MintPy's info.py approach for reading file attributes.
"""
import os
import sys
import argparse

# import  (remove the directory of script from sys.path)
sys.path.pop(0)
from minsar.src.minsar.helper_functions import get_flight_direction


EXAMPLE = """examples:
    get_flight_direction.py file.he5
    get_flight_direction.py file.h5
    FLIGHT_DIRECTION=$(get_flight_direction.py file.he5)
"""


def create_parser():
    """Create command line parser."""
    synopsis = 'Extract flight direction from HDF5/HDFEOS file'
    epilog = EXAMPLE
    parser = argparse.ArgumentParser(
        description=synopsis,
        epilog=epilog,
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('file', type=str, help='HDF5/HDFEOS file to check (.h5 or .he5)')
    return parser


def main(iargs=None):
    """Main function."""
    # Parse arguments
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    
    # Check file exists
    if not os.path.isfile(inps.file):
        print(f"ERROR: File not found: {inps.file}", file=sys.stderr)
        return 1
    
    try:
        # Get flight direction
        flight_dir = get_flight_direction(inps.file)
        
        if flight_dir is None:
            print(f"ERROR: Could not find ORBIT_DIRECTION or flight_direction in {inps.file}", file=sys.stderr)
            return 1
        
        # Print result (for use in bash scripts)
        print(flight_dir)
        return 0
        
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
