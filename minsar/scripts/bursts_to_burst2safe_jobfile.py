#!/usr/bin/env python3

import os
import sys
import re
import glob
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

from minsar.objects import message_rsmas
from minsar.objects.auto_defaults import PathFind
from minsar.job_submission import JOB_SUBMIT

# pathObj = PathFind()
inps = None

##############################################################################
EXAMPLE = """example:
    bursts_to_burst2safe_jobfile.py SLC

    Creates runfile for burst2safe for each acquisition 

 """

DESCRIPTION = ("""
     Creates runfile and jobfile for burst2safe (run after downloading bursts)
""")

def create_parser():
    synopsis = 'Create burst2safe run_file'
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    # parser.add_argument('ssara_listing_path', help='file name\n')
    parser.add_argument('burst_dir_path', metavar="DIRECTORY", help='bursts directory')

    parser.add_argument("--queue", dest="queue", metavar="QUEUE", help="Name of queue to submit job to")

    inps = parser.parse_args()

    # inps.ssara_listing_path = Path(inps.ssara_listing_path).resolve()
    
    return inps

###############################################
def clean_path(f):
        p = Path(f)
        # Remove all suffixes
        while p.suffix:
            p = p.with_suffix('')
        # Return only the filename (i.e., remove the "SLC/" part)
        return p.name

###############################################

def main(iargs=None):

    # parse
    inps = create_parser()

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    inps.work_dir = os.getcwd()
    run_01_burst2safe_path = Path(inps.work_dir) / inps.burst_dir_path / 'run_01_burst2safe'

    burst_list_fullpath = glob.glob(inps.burst_dir_path + '/*.tiff')
    burst_list = [clean_path(f) for f in burst_list_fullpath ]
    
    bursts_by_date = defaultdict(list)
    for burst in burst_list:
        date_str = burst.split('_')[3][:8]  # Extract YYYYMMDD
        bursts_by_date[date_str].append(burst)

    max_date = max(bursts_by_date, key=lambda k: len(bursts_by_date[k]))
    print("Date with most bursts:", max_date)

    filtered_bursts_by_date = { date: bursts for date, bursts in bursts_by_date.items() if len(bursts) == len(bursts_by_date[max_date]) }

    first_key = next(iter(filtered_bursts_by_date))
    number_of_bursts = len(filtered_bursts_by_date[first_key])
    if number_of_bursts <= 1:
        raise RuntimeError("USER ERROR: need more than 1 burst for ISCE processing (in run_07_merge* step). For {first_key} there is only 1 burst")
        sys.exit(1)

    with open(run_01_burst2safe_path, "w") as f:
        for date, bursts in sorted(filtered_bursts_by_date.items()):
            output_dir = str(Path(inps.work_dir) / inps.burst_dir_path)
            f.write("burst2safe " + ' '.join(bursts) + " --keep-files --output-dir " + output_dir + "\n")

    print("Created: ", run_01_burst2safe_path)
    
    # find *template file (needed currently for run_workflow.bash)
    current_directory = Path(os.getcwd())
    parent_directory = current_directory.parent
    template_files_current = glob.glob(str(current_directory / '*.template'))
    template_files_parent = glob.glob(str(parent_directory / '*.template'))
    template_files = template_files_current + template_files_parent
    if template_files:
        inps.custom_template_file = template_files[0]
    else:
        raise FileNotFoundError("No file found ending with *template")

    inps.out_dir = inps.burst_dir_path
    inps.num_data = 1
    job_obj = JOB_SUBMIT(inps)  
    job_obj.write_batch_jobs(batch_file = str(run_01_burst2safe_path) )

###############################################
if __name__ == "__main__":
    main()
