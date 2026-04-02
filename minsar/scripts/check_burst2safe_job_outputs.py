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


def _safe_exists_for_date(dirname, date_str):
    """Return True if a .SAFE directory exists in dirname whose name contains date_str (YYYYMMDD)."""
    pattern = os.path.join(dirname, "*" + date_str + "*.SAFE")
    for p in glob.glob(pattern):
        if os.path.isdir(p):
            return True
    return False


def _error_summary_from_stderr(stderr_path, timeout_strings, data_problem_strings_stderr):
    """
    Classify error and return (error_type, short_summary).
    error_type: 'timeout' | 'data_problem' | 'other'
    """
    for s in timeout_strings:
        if check_words_in_file(stderr_path, s):
            return "timeout", "Timeout"
    for s in data_problem_strings_stderr:
        if check_words_in_file(stderr_path, s):
            return "data_problem", s[:80] if len(s) > 80 else s
    try:
        with open(stderr_path, "r") as f:
            first = None
            file_not_found_line = None
            for line in f:
                line_stripped = line.strip()
                if line_stripped and "FileNotFoundError" in line_stripped:
                    file_not_found_line = line_stripped  # full line for errors_redundant/errors_eliminated
                    break
                if line_stripped and first is None:
                    first = line_stripped[:80] if len(line_stripped) > 80 else line_stripped
        if file_not_found_line is not None:
            return "other", file_not_found_line
        return "other", first if first else "Error in stderr"
    except OSError:
        return "other", "Error in stderr"


def cmd_line_parser(iargs=None):

    DESCRIPTION = "Check run_burst2safe job output files and remove data for problematic dates"
    EXAMPLE = """
Examples:
  check_burst2safe_job_outputs.py SLC

Docs: https://github.com/geodesymiami/minsar/blob/master/docs/README_burst_download.md
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

    # Remove previous run list and job files so we start fresh (timeouts and reruns)
    for pattern in ["run_01_burst2safe_timeout*", "run_01_burst2safe_rerun_*"]:
        for f in glob.glob(os.path.join(inps.slc_dir, pattern)):
            try:
                (shutil.rmtree if os.path.isdir(f) else os.remove)(f)
            except OSError:
                pass

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
        # Preserve original run file before any modifications
        run_file_orig = os.path.join(dirname, "run_01_burst2safe_0_orig")
        shutil.copy2(run_file, run_file_orig)

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
                break

    # Per-error records: (date, line_idx, error_type, summary, run_line) for each non-zero .e file
    error_records = []
    for stderr_path in stderr_files:
        idx = line_index_for_stderr_file(stderr_path)
        if idx is None:
            continue
        date_str, _ = _date_and_task_index_from_stderr_filename(stderr_path)
        if not date_str:
            date_str = _date_from_stderr_filename(stderr_path)
        if not date_str:
            continue
        error_type, summary = _error_summary_from_stderr(stderr_path, timeout_strings, data_problem_strings_stderr)
        run_line = run_lines[idx].strip() if run_lines and 0 <= idx < len(run_lines) else ""
        error_records.append((date_str, idx, error_type, summary, run_line))

    # Split into redundant (SAFE exists for date) vs eliminated (no SAFE)
    errors_redundant = []
    errors_eliminated = []
    for date_str, line_idx, error_type, summary, run_line in error_records:
        one_liner = "{} {}".format(date_str, summary)
        if _safe_exists_for_date(dirname, date_str):
            errors_redundant.append(one_liner)
        else:
            errors_eliminated.append(one_liner)

    errors_redundant_path = os.path.join(dirname, "errors_redundant.txt")
    errors_eliminated_path = os.path.join(dirname, "errors_eliminated.txt")
    if errors_redundant:
        with open(errors_redundant_path, "w") as f:
            f.write("\n".join(errors_redundant) + "\n")
    if errors_eliminated:
        with open(errors_eliminated_path, "w") as f:
            f.write("\n".join(errors_eliminated) + "\n")
    if errors_redundant or errors_eliminated:
        cwd = os.getcwd()
        parts = []
        if errors_redundant:
            parts.append("{} ({})".format(os.path.relpath(errors_redundant_path, cwd), len(errors_redundant)))
        if errors_eliminated:
            parts.append("{} ({})".format(os.path.relpath(errors_eliminated_path, cwd), len(errors_eliminated)))
        print("Wrote " + ", ".join(parts))

    all_error_line_indices = sorted(set(error_line_indices))

    # run_01_burst2safe_0_clean: original run file with problem lines removed
    if run_lines and all_error_line_indices:
        clean_path = os.path.join(dirname, "run_01_burst2safe_0_clean")
        error_set = set(all_error_line_indices)
        clean_lines = [run_lines[i] for i in range(len(run_lines)) if i not in error_set]
        with open(clean_path, "w") as f:
            f.writelines(clean_lines)

    # timeout.txt and timeout run file: only when there are timeouts
    if timeout_line_indices and run_lines:
        timeout_indices = sorted(set(timeout_line_indices))
        timeout_txt = os.path.join(dirname, "timeout.txt")
        with open(timeout_txt, "w") as fout:
            for i in timeout_indices:
                if 0 <= i < len(run_lines):
                    fout.write(run_lines[i])
        timeout_file = os.path.join(dirname, "run_01_burst2safe_timeout_0")
        with open(timeout_file, "w") as fout:
            for i in timeout_indices:
                if 0 <= i < len(run_lines):
                    fout.write(run_lines[i])
        if os.path.isfile(job_file):
            copy_burst2safe_jobfile(job_file, new_tag="burst2safe_timeout")
        print("Wrote {} ({} timeouts)".format(os.path.relpath(timeout_file, os.getcwd()), len(timeout_indices)))

    # Rerun file: only when there are non-timeout errors
    error_only_indices = sorted(set(error_line_indices) - set(timeout_line_indices))
    if error_only_indices and run_lines:
        rerun_file = os.path.join(dirname, "run_01_burst2safe_rerun_0")
        selected = [run_lines[i] for i in error_only_indices]
        with open(rerun_file, "w") as fout:
            fout.writelines(selected)
        if os.path.isfile(job_file):
            copy_burst2safe_jobfile(job_file, new_tag="burst2safe_rerun")
        print("Wrote {} ({} errors)".format(os.path.relpath(rerun_file, os.getcwd()), len(error_only_indices)))

    # Identify problem dates and remove *tiff and *SAFE files
    problem_dates = []
    for file in stderr_files:
        for string in data_problem_strings_stderr:
            if check_words_in_file(file, string):
                date = _date_from_stderr_filename(file)
                if date and date not in problem_dates:
                    problem_dates.append(date)
                break

    if problem_dates:
        log_index = 1
        while os.path.exists(f"removed_dates_{log_index}.txt"):
            log_index += 1
        logfile = f"removed_dates_{log_index}.txt"
        for date in problem_dates:
            with open(logfile, "a") as f:
                f.write("Removed problem date: {}\n".format(date))
            matching_files = glob.glob(os.path.join(dirname, "*" + date + "*"))
            for f in matching_files:
                if os.path.exists(f):
                    try:
                        (shutil.rmtree if os.path.isdir(f) else os.remove)(f)
                    except Exception as e:
                        print("Could not remove {}: {}".format(f, e))
        print("Removed {} problem date(s): {}".format(len(problem_dates), " ".join(problem_dates)))
        
    if inps.clean_flag:
        for file in stderr_files:
            if os.path.exists(file):
                os.remove(file)

    return


if __name__ == "__main__":
    main()


