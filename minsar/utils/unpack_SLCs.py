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
import math
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
    unpack_SLCs.py SLC_ORIG --queue skx --unpack-walltime 1:30 --uncompress-walltime 0:45
    unpack_SLCs.py SLC_ORIG --alos-stack --queue skx --jobs 5
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
    parser.add_argument('--jobs', dest='jobs', type=int, default=5, metavar='N', help='simultaneous archives to uncompress (default: 5)')
    parser.add_argument('--uncompress-walltime', dest='uncompress_wall_time', metavar='WALLTIME (HH:MM)', default=None,
                        help='uncompress walltime (default: 15 min per wave of --jobs, 30 min floor)')
    parser.add_argument('--unpack-walltime', dest='unpack_wall_time', metavar="WALLTIME (HH:MM)", default='1:00', help='walltime for unpackFrame stage (default=1:00)')
    parser.add_argument('--alos-stack', action='store_true', help='Prepare ALOS-2 L1.1 archives for ISCE2 alosStack')
    return parser

def uncompress_walltime_for(n_files, jobs):
    """15 minutes per wave of `jobs`, with a 30 minute floor. Cap at 23:59 (strptime %H)."""
    jobs = max(int(jobs), 1)
    waves = math.ceil(n_files / jobs) if n_files else 1
    minutes = max(30, 15 * waves)
    hours, mins = divmod(minutes, 60)
    if hours > 23:
        return '23:59'
    return f'{hours}:{mins:02d}'

def cmd_line_parse(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    if inps.jobs < 1:
        parser.error('--jobs must be a positive integer')
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
    if inps.alos_stack:
        os.makedirs(slc_dir, exist_ok=True)
    else:
        shutil.rmtree(slc_dir, ignore_errors=True)
    sensorsObj = Sensors(inps.slc_orig_dir, slc_dir, remove_file='False', alos_stack=inps.alos_stack)
    
    # Stage 1: Create and submit the uncompress_rename run_file
    print("\n" + "#"*60)
    print("STAGE 1: Creating run file for data uncompression and renaming")
    
    uncompress_rename_run_file = sensorsObj.create_uncompress_rename_runfile(jobs=inps.jobs)
    uncompress_rename_run_file = os.path.abspath(uncompress_rename_run_file)
    print(f"Created: {uncompress_rename_run_file}")
    
    inps.out_dir = inps.work_dir
    inps.num_data = 1
    inps.custom_template_file = None
    if inps.uncompress_wall_time:
        inps.wall_time = inps.uncompress_wall_time
    else:
        inps.wall_time = uncompress_walltime_for(len(sensorsObj.file_list), inps.jobs)
    print(f"Uncompress walltime: {inps.wall_time}  jobs: {inps.jobs}  archives: {len(sensorsObj.file_list)}")
    
    job_obj = JOB_SUBMIT(inps)
    print(f"\nSubmitting uncompress_rename job...")
    job_obj.write_batch_jobs(batch_file=uncompress_rename_run_file)
    job_status = job_obj.submit_batch_jobs(batch_file=uncompress_rename_run_file)
    
    if not job_status:
        raise Exception('ERROR: uncompress_rename job failed')
    
    print("uncompress_rename job completed successfully!")
    if inps.alos_stack:
        sensorsObj.close()
        print("ALOS-2 data are ready in YYMMDD directories; alosStack does not use unpackFrame.")
        return
    
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

