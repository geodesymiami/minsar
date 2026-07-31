#!/usr/bin/env python3
"""CLI to reduce the time span of SLC stack inputs."""
import h5py
import pandas as pd
import os
import numpy as np
import argparse
import datetime
from mintpy.utils import ptime

parser = argparse.ArgumentParser(description="Reduce time span of SLC stack inputs.")
parser.add_argument('--start', required=True, type=str, help='Start date in YYYYMMDD format')
parser.add_argument('--end', required=True, type=str, help='End date in YYYYMMDD format')
parser.add_argument('input_file', type=str, help='Path to input slcStack.h5 file name')
parser.add_argument('-o', '--output_file', type=str, default='slcStack_reduced.h5', help='Output HDF5 file name')
args = parser.parse_args()

start_date = args.start
end_date = args.end
input_file = args.input_file
output_file = args.output_file

# check if input_file is the same as output_file
if os.path.abspath(input_file) == os.path.abspath(output_file):
    raise ValueError("Input file and output file must be different")

print(f"Start date: {start_date}")
print(f"End date: {end_date}")
print(f"Input file: {input_file}")
print(f"Output file: {output_file}")

# do some checks on the date format
if len(start_date) != 8 or len(end_date) != 8:
    raise ValueError("Dates must be in YYYYMMDD format")
try:
    datetime.datetime.strptime(start_date, '%Y%m%d')
    datetime.datetime.strptime(end_date, '%Y%m%d')
except ValueError:
    raise ValueError("Dates must be in YYYYMMDD format")
# check if input file exists
if not os.path.exists(input_file):
    raise FileNotFoundError(f"Input file {input_file} does not exist")
# check if output file already exists
if os.path.exists(output_file):
    raise FileExistsError(f"Output file {output_file} already exists. Please remove it or choose a different name.")

# check if start_date is before end_date
if start_date >= end_date:
    raise ValueError("Start date must be before end date")

with h5py.File(input_file, 'r') as f:
    print("Read the dates and bperp from the input file.")
    time_data = f['date'][:]

    # check if at least one date is within the range of the dates in the input file
    if (time_data[0].decode('utf-8') > end_date) or (time_data[-1].decode('utf-8') < start_date):
        raise ValueError("No dates in the input file are within the specified range.")

    bperp = f['bperp'][:]

    # read all metadata from the attributes
    metadata = {key: f.attrs[key] for key in f.attrs.keys()}

    # Convert to datetime objects
    time_data = [pd.to_datetime(t.decode('utf-8')) for t in time_data]

    # Filter the time data based on the start and end dates
    # create a mask for the time data
    # convert start_date and end_date to datetime
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)
    mask = np.zeros(len(time_data), dtype=bool)
    for i, t in enumerate(time_data):
        if start_date <= t <= end_date:
            mask[i] = True
    filtered_time_data = np.array(time_data)[mask]
    # convert filtered_time_data back to bytes for HDF5 storage
    filtered_time_data = np.array([t.strftime('%Y%m%d').encode('utf-8') for t in filtered_time_data])

    print("Create a new HDF5 file with the filtered time data")
    with h5py.File(output_file, 'w') as out_f:
        out_f.create_dataset('date', data=filtered_time_data)
        out_f.create_dataset('bperp', data=bperp[mask])
        # save metadata as attributes at root level
        for key, value in metadata.items():
            out_f.attrs[key] = value

with h5py.File(input_file, 'r') as f, h5py.File(output_file, 'a') as out_f:
        slc_shape = f['slc'].shape
        slc_dtype = f['slc'].dtype
        print("Create the reduced slc dataset")
        out_f.create_dataset('slc', shape=(np.sum(mask), slc_shape[1], slc_shape[2]), dtype=slc_dtype)
        idx = 0
        prog_bar = ptime.progressBar(maxValue=slc_shape[0])
        for i in range(slc_shape[0]):
            if mask[i]:
                out_f['slc'][idx, :, :] = f['slc'][i, :, :]
                idx += 1
            prog_bar.update(i + 1, every=1,
                           suffix='{}/{} images checked'.format(i + 1, slc_shape[0] + 1))
        prog_bar.close()

        print(f"Reduced slc dataset to {idx} images.")
        # Write date, bperp, and metadata if not already present
        if 'date' not in out_f:
            out_f.create_dataset('date', data=filtered_time_data)
        if 'bperp' not in out_f:
            out_f.create_dataset('bperp', data=bperp[mask])
        for key, value in metadata.items():
            out_f.attrs[key] = value

print(f"Reduced time span data saved to {output_file}.")

