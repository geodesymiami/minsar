#!/usr/bin/env python3
########################
# Author: Sara Mirzaee
#######################

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
from minsar.objects.unpack_sensors import Sensors

# pathObj = PathFind()

##############################################################################
EXAMPLE = """

Examples:
    unpack_SLCs.py RAW_data
    unpack_SLCs.py SLC_ORIG
    unpack_SLCs.py SLC_ORIG --queue skx --walltime 0:45
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
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM)", default='1:00', help='job walltime (default=1:00)')
    return parser

def cmd_line_parse(iargs=None):

    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    # inps.mintpy_flag = False
    # if inps.data_dirs:
    #     if 'mintpy' in inps.data_dirs[0]:
    #         inps.mintpy_flag = True
    # print('inps: ',inps)
    return inps

def detect_platform(dir):

    dir_path = Path(dir)
    files = [p for p in dir_path.iterdir() if p.is_file() and p.stat().st_size > 10 * 1024 * 1024]
    # print ('files: ',files)  
    file = files[0].name
    print ('file: ',file)

    if file.startswith('CSK'):
        platform = 'COSMO_SKYMED'
    elif file.startswith('TSX'):
        platform = 'TERRASAR-X'
    elif file.startswith('ASA_'):
        platform = 'ENVISAT'
    else:
        raise Exception(f'Cannot detect platform for file {file}.')

    return platform

    ###########################################################################################
def main(iargs=None):
    inps = cmd_line_parse()
    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    inps.work_dir = os.getcwd()
    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    platform = detect_platform(inps.slc_orig_dir)
    slc_dir = os.path.join(inps.work_dir, 'SLC')
    # unpackObj = Sensors(inps.slc_orig_dir, slc_dir, remove_file='False',
    #                         multiple_raw_frame=inps.template['multiple_raw_frame'])
    unpackObj = Sensors(inps.slc_orig_dir, slc_dir, remove_file='False')
    unpack_run_file = unpackObj.start()
    unpackObj.close()

    unpack_run_file = os.path.abspath( os.path.join(inps.work_dir, unpack_run_file))
    inps.out_dir = inps.work_dir
    inps.num_data = 1
    job_obj = JOB_SUBMIT(inps)  
    job_obj.write_batch_jobs(batch_file=unpack_run_file)
    job_status = job_obj.submit_batch_jobs(batch_file=unpack_run_file)

    if not job_status:
        raise Exception('ERROR: Unpacking was failed')


###########################################################################################

if __name__ == "__main__":
    main()
