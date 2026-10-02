#!/usr/bin/env python
import argparse
import glob
import sys
import os
import shutil
import h5py
import numpy as np
from pathlib import Path
from mintpy.utils import readfile, writefile
from mintpy.objects import HDFEOS

def find_attribute(obj, key):
    """
    Recursively search for an attribute 'key' in the HDF5 object 'obj'.
    Returns the attribute value if found, or None otherwise.
    """
    if key in obj.attrs:
        return obj.attrs[key]
    for subkey in obj:
        try:
            subobj = obj[subkey]
        except Exception:
            continue
        result = find_attribute(subobj, key)
        if result is not None:
            return result
    return None

def determine_coordinates(file_path):
    """
    Determine coordinate system from the mask dataset attributes.
    Returns 'GEO' if Y_FIRST is in the attribute keys, else 'RADAR'.
    """
    try:
        _, attr = readfile.read(file_path, datasetName='HDFEOS/GRIDS/timeseries/quality/mask')
        if 'Y_FIRST' in attr.keys():
            print("Detected coordinates: GEO")
            return 'GEO'
    except Exception:
        pass
    print("Detected coordinates: RADAR")
    return 'RADAR'

def extract_mask(file_path, coords, out_dir=""):
    data, attr = readfile.read(file_path, datasetName='HDFEOS/GRIDS/timeseries/quality/mask')
    attr['FILE_TYPE'] = 'mask'
    out_file = os.path.join(out_dir, "geo_mask.h5" if coords=="GEO" else "mask.h5")
    writefile.write(data, out_file=out_file, metadata=attr)
    print(f"Extracted mask -> {out_file}")

    return out_file

def extract_avgSpatialCoherence(file_path, coords, out_dir=""):
    data, attr = readfile.read(file_path, datasetName='HDFEOS/GRIDS/timeseries/quality/avgSpatialCoherence')
    attr['FILE_TYPE'] = 'avgSpatialCoherence'
    out_file = os.path.join(out_dir, "geo_avgSpatialCoherence.h5" if coords=="GEO" else "avgSpatialCoherence.h5")
    writefile.write(data, out_file=out_file, metadata=attr)
    print(f"Extracted avgSpatialCoherence -> {out_file}")

    return out_file

def extract_temporalCoherence(file_path, coords, out_dir=""):
    data, attr = readfile.read(file_path, datasetName='HDFEOS/GRIDS/timeseries/quality/temporalCoherence')
    attr['FILE_TYPE'] = 'temporalCoherence'
    out_file = os.path.join(out_dir, "geo_temporalCoherence.h5" if coords=="GEO" else "temporalCoherence.h5")
    writefile.write(data, out_file=out_file, metadata=attr)
    print(f"Extracted temporalCoherence -> {out_file}")

    return out_file

def extract_shadowMask(file_path, coords, out_dir=""):
    data, attr = readfile.read(file_path, datasetName='HDFEOS/GRIDS/timeseries/geometry/shadowMask')
    attr['FILE_TYPE'] = 'shadowMask'
    out_file = os.path.join(out_dir, "geo_shadowMask.h5" if coords=="GEO" else "shadowMask.h5")
    writefile.write(data, out_file=out_file, metadata=attr)
    print(f"Extracted shadowMask -> {out_file}")

    return out_file

def extract_geometry(file_path, coords, out_dir=""):
    group_path = 'HDFEOS/GRIDS/timeseries/geometry'
    slices = ['azimuthAngle', 'height', 'incidenceAngle', 'latitude', 'longitude', 'shadowMask', 'slantRangeDistance']
    geo_data = {}
    geo_attr = {}
    for s in slices:
        dset_path = f"{group_path}/{s}"
        try:
            data, attr = readfile.read(file_path, datasetName=dset_path)
            geo_data[s] = data
            if not geo_attr:
                geo_attr = attr
        except Exception as e:
            print(f"Warning: Could not extract slice '{s}' from {dset_path}: {e}", file=sys.stderr)
    geo_attr['FILE_TYPE'] = 'geometry'
    geo_attr['COORDINATES'] = coords
    out_file = os.path.join(out_dir, "geo_geometryRadar.h5" if coords=="GEO" else "geometryRadar.h5")
    writefile.write(geo_data, out_file=out_file, metadata=geo_attr)
    print(f"Extracted geometry -> {out_file}")

    if coords=="RADAR":
        inputs_dir = os.path.join(out_dir, 'inputs')
        os.makedirs(inputs_dir, exist_ok=True)
        inputs_file = os.path.join(inputs_dir, 'geometryRadar.h5')
        shutil.copy(out_file, inputs_file)
        print(f"Copied geometryRadar.h5 into {inputs_dir}")

    return out_file

