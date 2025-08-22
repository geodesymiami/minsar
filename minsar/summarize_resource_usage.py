#!/usr/bin/env python3
"""
Summarize memory and wall time from multiple *.time_log files.

Usage:
    summarize_resource_usage.py $TE/GalapagosSenDT128.template run_files/run_*time_log other_dir/*run*time_log

The script groups timing log files by run_file name, stripping only trailing numeric/date suffixes.
It computes max, median, and mean of memory (MB), and max and mean wall time (HH:MM:SS). It gets the number of bursts and looks using teh *template file
Output is written to summary.time_log.
"""

import re
import os
import glob
import h5py
from osgeo import gdal
from collections import defaultdict
from statistics import mean, median
from datetime import timedelta
from minsar.objects.dataset_template import Template
from minsar.utils import process_utilities as putils

NOMINAL_BURST_SIZE_SAMPLES = 23811 * 1505

##########################################################
def parse_time_log_file(filepath):
    """Extract memory in MB and wall time in seconds from a .time_log file."""
    with open(filepath) as f:
        content = f.read()

    mem_match = re.search(r"Maximum resident set size\s*\(kbytes\):\s*(\d+)", content)
    wall_match = re.search(r"Elapsed \(wall clock\) time.*: ([0-9:.]+)", content)

    if not mem_match or not wall_match:
        print(f"Warning: failed to parse {filepath}")
        return None, None

    mem_mb = int(mem_match.group(1)) / 1024

    hms = wall_match.group(1).split(":")
    try:
        if len(hms) == 3:
            h, m, s = map(float, hms)
        elif len(hms) == 2:
            h, m = 0, float(hms[0])
            s = float(hms[1])
        else:
            print(f"Warning: unrecognized wall time format in {filepath}")
            return None, None
        wall_sec = int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        print(f"Warning: invalid wall time format in {filepath}")
        return None, None

    return mem_mb, wall_sec


##########################################################
def extract_runfile_name(filename):
    base = os.path.basename(filename).replace('.time_log', '')
    parts = base.split('_')

    group_parts = parts[:2]  # 'run' and step number

    for part in parts[2:]:
        if part.isdigit() and (len(part) == 8 or int(part) < 1000):
            break
        group_parts.append(part)

    return '_'.join(group_parts)


##########################################################
def format_seconds(secs):
    """Format seconds as H:MM:SS."""
    return str(timedelta(seconds=int(round(secs))))

##########################################################
def get_slc_data_size_from_data(dir, number_of_bursts):
    
    burst_files = glob.glob(f"{dir}/*.tiff")
    if not burst_files:
        raise FileNotFoundError(f"User error: no burst files (*.tiff) found in directory: {dir}")
    dataset = gdal.Open(burst_files[0])

    width = dataset.RasterXSize
    length = dataset.RasterYSize
    
    number_of_samples = length * width
    burst_size_units = number_of_samples / NOMINAL_BURST_SIZE_SAMPLES
    total_burst_size_units = round(burst_size_units * number_of_bursts, 2)
    return total_burst_size_units

##########################################################
def get_miaplpy_data_size_from_data(dir):
    """Calculate the total SLC size in burst-size units based on the SLC data."""
    slc_file = f"{dir}/slcStack.h5" 
    with h5py.File(slc_file, 'r') as f:
        shape = f['/slc'].shape  # Format: (time, length, width)
        num_dates, length, width = shape

    print(f"slcStack Width: {width}, Length: {length}, Dates: {num_dates}")
    number_of_samples = length * width
    burst_size_units = round(number_of_samples / NOMINAL_BURST_SIZE_SAMPLES, 3)

    return burst_size_units

##########################################################
def main():
    hardcoded_patterns = [
        "run_files/run_*time_log",
        "miaplpy_SN_201606_201608/network_single_reference/run_files/run*time_log",
        "/Users/famelung/code/minsar/samples/unittestGalapagosSenDT128.template"
    ]

    files = []
    for pattern in hardcoded_patterns:
        matched = glob.glob(pattern)
        print(f"Pattern: {pattern}")
        print(f"Matched files: {matched}")
        files.extend(matched)

    if not files:
        print("No matching .time_log files found.")
        return

    custom_template_file = next(f for f in files if f.endswith(".template"))
    dataset_template = Template(custom_template_file)

    miaplpy_time_log_files = [f for f in files if "miaplpy" in f and f.endswith(".time_log")]
    miaplpy_time_log_file = miaplpy_time_log_files[0]
    miaplpy_dir = next(part for part in miaplpy_time_log_file.split("/") if part.startswith("miaplpy"))

    # number_of_bursts = putils.get_number_of_bursts(self.inps)
    number_of_bursts = 2
    az_looks = dataset_template.options.get('topsStack.azimuthLooks')
    range_looks = dataset_template.options.get('topsStack.rangeLooks')

    slc_size_units = get_slc_data_size_from_data(dir='SLC', number_of_bursts=number_of_bursts)
    miaplpy_size_units = get_miaplpy_data_size_from_data(miaplpy_dir + '/inputs/')

    summary_lines=[]
    summary_lines.append(f"Number of bursts, azimuth looks, range looks, miaplpy_file_size: {number_of_bursts} {az_looks} {range_looks}")
    summary_lines.append(f"SLC and miaplpy burst units: {slc_size_units:.2f} {miaplpy_size_units:.3f}")

    data = defaultdict(list)
    for file in files:
        mem_mb, wall_sec = parse_time_log_file(file)
        if mem_mb is not None:
            group = extract_runfile_name(file)
            data[group].append((mem_mb, wall_sec))

    def group_sort_key(name):
        if "miaplpy" in name:
            return (1, name)
        if "mintpy" in name:
            return (2, name)
        return (0, name)

    with open("summary.time_log", "w") as f:
        f.write("\n".join(summary_lines) + "\n")        
        for group in sorted(data, key=group_sort_key):
            mem_vals = [x[0] for x in data[group]]
            wall_vals = [x[1] for x in data[group]]
            max_mem = max(mem_vals)
            med_mem = median(mem_vals)
            mean_mem = mean(mem_vals)
            max_wall = format_seconds(max(wall_vals))
            mean_wall = format_seconds(mean(wall_vals))
            line = (
                f"{group}: MaxMem={max_mem:.2f} MB  MedMem={med_mem:.2f} MB  "
                f"MeanMem={mean_mem:.2f} MB  MaxWall={max_wall}  MeanWall={mean_wall}"
            )
            print(line)
            f.write(line + "\n")

if __name__ == "__main__":
    main()