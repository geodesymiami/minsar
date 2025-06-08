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
    create_mintpy_jobfile.py $SAMPLESDIR/unittestGalapagosSenDT128.template mintpy
"""

###########################################################################################
def create_parser():

    default_queuename = os.environ.get("QUEUENAME")

    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('custom_template_file', help='template file\n')
    parser.add_argument('processing_dir', help='Processing directory')

    parser.add_argument("--queue", dest="queue", metavar="QUEUE", default=default_queuename, help="Name of queue to submit job to")
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM:SS)", help='walltime for submitting the script as a job')

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
 
    command = []
    command.append( "check_timeseries_file.bash --dir mintpy")
    command.append( f"smallbaselineApp.py {inps.custom_template_file} --dir {inps.processing_dir}" )
    command.append( "create_html.py mintpy/pic" )

    # Join the list into a string with linefeeds
    final_command =[ '\n'.join(command) ]

    # create job file
    job_name = 'smallbaseline_wrapper'
    job_file_name = job_name
    
    inps.num_data = 1
    job_obj= JOB_SUBMIT(inps)
    job_obj.get_memory_walltime(job_name="smallbaseline_wrapper", job_type='script')
    job_obj.submit_script(job_name, job_file_name, final_command, writeOnly='True')
    print('jobfile created: ',job_file_name + '.job')

    return 

###########################################################################################

if __name__ == "__main__":
    main()