def extract_timeseries(file_path, coords, out_dir=""):
    """
    Extract all displacement datasets from HDFEOS/GRIDS/timeseries/observation.
    Uses HDFEOS from mintpy.objects to obtain the date list.
    Each displacement dataset (named as displacement-YYYYMMDD) is read with readfile.read,
    then renamed to timeseries-YYYYMMDD. The sorted date list is forced into the metadata,
    ensuring that the 'date' dataset exists.
    """
    h = HDFEOS(file_path)
    date_list = h.get_date_list()
    if not date_list:
        print("Error: No displacement datasets found.", file=sys.stderr)
        sys.exit(1)
    date_list = sorted(date_list)

    dataset_name_list = []
    for date_str in date_list:
        dataset_name_list.append(f'HDFEOS/GRIDS/timeseries/observation/displacement-{date_str}')

    data, attr  = readfile.read(file_path, datasetName=dataset_name_list)

    attr['FILE_TYPE'] = 'timeseries'
    out_file = os.path.join(out_dir, "geo_timeseries.h5" if coords=="GEO" else "timeseries.h5")

    dates = np.array(date_list, dtype='S8')

    num_date, length, width = data.shape

    with h5py.File(file_path, 'r') as f:
        bperp = f["HDFEOS/GRIDS/timeseries/observation/bperp"][()]

    pbase = bperp
    ds_name_dict = {
        "date"       : [dates.dtype, (num_date,), dates],
        "bperp"      : [np.float32,  (num_date,), pbase],
        "timeseries" : [np.float32,  (num_date, length, width), None],
        }

    box = [0, 0, data.shape[2], data.shape[1]]
    block = [0, num_date, box[1], box[3], box[0], box[2]]
    writefile.layout_hdf5(out_file, ds_name_dict, metadata=attr)
    writefile.write_hdf5_block(out_file, data=data, datasetName= 'timeseries', block=block)
    print(f"Extracted timeseries (displacement) -> {out_file}")

    return out_file

def extract_velocity(file_path, coords, out_dir="", start_date=None, end_date=None):
    """
    Estimate LOS velocity from displacement time-series via MintPy timeseries2velocity
    (default timeFunc: polynomial=1, same as timeseries2velocity.py with no template).
    """
    out_file = os.path.join(out_dir, "geo_velocity.h5" if coords == "GEO" else "velocity.h5")
    iargs = [file_path, "-o", out_file]
    if start_date:
        iargs.extend(["--start-date", start_date])
    if end_date:
        iargs.extend(["--end-date", end_date])
    print("\ntimeseries2velocity.py", " ".join(iargs))
    import mintpy.cli.timeseries2velocity
    mintpy.cli.timeseries2velocity.main(iargs)
    print(f"Extracted velocity -> {out_file}")
    return out_file

def main():
    parser = argparse.ArgumentParser(
        description="Extract slices from a MintPy HDFEOS file (reverse of save_hdfeos5.py).  "
                    "By default extracts mask, avgSpatialCoherence, temporalCoherence, and geometry. "
                    "Use --all to also extract the displacement (timeseries) datasets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  extract_hdfeos5.py S1_*.he5\n"
               "  extract_hdfeos5.py S1_*.he5 --all --velocity\n"
               "  extract_hdfeos5.py S1_*.he5 --velocity --start-date 20190101 --end-date 20201231",
    )
    parser.add_argument("infile", help="Input S1* HDFEOS file.")
    parser.add_argument("--all", action="store_true",
                        help="Extract all slices including the displacement (timeseries) datasets.")
    parser.add_argument("--velocity", action="store_true",
                        help="Estimate velocity with MintPy timeseries2velocity (default timeFunc options).")
    parser.add_argument("--start-date", dest="start_date", metavar="YYYYMMDD",
                        help="First date for velocity fit (default: first date in file). Requires --velocity.")
    parser.add_argument("--end-date", dest="end_date", metavar="YYYYMMDD",
                        help="Last date for velocity fit (default: last date in file). Requires --velocity.")
    args = parser.parse_args()

    if (args.start_date or args.end_date) and not args.velocity:
        parser.error("--start-date and --end-date require --velocity")

    file_list = glob.glob(args.infile)
    if not file_list:
        print(f"Error: No file found at path {args.infile}.", file=sys.stderr)
        sys.exit(1)
    file_path = file_list[0]

    # Determine output directory from input file path
    # If input is in a subdirectory (e.g., "mintpy/file.he5"), extract to that directory
    # If input is just a filename (e.g., "file.he5"), extract to current directory
    file_dir = os.path.dirname(file_path)
    # Get relative path from current working directory
    if file_dir:
        # Normalize the path to handle "mintpy/" vs "mintpy\file.he5" etc.
        out_dir = os.path.normpath(file_dir)
    else:
        out_dir = ""
    # Create output directory if it doesn't exist
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    coords = determine_coordinates(file_path)
    extract_mask(file_path, coords, out_dir)
    extract_avgSpatialCoherence(file_path, coords, out_dir)
    extract_temporalCoherence(file_path, coords, out_dir)
    extract_geometry(file_path, coords, out_dir)
    extract_shadowMask(file_path, coords, out_dir)

    if args.all:
        extract_timeseries(file_path, coords, out_dir)

    if args.velocity:
        extract_velocity(
            file_path, coords, out_dir,
            start_date=args.start_date, end_date=args.end_date,
        )

if __name__ == "__main__":
    main()
