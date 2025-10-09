#!/usr/bin/env python3
########################
# Authors: Sara Mirzaee, Falk Amelung
#######################
import argparse
import os
import shutil
import sys
import minsar.utils.process_utilities as putils
import numpy as np
import shutil
import glob
from pathlib import Path
from minsar.job_submission import check_words_in_file

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

def write_burst2safe_file_for_timeouts(input_file, timeout_dates):
    """
    Extracts lines from input_file that contain any of the timeout_dates
    and writes them to a new file, overwriting if it already exists.
    """
    dirname, basename = os.path.split(input_file)
    outname = basename.replace("burst2safe_", "burst2safe_timeouts_")
    output_file = os.path.join(dirname, outname)

    # Remove output file if it exists
    if os.path.exists(output_file):
        os.remove(output_file)

    # Read and filter lines
    with open(input_file, "r") as fin:
        lines = fin.readlines()

    matching_lines = [line for line in lines if any(date in line for date in timeout_dates)]

    with open(output_file, "w") as fout:
        fout.writelines(matching_lines)

    #print(f"Wrote {len(matching_lines)} matching lines to {output_file}")
    return output_file

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

    error_happened = False
    data_problem_strings_stdout = []     #FA 10/25: may not be needed
    timeout_strings = ["TimeoutError","asf_search.exceptions.ASFSearchError: Connection Error (Timeout): CMR took too long to respond"]
    data_problem_strings_stderr = [
                    "AttributeError: 'NoneType' object has no attribute 'tag'"
                    ]

    files = glob.glob(os.path.join(inps.slc_dir, 'run_01*'))
    stderr_files = [f for f in files if f.endswith(".e")]
    dirname = os.path.dirname(stderr_files[0])

    # identify dates with download/connection timeout
    timeout_dates= []
    for file in stderr_files:
        ## preprocess *.e files
        #  putils.remove_zero_size_or_length_error_files(run_file=job_name)      
        for string in timeout_strings:
            if check_words_in_file(file, string):
                date = file.split("_")[-2]
                timeout_dates.append(date)
                print('Timeout detected:' + file)

    print ('QQQQ FA 10/2025:','Timed out burst downloads (need script to re-download):') 
    if timeout_dates:
       write_burst2safe_file_for_timeouts(dirname + "/run_01_burst2safe_0", timeout_dates)
       copy_burst2safe_jobfile(dirname + "/run_01_burst2safe_0.job", new_tag="burst2safe_timeouts")
        
    # identify problem dates and remove *tiff amd *SAFE files
    problem_dates= []
    for file in stderr_files:
        #print('checking *.e, *.o from ' + file)
        ## preprocess *.e files
        #  putils.remove_zero_size_or_length_error_files(run_file=job_name)      
        for string in data_problem_strings_stderr:
            if check_words_in_file(file, string):
                date = file.split("_")[-2]
                problem_dates.append(date)
                print('Match:' + file)

    for date in problem_dates:
        print  ('Removed problem date: ' + str(date)) 
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


