#!/usr/bin/env python3
########################
# Author: Falk Amelung
#######################

import os
import sys
import argparse
from pathlib import Path
from minsar.objects import message_rsmas
from minsar.objects.auto_defaults import PathFind
import minsar.utils.process_utilities as putils
from minsar.job_submission import JOB_SUBMIT
from minsar.objects.dataset_template import Template
import minsar.utils.process_utilities as putils

pathObj = PathFind()

DESCRIPTION = ("""Creates jobfile to run smallbaselineApp.py""")
EXAMPLE = """example:
    create_mintpy_jobfile.py $SAMPLESDIR/unittestGalapagosSenDT128.template 
"""

###########################################################################################
def create_parser():

    default_queuename = os.environ.get("QUEUENAME")
    default_walltime = "1:00:00"

    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('custom_template_file', help='template file.\n')
    parser.add_argument("--queue", type=str, default=default_queuename, help="Queue name for job submission (default: $QUEUENAME)")
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM)", default=default_walltime, help='walltime for submitting the script as a job')

    inps = parser.parse_args()    
    return inps

def main(iargs=None):

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    inps = create_parser()
    inps.work_dir = os.getcwd()

    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    # job_obj = JOB_SUBMIT(inps)
    
    # job_name = f'{inps.outdir}/{inps.outfile}'
    # job_file_name = job_name

    # mask_thresh = min_temp_coh
    # command = []
    # command.append( f'spatial_filter.py temporalCoherence.h5 -f lowpass_gaussian -p {inps.filter_par} &' )
        
    # # Join the list into a string with linefeeds
    # final_command =[ '\n'.join(command) ]
    # #final_command = [final_command_str]

    # job_obj.submit_script(job_name, job_file_name, final_command, writeOnly='True')
    # print('jobfile created: ',job_file_name + '.job')

    # Writing job files
 
    job_name = 'smallbaseline_wrapper'
    job_file_name = job_name
  
    command1 = "check_timeseries_file.bash --dir mintpy;"
    command2 = f"smallbaselineApp.py {inps.custom_template_file} --dir mintpy;"
    command3 = "create_html.py mintpy/pic;"

    with open(job_file_name, 'w') as f:
        f.write(command1 + '\n')
        # f.write(command2 + '\n')
        # f.write(command3 + '\n')

    inps.num_data = 1
    job_obj = JOB_SUBMIT(inps)
    job_obj.write_batch_jobs(batch_file=job_file_name)

    # job_obj = JOB_SUBMIT(inps)  
    # job_obj.submit_script(job_name, job_file_name, command, writeOnly='True')


    return None

###########################################################################################

if __name__ == "__main__":
    main()
