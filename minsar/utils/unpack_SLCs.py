#!/usr/bin/env python3
########################
# Author: Falk Amelung
########################

"""
Unpacks SLC files into SLC directory using a two-stage approach:
1. Extract archives and rename folders (parallelized via SLURM)
2. Run ISCE unpackFrame scripts (parallelized via SLURM)
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
    unpack_SLCs.py RAW_data
    unpack_SLCs.py SLC_ORIG
    unpack_SLCs.py SLC_ORIG --queue skx --unpack-walltime 1:30 --extract-walltime 0:45
"""

DESCRIPTION = (
    "Unpacks SLC files into SLC directory"
)

def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE,
                 formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("slc_orig_dir", metavar="SLC_ORIG", help="path to SLC_ORIG directory")
    parser.add_argument("--queue", dest="queue", metavar="QUEUE", help="Name of queue to submit job to")
    parser.add_argument('--jobfiles', dest='write_jobs', action='store_true', help='writes the jobs corresponding to run files')
    parser.add_argument('--extract-walltime', dest='extract_wall_time', metavar="WALLTIME (HH:MM)", default='0:30', help='walltime for extraction stage (default=0:30)')
    parser.add_argument('--unpack-walltime', dest='unpack_wall_time', metavar="WALLTIME (HH:MM)", default='1:00', help='walltime for unpackFrame stage (default=1:00)')
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
    shutil.rmtree(slc_dir, ignore_errors=True)
    sensorsObj = Sensors(inps.slc_orig_dir, slc_dir, remove_file='False')
    
    # Stage 1: Create and submit the uncompress_rename run_file
    print("\n" + "#"*60)
    print("STAGE 1: Creating run file for data uncompression and renaming")
    
    uncompress_rename_run_file = sensorsObj.create_uncompress_rename_runfile()
    uncompress_rename_run_file = os.path.abspath(uncompress_rename_run_file)
    print(f"Created: {uncompress_rename_run_file}")
    
    inps.out_dir = inps.work_dir
    inps.num_data = 1
    inps.custom_template_file = None    
    if hasattr(inps, 'extract_wall_time'):
        inps.wall_time = inps.extract_wall_time
    
    job_obj = JOB_SUBMIT(inps)
    print(f"\nSubmitting uncompress_rename job...")
    job_obj.write_batch_jobs(batch_file=uncompress_rename_run_file)
    job_status = job_obj.submit_batch_jobs(batch_file=uncompress_rename_run_file)
    
    if not job_status:
        raise Exception('ERROR: uncompress_rename job failed')
    
    print("uncompress_rename job completed successfully!")
    
    # Stage 2: Create and submit the unpackFrame run file
    print("\n" + "#"*60)
    print("STAGE 2: Creating run file for ISCE unpackFrame processing")
    
    unpackFrame_run_file = sensorsObj.create_run_unpackFrame()
    unpackFrame_run_file = os.path.abspath(unpackFrame_run_file)
    print(f"Created: {unpackFrame_run_file}")
    
    if hasattr(inps, 'unpack_wall_time'):
        inps.wall_time = inps.unpack_wall_time
    else:
        inps.wall_time = '1:00'  # default
    
    job_obj2 = JOB_SUBMIT(inps)
    print(f"\nSubmitting unpackFrame job...")
    job_obj2.write_batch_jobs(batch_file=unpackFrame_run_file)
    job_status2 = job_obj2.submit_batch_jobs(batch_file=unpackFrame_run_file)
    
    sensorsObj.close()
    
    if not job_status2:
        raise Exception('ERROR: unpackFrame job failed')
    
    print("unpackFrame job completed successfully!")


###########################################################################################

if __name__ == "__main__":
    main()

