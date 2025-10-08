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

    DESCRIPTION = "Check run_burst2safe output files and remove data for problematic dates"
    EXAMPLE = """
Examples:
  check_burst2safe_outputs.py run_01_*.e run_01_*.o
  check_burst2safe_outputs.py SLC/run_01_*.e
    """

    parser = argparse.ArgumentParser( description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(dest="files", nargs="+", help="run_01*.e, run_01*.o files")

    inps = parser.parse_args(args=iargs)

    return inps


def main(iargs=None):

    inps = cmd_line_parser(iargs)

    # project_dir = os.path.dirname(work_dir)

    error_happened = False
    data_problem_strings_stdout = []     #FA 10/25: may not be needed
    data_problem_strings_stderr = [
                    "AttributeError: 'NoneType' object has no attribute 'tag'"
                    ]

    stderr_files = [f for f in inps.files if f.endswith(".e")]
    dirname = os.path.dirname(stderr_files[0])
    # stdout_files = [f for f in inps.files if f.endswith(".o")]
    # matched_error_strings = []

    problem_dates= []
    for file in stderr_files:
        # print('checking *.e, *.o from ' + file)
        ## preprocess *.e files
        #  putils.remove_zero_size_or_length_error_files(run_file=job_name)      
        for string in data_problem_strings_stderr:
            if check_words_in_file(file, string):
                date = file.split("_")[-2]
                problem_dates.append(date)


    for date in problem_dates:
        # matching_files = glob.glob("*" + date + "*")  
        print  ('Removed data for problem date: ' + str(date)) 
        matching_files = glob.glob(os.path.join(dirname, "*" + date + "*"))
        for f in matching_files:
             if os.path.exists(f):
                try:
                    (shutil.rmtree if os.path.isdir(f) else os.remove)(f)
                except Exception as e:
                    print(f"Could not remove {f}: {e}")
        
        # [os.remove(f)  for f in matching_files if os.path.exists(f)]  
        # [shutil.rmtree(f) if os.path.isdir(f) else os.remove(f) for f in matching_files if os.path.exists(f)]    

    return

if __name__ == "__main__":
    main()


