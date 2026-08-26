#!/usr/bin/env python3


import os
import glob
import tqdm
import shutil
import netCDF4
import argparse
import datetime
import subprocess
import numpy as np
from datetime import date
from shapely import wkt
from mintpy.objects import HDFEOS
from minsar.src.minsar.cli import asf_search_args as asf
from minsar.src.minsar.helper_functions import parse_polygon, convert_to_coord, extract_identification_metadata, normalize_meta_value, merge_metadata, get_output_filename

DESCRIPTION = "Create OPERA timeseries file from pairwise aggregated data."
EXAMPLE = """
Example:
  %(prog)s --dir /path/to/aggregated/files --dem-file /path/to/dem.tif
"""

def create_parser():
    parser = argparse.ArgumentParser(
        description="Create OPERA timeseries file.",
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument('--dir', default=os.path.join(os.getcwd()), help='Output directory')
    parser.add_argument('--dem-file', default=None, help='DEM file to download (optional)')

    inps = parser.parse_args()

    os.makedirs(inps.dir, exist_ok=True)

    if inps.dem_file and not os.path.abspath(inps.dem_file):
        inps.dem_file = os.path.join(os.getcwd(), inps.dem_file)

    return inps

def main():
    inps = create_parser()
    centroid = None

    # DEM section
    if inps.dem_file and not os.path.exists(inps.dem_file):
        region = parse_polygon(inps.intersectsWith)
        subprocess.run([
            "sardem",
            "--bbox", str(region[0]), str(region[2]), str(region[1]), str(region[3]),
            "--output", inps.dem_file,
        ])

    # Processing section
    files = glob.glob(os.path.join(inps.dir, "*.nc"))

    ref_x, ref_y, ref_temporal_coh = None, None, None

    # Initialize dictionary to store by secondary date
    pair_dict = {}
    prev_polygon = None

    for f in tqdm.tqdm(files, desc="Processing files", unit=" file", total=len(files)):
        nc = netCDF4.Dataset(f, 'r')
        x = np.asarray(nc.variables["x"][:], dtype=float)
        y = np.asarray(nc.variables["y"][:], dtype=float)
        temporal_coh = np.asarray(nc.variables["temporal_coherence"][:], dtype=np.float32)
        mask = nc.variables['recommended_mask'][:]

        # Set reference shapes on first valid file
        if ref_x is None:
            ref_x, ref_y, ref_temporal_coh = x.shape, y.shape, temporal_coh.shape

        # Check shapes
        if x.shape != ref_x or y.shape != ref_y or temporal_coh.shape != ref_temporal_coh:
            print(f"Skipping {f}: shape mismatch.")
            nc.close()
            try:
                os.remove(f)
                print(f"Removed {f} due to shape mismatch.")
            except Exception as e:
                print(f"Could not remove {f}: {e}")
            continue

        displacement = nc.variables["displacement"][:] * 100
        displacement_data = displacement.filled(np.nan) if hasattr(displacement, "filled") else np.asarray(displacement)
        ref_time = nc.variables["reference_time"][:]
        sec_time = nc.variables["time"]
        ref_date = netCDF4.num2date(ref_time[:], units=sec_time.units, calendar=getattr(sec_time, "calendar", "standard"), only_use_cftime_datetimes=False)[0].date()
        sec_date = netCDF4.num2date(sec_time[:], units=sec_time.units, calendar=getattr(sec_time, "calendar", "standard"), only_use_cftime_datetimes=False)[0].date()
        meta = extract_identification_metadata(nc)

        if 'bounding_polygon' in meta:
            if prev_polygon and meta['bounding_polygon'] != prev_polygon:
                mismatch_folder = os.path.join(inps.dir, "mismatched_polygons")
                os.makedirs(mismatch_folder, exist_ok=True)
                shutil.move(f, mismatch_folder)
                continue
            prev_polygon = meta['bounding_polygon']

        ref = np.nanmean(displacement_data[0:10,0:10])
        pair_dict[sec_date] = {
            'ref_date': ref_date,
            'displacement': displacement_data - ref,
            'mask': mask,
            'temporal_coherence': temporal_coh,
            'meta': meta
        }

        if not centroid:
            wkt_str = meta.get('bounding_polygon', meta.get('data_footprint', ''))
            geom = wkt.loads(wkt_str)
            centroid = geom.centroid
        nc.close()

    # Sort by secondary date
    pair_dict = {k: pair_dict[k] for k in sorted(pair_dict)}
    date_list = [d.strftime("%Y%m%d") for d in pair_dict]

    time = list(pair_dict.keys())
    X = np.stack([pair_dict[d]['displacement'] for d in pair_dict], axis=0)

    meta = merge_metadata([pair_dict[d]['meta'] for d in pair_dict.keys()])

    if 'reference_datetime' not in meta:
        meta['reference_datetime'] = pair_dict[datetime.datetime.strptime(date_list[0], '%Y%m%d').date()]['ref_date'].strftime("%Y-%m-%d")
    if 'last_date' not in meta:
        meta['last_date'] = date_list[-1]
    meta.pop('source_data_file_list', None)
    if 'PROJECT_NAME' not in meta:
        meta['PROJECT_NAME'] = 'OPERA'

    longitude, latitude = convert_to_coord(x, y, (centroid.x, centroid.y))

    out_file = get_output_filename(meta)

    # Format date_list as YYYYMMDD strings for MintPy compatibility
    date_list = [d.strftime("%Y%m%d") if hasattr(d, 'strftime') else str(d).replace('-', '') for d in time]

    mask_2d = np.multiply.reduce([pair_dict[d]['mask'] for d in pair_dict.keys()])
    temporal_2d = np.nanmean(np.stack([pair_dict[d]['temporal_coherence'] for d in pair_dict.keys()], axis=0), axis=0)

    with netCDF4.Dataset(os.path.join(inps.dir, out_file), "w", format="NETCDF4") as f:
        f.createDimension("time", len(date_list))
        f.createDimension("y", X.shape[1])
        f.createDimension("x", X.shape[2])

        hdfeos_group = f.createGroup("HDFEOS")
        grids_group = hdfeos_group.createGroup("GRIDS")
        ts_group = grids_group.createGroup("timeseries")
        obs_group = ts_group.createGroup("observation")
        qual_group = ts_group.createGroup("quality")
        geom_group = ts_group.createGroup("geometry")

        disp_var = obs_group.createVariable("displacement", "f4", ("time", "y", "x"), zlib=True, complevel=4)
        disp_var[:] = X.astype(np.float32)

        date_var = obs_group.createVariable("date", str, ("time",))
        date_var[:] = np.asarray(date_list, dtype=object)

        # Also write a top-level dataset 'date_list' for compatibility
        date_list_var = f.createVariable("date_list", str, ("time",))
        date_list_var[:] = np.asarray(date_list, dtype=object)

        bperp_var = obs_group.createVariable("bperp", "f4", ("time",))
        bperp_var[:] = np.zeros((len(date_list),), dtype=np.float32)

        tcoh_var = qual_group.createVariable("averageTemporalCoherence", "f4", ("y", "x"), zlib=True, complevel=4)
        tcoh_var[:] = temporal_2d.astype(np.float32)

        mask_var = qual_group.createVariable("mask", "i1", ("y", "x"), zlib=True, complevel=4)
        mask_var[:] = mask_2d.astype(np.int8)


        # Write latitude and longitude grids instead of x and y
        lat_var = geom_group.createVariable("latitude", "f4", ("y", "x"))
        lat_var[:, :] = latitude.astype(np.float32)

        lon_var = geom_group.createVariable("longitude", "f4", ("y", "x"))
        lon_var[:, :] = longitude.astype(np.float32)

        f.FILE_TYPE = "HDFEOS"
        f.LENGTH = str(X.shape[1])
        f.WIDTH = str(X.shape[2])

        # Add meta attributes if available
        if meta is not None:
            meta_attrs = meta if isinstance(meta, dict) else vars(meta)
            for key, value in meta_attrs.items():
                if value is None:
                    continue
                norm_val = normalize_meta_value(value)
                setattr(f, key, str(norm_val) if isinstance(norm_val, (list, tuple, dict, np.ndarray)) else norm_val)

if __name__ == '__main__':
    main()