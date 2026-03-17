#!/usr/bin/env python3
"""
Summarize memory, wall time, and efficiency from multiple *.time_log files.

Output (walltimes_memory.log) is designed so that many such files (e.g. from 100 datasets)
can be aggregated later to:
  - Fit walltime/memory vs number of bursts (c_*, s_* in job_defaults.cfg).
  - Assess whether num_threads per step is appropriate (CPU%, CPU_ratio).
  - Determine tasks per node from memory per task and node size.

Usage:
    summarize_resource_usage.py $TE/GalapagosSenD128.template run_files [other_dir ...]

Output format: Header lines (bursts, looks, queue); then one line per step with
MaxMem, MedMem, MeanMem, MaxWall, MeanWall, MeanCPU%%, MinCPU%%, CPU_ratio, MaxMajorFaults,
Efficiency (OK/LOW_CPU/HIGH_MAJOR_FAULTS/CHECK), LAUNCHER_PPN, LAUNCHER_NHOSTS, launcher_file_lines (lines in launcher task file when available), OMP_NUM_THREADS.
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
        parser.error(f"Template file not found: {inps.template_file}")

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

def _parse_optional_float(content, pattern, default=None):
    m = re.search(pattern, content)
    return float(m.group(1)) if m else default


##########################################################
def parse_time_log_file(filepath):
    """
    Extract from a .time_log file (GNU time -v style): memory (MB), wall time (s),
    user/system time (s), CPU%, major page faults. Returns a dict or None if essential
    fields are missing. Keys: mem_mb, wall_sec, user_sec, system_sec, cpu_pct, cpu_ratio, major_faults.
    """
    with open(filepath) as f:
        content = f.read()

    mem_match = re.search(r"Maximum resident set size\s*\(kbytes\):\s*(\d+)", content)
    wall_match = re.search(r"Elapsed \(wall clock\) time.*: ([0-9:.]+)", content)
    if not mem_match or not wall_match:
        print(f"Warning: failed to parse {filepath}", file=sys.stderr)
        return None

    mem_mb = int(mem_match.group(1)) / 1024
    hms = wall_match.group(1).split(":")
    try:
        if len(hms) == 3:
            h, m, s = map(float, hms)
        elif len(hms) == 2:
            h, m = 0, float(hms[0])
            s = float(hms[1])
        else:
            print(f"Warning: unrecognized wall time format in {filepath}", file=sys.stderr)
            return None
        wall_sec = int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        print(f"Warning: invalid wall time format in {filepath}", file=sys.stderr)
        return None

    user_sec = _parse_optional_float(content, r"User time \(seconds\):\s*([\d.]+)")
    system_sec = _parse_optional_float(content, r"System time \(seconds\):\s*([\d.]+)")
    cpu_pct = _parse_optional_float(content, r"Percent of CPU this job got:\s*(\d+)")
    major_faults = _parse_optional_float(content, r"Major \(requiring I/O\) page faults:\s*(\d+)")
    if major_faults is not None:
        major_faults = int(major_faults)

    cpu_ratio = None
    if user_sec is not None and system_sec is not None and wall_sec and wall_sec > 0:
        cpu_ratio = (user_sec + system_sec) / wall_sec

    return {
        "mem_mb": mem_mb,
        "wall_sec": wall_sec,
        "user_sec": user_sec,
        "system_sec": system_sec,
        "cpu_pct": cpu_pct,
        "cpu_ratio": cpu_ratio,
        "major_faults": major_faults,
    }


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
def get_launcher_params_from_job_file(job_file_path):
    """
    Read from a .job file: LAUNCHER_PPN, LAUNCHER_NHOSTS, OMP_NUM_THREADS. If LAUNCHER_JOB_FILE
    is set, resolve it and count non-empty lines (launcher tasks) -> launcher_file_lines. The file
    path is not written to the summary; only the task count is reported. Returns dict or None.
    """
    if not job_file_path or not os.path.isfile(job_file_path):
        return None
    params = {}
    job_dir = os.path.dirname(job_file_path)
    launcher_job_file_path = None
    try:
        with open(job_file_path) as f:
            for line in f:
                m = re.search(r"LAUNCHER_PPN\s*=\s*(\S+)", line)
                if m:
                    params["LAUNCHER_PPN"] = m.group(1).strip().strip("'\"")
                m = re.search(r"LAUNCHER_NHOSTS\s*=\s*(\S+)", line)
                if m:
                    params["LAUNCHER_NHOSTS"] = m.group(1).strip().strip("'\"")
                m = re.search(r"OMP_NUM_THREADS\s*=\s*(\S+)", line)
                if m:
                    params["OMP_NUM_THREADS"] = m.group(1).strip().strip("'\"")
                m = re.search(r"LAUNCHER_JOB_FILE\s*=\s*(\S+)", line)
                if m:
                    launcher_job_file_path = m.group(1).strip().strip("'\"")

        if launcher_job_file_path:
            path = launcher_job_file_path
            resolved = path if os.path.isabs(path) and os.path.isfile(path) else None
            if not resolved and job_dir:
                base = os.path.basename(path.split("/")[-1].split("$")[-1])
                candidate = os.path.join(job_dir, base)
                if os.path.isfile(candidate):
                    resolved = candidate
            if resolved and os.path.isfile(resolved):
                with open(resolved) as lf:
                    params["launcher_file_lines"] = sum(1 for ln in lf if ln.strip())
    except (OSError, IOError):
        pass
    return params if params else None

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
    """Extracts and returns the number of bursts from the output file, or None if file missing."""
    if not os.path.isfile(file_path):
        return None

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

   # if number_of_bursts is None:
   #     raise ValueError("No line containing 'number of bursts' found.")

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

    if number_of_bursts is None:
        print("Note: out_create_jobfiles.o not found; number of bursts will be reported as n/a.", file=sys.stderr)

    slc_size_units = miaplpy_size_units = 0
    if isce_log_files and number_of_bursts is not None:
       slc_size_units = number_of_bursts
    if miaplpy_log_files:
       miaplpy_size_units = get_miaplpy_data_size_from_data(miaplpy_dir + '/inputs/')

    job_submission_scheme = os.environ.get('JOB_SUBMISSION_SCHEME', '')
    summary_lines = []
    summary_lines.append("# Fields per step: MaxMem,MedMem,MeanMem (MB); MaxWall,MeanWall; MeanCPU%%,MinCPU%%,CPU_ratio,MaxMajorFaults,Efficiency; LAUNCHER_PPN,LAUNCHER_NHOSTS,launcher_file_lines,OMP_NUM_THREADS (for aggregation across runs).")
    number_of_bursts_str = str(number_of_bursts) if number_of_bursts is not None else "n/a"
    summary_lines.append(f"Number of bursts, azimuth looks, range looks, miaplpy_file_size: {number_of_bursts_str} {az_looks} {range_looks}")
    summary_lines.append(f"SLC and miaplpy burst units: {slc_size_units:.2f} {miaplpy_size_units:.3f}")
    summary_lines.append(f"Queue: {os.getenv('QUEUENAME')}")
    summary_lines.append(f"JOB_SUBMISSION_SCHEME: {job_submission_scheme}")

    data = defaultdict(list)
    group_dirs = {}
    for file in isce_log_files + miaplpy_log_files:
        row = parse_time_log_file(file)
        if row is not None:
            group = extract_runfile_name(file)
            data[group].append(row)
            if group not in group_dirs:
                group_dirs[group] = os.path.dirname(file)

    def efficiency_label(mean_cpu_pct, max_major_faults):
        if mean_cpu_pct is not None and max_major_faults is not None:
            if mean_cpu_pct >= 85 and max_major_faults <= 10:
                return "OK"
            if mean_cpu_pct < 70:
                return "LOW_CPU"
            if max_major_faults > 100:
                return "HIGH_MAJOR_FAULTS"
            return "CHECK"
        return "n/a"

    def group_sort_key(name):
        if "miaplpy" in name:
            return (1, name)
        if "mintpy" in name:
            return (2, name)
        return (0, name)

    if not os.path.isdir(inps.outdir):
        os.makedirs(inps.outdir, exist_ok=True)

    with open(f"{inps.outdir}/walltimes_memory.log", "w") as f:
        f.write("\n".join(summary_lines) + "\n")
        for group in sorted(data, key=group_sort_key):
            rows = data[group]
            mem_vals = [r["mem_mb"] for r in rows]
            wall_vals = [r["wall_sec"] for r in rows]
            max_mem = max(mem_vals)
            med_mem = median(mem_vals)
            mean_mem = mean(mem_vals)
            max_wall = format_seconds(max(wall_vals))
            mean_wall = format_seconds(mean(wall_vals))
            line = (
                f"{group}: MaxMem={max_mem:.2f} MB  MedMem={med_mem:.2f} MB  "
                f"MeanMem={mean_mem:.2f} MB  MaxWall={max_wall}  MeanWall={mean_wall}"
            )
            cpu_pcts = [r["cpu_pct"] for r in rows if r.get("cpu_pct") is not None]
            cpu_ratios = [r["cpu_ratio"] for r in rows if r.get("cpu_ratio") is not None]
            major_faults_list = [r["major_faults"] for r in rows if r.get("major_faults") is not None]
            mean_cpu_pct = mean(cpu_pcts) if cpu_pcts else None
            min_cpu_pct = min(cpu_pcts) if cpu_pcts else None
            mean_cpu_ratio = mean(cpu_ratios) if cpu_ratios else None
            max_major_faults = max(major_faults_list) if major_faults_list else None
            eff = efficiency_label(mean_cpu_pct, max_major_faults)
            line += f"  MeanCPU%={mean_cpu_pct:.0f}" if mean_cpu_pct is not None else "  MeanCPU%=n/a"
            line += f"  MinCPU%={min_cpu_pct:.0f}" if min_cpu_pct is not None else "  MinCPU%=n/a"
            line += f"  CPU_ratio={mean_cpu_ratio:.2f}" if mean_cpu_ratio is not None else "  CPU_ratio=n/a"
            line += f"  MaxMajorFaults={max_major_faults}" if max_major_faults is not None else "  MaxMajorFaults=n/a"
            line += f"  Efficiency={eff}"
            job_file = os.path.join(group_dirs.get(group, ''), f"{group}_0.job")
            launcher_params = get_launcher_params_from_job_file(job_file)
            if launcher_params:
                # Fixed order: LAUNCHER_PPN, LAUNCHER_NHOSTS, launcher_file_lines, OMP_NUM_THREADS
                order = ("LAUNCHER_PPN", "LAUNCHER_NHOSTS", "launcher_file_lines", "OMP_NUM_THREADS")
                launcher_str = "  ".join(f"{k}={launcher_params[k]}" for k in order if k in launcher_params)
                line = f"{line}  {launcher_str}"
            print(line)
            f.write(line + "\n")

if __name__ == "__main__":
    main()
