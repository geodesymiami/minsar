#!/usr/bin/env python3
"""
Copy data_footprint attribute from a reference .he5 file to target .he5 files.
This ensures all files have the same footprint for consistent map display.
"""
import argparse
import h5py
import sys
import os
import glob

def get_he5_file(path):
    """If path is a directory, find the newest .he5 file in it. Otherwise return path."""
    if os.path.isdir(path):
        he5_files = sorted(glob.glob(os.path.join(path, '*.he5')), key=os.path.getmtime, reverse=True)
        if he5_files:
            print(f"Found .he5 file in directory {path}: {he5_files[0]}")
            return he5_files[0]
        else:
            print(f"Warning: No .he5 files found in directory {path}")
            return None
    return path

def copy_footprint(source_file, target_files):
    """Copy data_footprint from source to target files."""
    
    # Resolve source file (handle directories)
    source_file = get_he5_file(source_file)
    if source_file is None:
        return False
    
    # Read footprint from source
    try:
        with h5py.File(source_file, 'r') as f:
            footprint = f.attrs.get('data_footprint', None)
            if footprint is None:
                print(f"Warning: No data_footprint found in {source_file}")
                return False
            if isinstance(footprint, bytes):
                footprint = footprint.decode('utf-8')
            print(f"Source footprint from {source_file}: {footprint}")
    except Exception as e:
        print(f"Error reading {source_file}: {e}", file=sys.stderr)
        return False
    
    # Copy to each target file
    success = True
    for target_path in target_files:
        # Resolve target file (handle directories)
        target_file = get_he5_file(target_path)
        if target_file is None:
            success = False
            continue
            
        try:
            with h5py.File(target_file, 'r+') as f:
                if 'data_footprint' in f.attrs:
                    del f.attrs['data_footprint']
                f.attrs['data_footprint'] = footprint
                print(f"✓ Updated data_footprint in {target_file}")
        except Exception as e:
            print(f"Error updating {target_file}: {e}", file=sys.stderr)
            success = False
    
    return success


def main():
    parser = argparse.ArgumentParser(
        description='Copy data_footprint attribute from source to target .he5 files'
    )
    parser.add_argument('source', help='Source .he5 file (reference)')
    parser.add_argument('targets', nargs='+', help='Target .he5 file(s) to update')
    
    args = parser.parse_args()
    
    success = copy_footprint(args.source, args.targets)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

