#!/usr/bin/env python3
########################
# Author: Falk Amelung
# Based on unpack_SLCs.py by Sara Mirzaee
########################

"""
Unpacks SLC files into SLC directory using a two-stage parallel approach:
1. Extract archives and rename folders (parallelized via SLURM)
2. Run ISCE unpackFrame scripts (parallelized via SLURM)

This is more efficient than unpack_SLCs.py for large numbers of files.
"""

import os
import sys
import glob
import shutil
import argparse
from pathlib import Path
from minsar.objects import message_rsmas
from minsar.objects.unpack_sensors import Sensors
from minsar.utils.stack_run import CreateRun
import minsar.utils.process_utilities as putils
from minsar.job_submission import JOB_SUBMIT

##############################################################################
EXAMPLE = """

Examples:
    unpack_SLCs_parallel.py RAW_data
    unpack_SLCs_parallel.py SLC_ORIG
    unpack_SLCs_parallel.py SLC_ORIG --queue skx --walltime 0:45
"""

DESCRIPTION = (
    "Unpacks SLC files into SLC directory using parallel extraction"
)

def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE,
                 formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("slc_orig_dir", metavar="SLC_ORIG", help="path to SLC_ORIG directory")
    parser.add_argument("--queue", dest="queue", metavar="QUEUE", help="Name of queue to submit job to")
    parser.add_argument('--jobfiles', dest='write_jobs', action='store_true', help='writes the jobs corresponding to run files')
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM)", default='1:00', help='job walltime (default=1:00)')
    parser.add_argument('--extract-walltime', dest='extract_wall_time', metavar="WALLTIME (HH:MM)", default='0:30', help='walltime for extraction stage (default=0:30)')
    return parser

def cmd_line_parse(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    return inps


def main(iargs=None):
    inps = cmd_line_parse()
    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    inps.work_dir = os.getcwd()
    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    # Create Sensors object
    slc_dir = os.path.join(inps.work_dir, 'SLC')
    unpackObj = Sensors(inps.slc_orig_dir, slc_dir, remove_file='False')
    
    # Stage 1: Create and submit the extraction/rename run file
    print("\n" + "="*80)
    print("STAGE 1: Creating run file for archive extraction and renaming")
    print("="*80)
    
    extract_run_file = unpackObj.create_runfiles_only()
    extract_run_file = os.path.abspath(extract_run_file)
    print(f"Created: {extract_run_file}")
    
    # Submit extraction job
    inps.out_dir = inps.work_dir
    inps.num_data = 1
    inps.custom_template_file = None
    
    # Use shorter walltime for extraction
    if hasattr(inps, 'extract_wall_time'):
        inps.wall_time = inps.extract_wall_time
    
    job_obj = JOB_SUBMIT(inps)
    print(f"\nSubmitting extraction job...")
    job_obj.write_batch_jobs(batch_file=extract_run_file)
    job_status = job_obj.submit_batch_jobs(batch_file=extract_run_file)
    
    if not job_status:
        raise Exception('ERROR: Archive extraction job failed')
    
    print("Extraction job completed successfully!")
    
    # Stage 2: Create and submit the ISCE unpack run file
    print("\n" + "="*80)
    print("STAGE 2: Creating run file for ISCE unpackFrame processing")
    print("="*80)
    
    unpack_run_file = unpackObj.create_run_unpack()
    unpack_run_file = os.path.abspath(unpack_run_file)
    print(f"Created: {unpack_run_file}")
    
    # Reset walltime to user-specified value for unpack stage
    if hasattr(inps, 'wall_time_orig'):
        inps.wall_time = inps.wall_time_orig
    else:
        inps.wall_time = '1:00'  # default
    
    job_obj2 = JOB_SUBMIT(inps)
    print(f"\nSubmitting unpackFrame job...")
    job_obj2.write_batch_jobs(batch_file=unpack_run_file)
    job_status2 = job_obj2.submit_batch_jobs(batch_file=unpack_run_file)
    
    unpackObj.close()
    
    if not job_status2:
        raise Exception('ERROR: UnpackFrame job failed')
    
    print("UnpackFrame job completed successfully!")
    print("\n" + "="*80)
    print("All unpacking stages completed successfully!")
    print("="*80 + "\n")


###########################################################################################

if __name__ == "__main__":
    main()

