#!/usr/bin/env python3
########################
# Authors: Sara Mirzaee, Falk Amelung
#######################
import argparse
import os
import re
import shutil
import sys
import minsar.utils.process_utilities as putils
from minsar.objects import message_rsmas
import numpy as np
import shutil
import glob
from pathlib import Path
from minsar.job_submission import check_words_in_file


def _date_from_stderr_filename(filepath):
    """Extract 8-digit date (YYYYMMDD) from run_01_burst2safe_*_<date>_*.e filename."""
    base = os.path.basename(filepath).replace(".e", "")
    match = re.search(r"\d{8}", base)
    return match.group(0) if match else None


def _date_and_task_index_from_stderr_filename(filepath):
    """
    Extract date and launcher task index from .e filename.
    Pattern: run_01_burst2safe_0_YYYYMMDD_<JID>.e -> (date, 0-based line index).
    Returns (date_str or None, task_index or None). task_index is None if not in filename.
    """
    base = os.path.basename(filepath)
    # Match _YYYYMMDD.e or _YYYYMMDD_JID.e at end
    match = re.search(r"(\d{8})(?:_(\d+))?\.e$", base)
    if not match:
        return None, None
    date_str = match.group(1)
    jid_str = match.group(2)
    task_index = int(jid_str) if jid_str is not None else None
    return date_str, task_index

def cmd_line_parser(iargs=None):

    DESCRIPTION = "Check run_burst2safe job output files and remove data for problematic dates"
    EXAMPLE = """
Examples:
  check_burst2safe_job_outputs.py SLC
    """

    parser = argparse.ArgumentParser( description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(dest="slc_dir", help="SLC directory")
    parser.add_argument('--clean', dest='clean_flag', action='store_true', default=False, help='remove *.e files after running')

    inps = parser.parse_args(args=iargs)

    return inps

def copy_burst2safe_jobfile(jobfile, new_tag):
    """
    Copy the jobfile and replace all 'burst2safe' occurrences with the new tag.
    """
    with open(jobfile, 'r') as f:
        lines = f.readlines()

    new_lines = [line.replace("burst2safe", new_tag) for line in lines]
    
    new_jobfile = jobfile.replace("burst2safe", new_tag)
    with open(new_jobfile, 'w') as f:
        f.writelines(new_lines)
    #print(f"Created {new_jobfile}")

def main(iargs=None):

    inps = cmd_line_parser(iargs)

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    error_happened = False
    data_problem_strings_stdout = []     #FA 10/25: may not be needed
    timeout_strings = ["TimeoutError","asf_search.exceptions.ASFSearchError: Connection Error (Timeout): CMR took too long to respond"]
    data_problem_strings_stderr = [
                    "AttributeError: 'NoneType' object has no attribute 'tag'",
                    "ValueError: min() arg is an empty sequence"
                    ]

    files = glob.glob(os.path.join(inps.slc_dir, 'run_01*'))
    stderr_files = [f for f in files if f.endswith(".e")]

    # Remove zero-size *.e files first
    for f in stderr_files:
        try:
            if os.path.getsize(f) == 0:
                os.remove(f)
        except OSError:
            pass
    stderr_files = [f for f in glob.glob(os.path.join(inps.slc_dir, 'run_01*')) if f.endswith(".e")]

    dirname = os.path.dirname(stderr_files[0]) if stderr_files else inps.slc_dir
    run_file = os.path.join(dirname, "run_01_burst2safe_0")
    if not os.path.isfile(run_file):
        run_file = os.path.join(dirname, "run_01_burst2safe")
    job_file = run_file + ".job" if os.path.isfile(run_file + ".job") else os.path.join(dirname, "run_01_burst2safe_0.job")

    run_lines = []
    if os.path.isfile(run_file):
        with open(run_file, "r") as f:
            run_lines = f.readlines()

    def line_index_for_stderr_file(stderr_path):
        """One run-file line index for this .e file: use task index from filename, else first line containing date."""
        date_str, task_index = _date_and_task_index_from_stderr_filename(stderr_path)
        if date_str is None:
            return None
        if task_index is not None and 0 <= task_index < len(run_lines):
            return task_index
        for i, line in enumerate(run_lines):
            if date_str in line:
                return i
        return None

    # One entry per non-zero .e file: collect line indices (by task index in filename or date match)
    error_line_indices = []
    for f in stderr_files:
        idx = line_index_for_stderr_file(f)
        if idx is not None:
            error_line_indices.append(idx)

    # Timeouts: one entry per .e file that contains a timeout string
    timeout_line_indices = []
    for file in stderr_files:
        for string in timeout_strings:
            if check_words_in_file(file, string):
                idx = line_index_for_stderr_file(file)
                if idx is not None:
                    timeout_line_indices.append(idx)
                print('Timeout detected:' + file)
                print('Timed out burst downloads (need script to re-download):')
                break

    # Write timeout.txt with run-file lines that were timeouts (for reference)
    timeout_txt = os.path.join(dirname, "timeout.txt")
    if timeout_line_indices and run_lines:
        timeout_indices = sorted(set(timeout_line_indices))
        with open(timeout_txt, "w") as fout:
            for i in timeout_indices:
                if 0 <= i < len(run_lines):
                    fout.write(run_lines[i])
        print("Wrote {} ({} timeout entries)".format(timeout_txt, len(timeout_indices)))
    elif os.path.isfile(timeout_txt):
        open(timeout_txt, "w").close()  # clear if no timeouts

    # Rerun: only run_01_burst2safe_rerun_0 and run_01_burst2safe_rerun_0.job (merge timeouts + errors)
    rerun_file = os.path.join(dirname, "run_01_burst2safe_rerun_0")
    rerun_line_indices = sorted(set(timeout_line_indices) | set(error_line_indices))
    if rerun_line_indices and run_lines:
        selected = [run_lines[i] for i in rerun_line_indices]
        with open(rerun_file, "w") as fout:
            fout.writelines(selected)
        print("Wrote {} ({} rerun entries)".format(rerun_file, len(rerun_line_indices)))
        if os.path.isfile(job_file):
            copy_burst2safe_jobfile(job_file, new_tag="burst2safe_rerun")
    else:
        # No errors/timeouts: empty rerun file so rerun_burst2safe.sh loop exits
        with open(rerun_file, "w") as fout:
            pass
        print("No errors/timeouts; {} is empty.".format(rerun_file))

    # identify problem dates and remove *tiff and *SAFE files
    problem_dates = []
    for file in stderr_files:
        for string in data_problem_strings_stderr:
            if check_words_in_file(file, string):
                date = _date_from_stderr_filename(file)
                if date:
                    problem_dates.append(date)
                print('Match:' + file)

    log_index = 1
    while os.path.exists(f"removed_dates_{log_index}.txt"):
       log_index += 1
    logfile = f"removed_dates_{log_index}.txt"

    for date in problem_dates:
        msg = f"Removed problem date: {date}"
        print(msg)  
        with open(logfile, "a") as f:
             f.write(msg + "\n")

        matching_files = glob.glob(os.path.join(dirname, "*" + date + "*"))
        for f in matching_files:
             if os.path.exists(f):
                try:
                    (shutil.rmtree if os.path.isdir(f) else os.remove)(f)
                except Exception as e:
                    print(f"Could not remove {f}: {e}")
        
    if inps.clean_flag:
        for file in stderr_files:
            if os.path.exists(file):
                os.remove(file)

    return


if __name__ == "__main__":
    main()


