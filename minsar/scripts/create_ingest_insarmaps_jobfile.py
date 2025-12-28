#!/usr/bin/env python3
########################
# Author: Falk Amelung
#######################

import os
import sys
import argparse
from minsar.objects import message_rsmas
from minsar.job_submission import JOB_SUBMIT

############################################################
EXAMPLE = """Examples:
    create_ingest_insarmaps_jobfile.py mintpy
    create_ingest_insarmaps_jobfile.py miaplpy/network_single_reference
    create_ingest_insarmaps_jobfile.py S1_IW1_128_20180303_XXXXXXXX__S00878_S00791_W091201_W091113.he5
    create_ingest_insarmaps_jobfile.py hvGalapagosSenD128/mintpy --ref-lalo -0.81,-91.190
    create_ingest_insarmaps_jobfile.py hvGalapagosSenD128/miaplpy/network_single_reference
    create_ingest_insarmaps_jobfile.py miaplpy/network_single_reference --dataset geo
    create_ingest_insarmaps_jobfile.py miaplpy/network_single_reference --dataset PS
    create_ingest_insarmaps_jobfile.py miaplpy/network_single_reference --dataset filt*DS
    create_ingest_insarmaps_jobfile.py miaplpy/network_single_reference --dataset PS,DS
    create_ingest_insarmaps_jobfile.py miaplpy/network_single_reference --dataset PS,DS,filt*DS
    
    # Additional examples with SLURM options:
    create_ingest_insarmaps_jobfile.py miaplpy_SN_201606_201608/network_single_reference --dataset PS --queue skx --walltime 0:45
"""
###########################################################################################
def create_parser():
    synopsis = 'Create jobfile for ingestion into insarmaps on server(s) given by INSARMAPSHOST on queue given by QUEUENAME'
    epilog = EXAMPLE
    parser = argparse.ArgumentParser(description=synopsis, epilog=epilog, formatter_class=argparse.RawTextHelpFormatter)
    
    # Positional argument
    parser.add_argument('input_path', nargs=1, help='Directory with hdf5eos file or path to specific .he5 file.\n')
    
    # Options from ingest_insarmaps.bash
    parser.add_argument('--ref-lalo', dest='ref_lalo', nargs='+', 
                        help='Reference point (lat,lon or lat lon)')
    parser.add_argument('--dataset', dest='dataset', type=str,
                        default='geo', 
                        help='Dataset to upload (default: %(default)s). Options: {PS,DS,filtDS,filt*DS,geo} or comma-separated {PS,DS,filt*DS}. '
                             'Use comma-separated values to ingest multiple types: --dataset PS,DS or --dataset PS,DS,filt*DS')
    parser.add_argument('--debug', dest='debug', action='store_true',
                        help='Enable debug mode (set -x)')
    
    # SLURM job options (from create_insarmaps_jobfile.py)
    parser.add_argument("--queue", dest="queue", metavar="QUEUE", 
                        default=os.getenv('QUEUENAME'), 
                        help="Name of queue to submit job to")
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM)", 
                        default='1:00', 
                        help='job walltime (default=1:00)')
   
    inps = parser.parse_args()
    return inps

def main(iargs=None):
    
    inps = create_parser()
    inps.work_dir = os.getcwd()

    input_arguments = sys.argv[1::]
    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    # Set default values for JOB_SUBMIT
    inps.num_data = 1
    
    job_obj = JOB_SUBMIT(inps)

    job_name = f"ingest_insarmaps"
    job_file_name = job_name
    
    command_parts = ['ingest_insarmaps.bash', inps.input_path[0]]
    
    # Add optional arguments
    if inps.ref_lalo:
        command_parts.append('--ref-lalo')
        if len(inps.ref_lalo) == 1:
            # Single argument like "lat,lon"
            command_parts.append(inps.ref_lalo[0])
        else:
            # Two arguments like lat lon
            command_parts.extend(inps.ref_lalo[:2])
    
    if inps.dataset:
        command_parts.extend(['--dataset', inps.dataset])
    
    if inps.debug:
        command_parts.append('--debug')
    
    final_command = [' '.join(command_parts)]
    
    # Write the jobfile (don't submit)
    job_obj.submit_script(job_name, job_file_name, final_command, writeOnly='True')
    print('jobfile created: ', job_file_name + '.job')

    return None

###########################################################################################

if __name__ == "__main__":
    main()


