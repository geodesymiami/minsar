#!/usr/bin/env python3
# Author: Sara Mirzaee

import os
import numpy as np
import argparse
import h5py
from mintpy.utils import readfile, writefile, utils as ut
import pandas as pd

DESCRIPTION = "Correct for geolocation shift caused by DEM error."

EXAMPLE = """\
Supports:
    - HDF5 input (default)
    - CSV input

CSV mode reads longitude/latitude (or X/Y or xcoord/ycoord) and demError
(or dem_error). With --geometry and --points it samples incidenceAngle and
azimuthAngle onto the CSV. It writes longitude_corrected and latitude_corrected.

NOTE: --reverse only works for HDF5 files.


Examples:
  # Correct a CSV file, output auto-named:
  correct_geolocation.py North_20162023.csv

  # Correct a CSV file, save as specific output:
  correct_geolocation.py North_20162023.csv --outfile North_corrected.csv

  # Correct an HDF5 file:
  correct_geolocation.py -g geometryRadar.h5 -d demErr.h5

  # Reverse geolocation correction in HDF5 file:
  correct_geolocation.py -g geometryRadar.h5 -d demErr.h5 --reverse
"""
def cmd_line_parse(iargs=None):
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter
    )
    #parser = argparse.ArgumentParser(description='Correct for geolocation shift caused by DEM error')
    parser.add_argument('-g', '--geometry', dest='geometry_file', type=str,
                        help='Geometry stack File in radar coordinate, (geometryRadar.h5)')
    parser.add_argument('-d', '--demErr', dest='dem_error_file', type=str, help='DEM error file (demErr.h5)')
    parser.add_argument('--reverse', dest='reverse', action='store_true', help='Reverse geolocation Correction')
    #arguments for csv
    parser.add_argument("input_file", type=str, help="Input CSV or HDF5 file")
    parser.add_argument("--outfile", type=str, help="Output file (for CSV mode only)")
    parser.add_argument("--points", dest="points_file", type=str, default=None, help="Points HDF5 (coord_xy, point_id) sampled with --geometry")

    inps = parser.parse_args(args=iargs)
    return inps


def measure_d(lat1, lat2, lon1, lon2):
    R = 6378137  # in meter
    dLat = lat2 * np.pi / 180 - lat1 * np.pi / 180
    dLon = lon2 * np.pi / 180 - lon1 * np.pi / 180
    a = (np.sin(dLat/2)) ** 2 + (np.cos(lat1 * np.pi / 180)) ** 2 * (np.sin(dLon/2)) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    d = R * c
    return d


def main(iargs=None):
    inps = cmd_line_parse(iargs)

    #for csv input
    if inps.input_file.endswith(".csv"):
        correct_geolocation_csv(
            input_file=inps.input_file,
            output_file=inps.outfile,
            geometry_file=inps.geometry_file,
            points_file=inps.points_file,
        )
        return

    key = 'geolocation_corrected'

    with h5py.File(inps.geometry_file, 'r') as f:
        keys = f.attrs.keys()
        latitude = f['latitude'][:, :]
        longitude = f['longitude'][:, :]

        atr = readfile.read(inps.geometry_file, datasetName='azimuthAngle')[1]

        if not key in keys or atr[key] == 'no':
            status = 'run'
            print('Run geolocation correction ...')
        else:
            status = 'skip'
            print('Geolocation is already done, you may reverse it using --reverse. skip ...')

        if inps.reverse:
            if key in keys and atr[key] == 'yes':
                status = 'run'
                print('Run reversing geolocation correction ...')
            else:
                status = 'skip'
                print('The file is not corrected for geolocation. skip ...')

    if status == 'run':

        az_angle = np.deg2rad(float(atr['HEADING']))
        inc_angle = np.deg2rad(readfile.read(inps.geometry_file, datasetName='incidenceAngle')[0])

        dem_error = readfile.read(inps.dem_error_file, datasetName='dem')[0]

        rad_latitude = np.deg2rad(latitude)

        one_degree_latitude = 111132.92 - 559.82 * np.cos(2*rad_latitude) + \
                              1.175 * np.cos(4 * rad_latitude) - 0.0023 * np.cos(6 * rad_latitude)

        one_degree_longitude = 111412.84 * np.cos(rad_latitude) - \
                               93.5 * np.cos(3 * rad_latitude) + 0.118 * np.cos(5 * rad_latitude)

        print(np.mean(one_degree_latitude), np.mean(one_degree_longitude))

        #one_degree_latitude = measure_d(latitude, latitude+1, 0, 0)
        #one_degree_longitude = measure_d(latitude, latitude, 10, 11)

        #print(np.mean(one_degree_latitude), np.mean(one_degree_longitude))
        
        dx = np.divide((dem_error) * (1 / np.tan(inc_angle)) * np.cos(az_angle), one_degree_longitude)  # converted to degree
        dy = np.divide((dem_error) * (1 / np.tan(inc_angle)) * np.sin(az_angle), one_degree_latitude)  # converted to degree

        if inps.reverse:
            sign = np.sign(latitude)
            latitude -= sign * dy

            sign = np.sign(longitude)
            longitude -= sign * dx

            atr[key] = 'no'
            block = [0, latitude.shape[0], 0, latitude.shape[1]]
            writefile.write_hdf5_block(inps.geometry_file,
                                       data=latitude,
                                       datasetName='latitude',
                                       block=block)

            writefile.write_hdf5_block(inps.geometry_file,
                                       data=longitude,
                                       datasetName='longitude',
                                       block=block)

            ut.add_attribute(inps.geometry_file, atr_new=atr)


        else:
            sign = np.sign(latitude)
            latitude += sign * dy

            sign = np.sign(longitude)
            longitude += sign * dx

            atr[key] = 'yes'
            block = [0, latitude.shape[0], 0, latitude.shape[1]]
            writefile.write_hdf5_block(inps.geometry_file,
                                       data=latitude,
                                       datasetName='latitude',
                                       block=block)
            writefile.write_hdf5_block(inps.geometry_file,
                                       data=longitude,
                                       datasetName='longitude',
                                       block=block)
            ut.add_attribute(inps.geometry_file, atr_new=atr)

    f.close()

    return

