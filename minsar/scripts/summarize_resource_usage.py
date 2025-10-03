#!/usr/bin/env python3
"""
Summarize memory and wall time from multiple *.time_log files.

Usage:
    summarize_resource_usage.py $TE/GalapagosSenDT128.template run_files other_dir

The script groups timing log files by run_file name, stripping only trailing numeric/date suffixes.
It computes max, median, and mean of memory (MB), and max and mean wall time (HH:MM:SS). It gets the number of bursts and looks using teh *template file
Output is written to summary.time_log.
"""

import re
import os
import glob
import sys
import h5py
import argparse
from osgeo import gdal
from collections import defaultdict
from statistics import mean, median
from datetime import timedelta
from minsar.objects.dataset_template import Template
from minsar.utils import process_utilities as putils
from minsar.objects import message_rsmas
from argparse import Namespace

NOMINAL_BURST_SIZE_SAMPLES = 23811 * 1505

##########################################################
def create_parser():
    DESCRIPTION = "Summarize memory usage and walltimes from multiple *.time_log files in walltimes_memory.log."
    EXAMPLE = """
Examples:
  summarize_resource_usage.py $TE/GalapagosSenD128.template run_files
  summarize_resource_usage.py $TE/qburstChilesSenD142.template run_files miaplpy_201411_201703/network_delaunay_4/run_files
    """.strip()

    parser = argparse.ArgumentParser( description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(dest='custom_template_file',  help="Template file with option settings (*.template)")
    parser.add_argument(dest="log_dirs", nargs="+", help="One or more dirs containing *.time_log files")
    parser.add_argument('--outdir', dest="outdir", type=str, default=os.getcwd(),  help="Output directory for summary file (Default: current directory).")

    inps = parser.parse_args()
    inps = putils.create_or_update_template(inps)

    if not os.path.isfile(inps.template_file) or not inps.template_file.endswith(".template"):
        parser.error(f"Ttemplate file not found : {inps.template_file}")

    log_files = []
    for pattern in inps.log_dirs:
        matched = glob.glob(os.path.join(pattern, "*.time_log"))
        if not matched:
            print(f"Warning: No files matched pattern: {pattern}/*.time_log", file=sys.stderr)
        log_files.extend(matched)

    if not log_files:
        parser.error("No valid *.time_log files found.")

    inps.log_files = log_files

    return inps

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
def get_number_of_bursts_from_out_create_jobfiles(file_path='out_create_jobfiles.o'):
    """Extracts and returns the number of bursts from the output file."""
    if not os.path.isfile(file_path):
        print(f"WARNING: {file_path} not found, exiting without creating walltimes_memory.log.")
        sys.exit(0)   # exit with success code 0

    number_of_bursts = None

    with open(file_path, 'r') as f:
        for line in f:
            if "number of bursts" in line:
                match = re.search(r'number of bursts: (\d+)', line)
                if match:
                    number_of_bursts = int(match.group(1))
                    break
                else:
                    raise ValueError("Line found but pattern did not match: " + line)

    if number_of_bursts is None:
        raise ValueError("No line containing 'number of bursts' found.")

    return number_of_bursts

##########################################################
def main(iargs=None):

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]
    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + ' ' + ' '.join(input_arguments))
    inps = create_parser()

    isce_log_files = [f for f in inps.log_files if f.endswith(".time_log") and "miaplpy" not in f]
    miaplpy_log_files = [f for f in inps.log_files if "miaplpy" in f and f.endswith(".time_log")]

    if miaplpy_log_files:
        miaplpy_log_file = miaplpy_log_files[0]
        miaplpy_dir = next(part for part in miaplpy_log_file.split("/") if part.startswith("miaplpy"))

    dataset_template = Template(inps.custom_template_file)
    az_looks = dataset_template.options.get('topsStack.azimuthLooks')
    range_looks = dataset_template.options.get('topsStack.rangeLooks')
    inps_dict = dataset_template.options

    number_of_bursts = get_number_of_bursts_from_out_create_jobfiles()

    slc_size_units = miaplpy_size_units = 0
    if isce_log_files:
       slc_size_units = number_of_bursts
    if miaplpy_log_files:
       miaplpy_size_units = get_miaplpy_data_size_from_data(miaplpy_dir + '/inputs/')

    summary_lines=[]
    summary_lines.append(f"Number of bursts, azimuth looks, range looks, miaplpy_file_size: {number_of_bursts} {az_looks} {range_looks}")
    summary_lines.append(f"SLC and miaplpy burst units: {slc_size_units:.2f} {miaplpy_size_units:.3f}")
    summary_lines.append(f"Queue: {os.getenv('QUEUENAME')}")

    data = defaultdict(list)
    for file in isce_log_files + miaplpy_log_files:
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

    with open(f"{inps.outdir}/walltimes_memory.log", "w") as f:
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