def _sample_incidence_azimuth(df, geometry_file, points_file):
    """Add per-point incidenceAngle and azimuthAngle from geometryRadar.h5."""
    if geometry_file is None or points_file is None:
        return df
    if "point_id" not in df.columns:
        raise ValueError("CSV must contain point_id to sample incidenceAngle and azimuthAngle")
    with h5py.File(points_file, "r") as handle:
        coord_xy = handle["coord_xy"][:]
        point_id = handle["point_id"][:]
    with h5py.File(geometry_file, "r") as handle:
        incidence = handle["incidenceAngle"][:]
        azimuth = handle["azimuthAngle"][:]
    rows = coord_xy[:, 0].astype(int)
    cols = coord_xy[:, 1].astype(int)
    angles = pd.DataFrame({
        "point_id": point_id.astype(np.int64),
        "incidenceAngle": incidence[rows, cols],
        "azimuthAngle": azimuth[rows, cols],
    })
    df = df.copy()
    df["point_id"] = pd.to_numeric(df["point_id"], errors="coerce").astype(np.int64)
    df = df.drop(columns=[name for name in ("incidenceAngle", "azimuthAngle") if name in df.columns])
    df = df.merge(angles, on="point_id", how="left")
    df = _place_columns_after(df, ("height", "dem", "demError", "dem_error"), ("incidenceAngle", "azimuthAngle"))
    dem_name = next((name for name in ("demError", "dem_error") if name in df.columns), None)
    if dem_name is not None and "azimuthAngle" in df.columns:
        df = _place_columns_after(df, ("azimuthAngle",), (dem_name,))
    return df


def _place_columns_after(df, after_names, new_names):
    """Move new_names to sit just after the first existing column in after_names."""
    new_names = [name for name in new_names if name in df.columns]
    cols = [name for name in df.columns if name not in new_names]
    insert_at = len(cols)
    for name in after_names:
        if name in cols:
            insert_at = cols.index(name) + 1
            break
    for offset, name in enumerate(new_names):
        cols.insert(insert_at + offset, name)
    return df[cols]


def correct_geolocation_csv(input_file, output_file=None, geometry_file=None, points_file=None):
    df = pd.read_csv(input_file)
    if (geometry_file is None) ^ (points_file is None):
        raise ValueError("Pass both --geometry and --points to sample incidenceAngle and azimuthAngle")
    df = _sample_incidence_azimuth(df, geometry_file, points_file)

    if "xcoord" in df.columns and "ycoord" in df.columns:
        xcol, ycol = "xcoord", "ycoord"
    elif "longitude" in df.columns and "latitude" in df.columns:
        xcol, ycol = "longitude", "latitude"
    elif "X" in df.columns and "Y" in df.columns:
        xcol, ycol = "X", "Y"
    else:
        raise ValueError("CSV must contain ('xcoord', 'ycoord'), ('longitude', 'latitude'), or ('X', 'Y')")

    if "demError" in df.columns:
        dem_col = "demError"
    elif "dem_error" in df.columns:
        dem_col = "dem_error"
    else:
        raise ValueError("Missing required column: 'demError' or 'dem_error'")

    if "incidenceAngle" in df.columns and "azimuthAngle" in df.columns:
        inc_angle = np.deg2rad(df["incidenceAngle"].to_numpy(dtype=float))
        az_angle = np.deg2rad(df["azimuthAngle"].to_numpy(dtype=float))
    else:
        inc_angle = np.radians(42.85)
        az_angle = np.radians(350)

    cot_theta = 1 / np.tan(inc_angle)
    # East/north meters. Same signs as sarvey.geolocation.calculateGeolocationCorrection.
    east_m = df[dem_col].to_numpy(dtype=float) * np.cos(az_angle) * cot_theta
    north_m = -df[dem_col].to_numpy(dtype=float) * np.sin(az_angle) * cot_theta

    meter_to_deg_lat = 1 / 111320
    meter_to_deg_lon = 1 / (111320 * np.cos(np.radians(df[ycol].to_numpy(dtype=float))))

    df["longitude_corrected"] = df[xcol].to_numpy(dtype=float) + east_m * meter_to_deg_lon
    df["latitude_corrected"] = df[ycol].to_numpy(dtype=float) + north_m * meter_to_deg_lat
    cols = [name for name in df.columns if name not in (xcol, ycol, "longitude_corrected", "latitude_corrected")]
    insert_at = min(df.columns.get_loc(xcol), df.columns.get_loc(ycol))
    block = [xcol, ycol, "longitude_corrected", "latitude_corrected"]
    for offset, name in enumerate(block):
        cols.insert(insert_at + offset, name)
    df = df[cols]

    output_path = output_file or f"{os.path.splitext(input_file)[0]}_geocorr.csv"
    df.to_csv(output_path, index=False)
    print(f"Geolocation-corrected CSV saved to: {output_path}")

if __name__ == '__main__':
    main()
