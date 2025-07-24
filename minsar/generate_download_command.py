#!/usr/bin/env python3

import os
import sys
import re
import argparse
from minsar.objects.dataset_template import Template
from minsar.objects import message_rsmas
from minsar.objects.auto_defaults import PathFind
from minsar.utils import process_utilities as putils

pathObj = PathFind()
inps = None

##############################################################################
EXAMPLE = """example:
    generate_download_command.py $TE/GalapagosSenDT128.template

   OPTIONS NEED TO REVISTED (they don't work)
       --delta_lat DELTA_LAT
                        delta to add to latitude from boundingBox field, default is 0.0
       --seasonalStartDate SEASONALSTARTDATE
                        seasonal start date to specify download dates within start and end dates, example: a seasonsal start date of January 1 would be added as --seasonalEndDate 0101
       --seasonalEndDate SEASONALENDDATE
                        seasonal end date to specify download dates within start and end dates, example: a seasonsal end date of December 31 would be added as --seasonalEndDate 1231
       --parallel PARALLEL   determines whether a parallel download is required with a yes/no
       --processes PROCESSES
                        specifies number of processes for the parallel download, if no value is provided then the number of processors from os.cpu_count() is used
"""

DESCRIPTION = ("""
     Creates download command download_ssara.cmd containing intersectsWith='Polygon((...))'. 
     If the string is not given in *template file, it will be created based on (in that order):
         miaplpy.subset.lalo
         mintpy.subset.lalo
         topsStack.boundingBox
""")

def create_parser():
    synopsis = 'Create download commands'
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('custom_template_file', help='custom template with option settings.\n')
    parser.add_argument('--triplets', dest='triplets_flag', action='store_true', default=True, help='uploads numTriNonzeroIntAmbiguity.h5')
    parser.add_argument('--delta_lat', dest='delta_lat', default='0.0', type=float, help='delta to add to latitude from boundingBox field, default is 0.0')
    parser.add_argument('--seasonalStartDate', dest='seasonalStartDate', type=str,
                             help='seasonal start date to specify download dates within start and end dates, example: a seasonsal start date of January 1 would be added as --seasonalEndDate 0101')
    parser.add_argument('--seasonalEndDate', dest='seasonalEndDate', type=str,
                             help='seasonal end date to specify download dates within start and end dates, example: a seasonsal end date of December 31 would be added as --seasonalEndDate 1231')

    inps = parser.parse_args()
    inps = putils.create_or_update_template(inps)

    return inps


###############################################
def create_download_retry_bash_script(download_command, waittime=10, timeout=86400):
    # command_str = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in download_command)
    download_command = [arg for arg in download_command if arg != '--print']
    command_str=' '.join(download_command)
    script = f"""#!/usr/bin/env bash

waittime={waittime}           # seconds to wait between retries
timeout={timeout}          # total seconds before giving up
mkdir -p SLC
logfile="download.log"
> "$logfile"

echo "Starting download at $(date)" | tee -a "$logfile"
start_time=$(date +%s)

# Retry loop
while true; do
    {command_str} >> "$logfile" 2>&1
    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo "Download completed successfully." | tee -a "$logfile"
        break
    fi

    # Check for HTTP 50x errors in the log
    if grep -E -q "HTTP Error 50[0-9]|502 Server Error|502: Proxy Error|500: Internal Server Error" "$logfile"; then
        echo "Encountered server error (HTTP 50x). Retrying in $waittime seconds..." | tee -a "$logfile"
        sleep "$waittime"

        now=$(date +%s)
        elapsed=$((now - start_time))

        if [ $elapsed -ge $timeout ]; then
            echo "Repeated 50x errors. Exiting after $timeout seconds." | tee -a "$logfile"
            exit 1
        fi
    else
        echo "Download failed with non-retryable error. Exiting." | tee -a "$logfile"
        echo
        sed -n '/The above exception was the direct cause of the following exception/,$p' "$logfile"
        exit $exit_code
    fi
done
"""
    return script

###############################################
def generate_download_command(template,inps):
    """ generate ssara download options to use """

    dataset_template = Template(template)
    dataset_template.options.update(pathObj.correct_for_ssara_date_format(dataset_template.options))

    ssaraopt_string, ssaraopt_dict = dataset_template.generate_ssaraopt_string()
    ssaraopt = ssaraopt_string.split(' ')
    if 'end' not in ssaraopt_dict:
        ssaraopt_dict['end'] = '2099-12-31'

    if any(option.startswith('ssaraopt.intersectsWith') for option in dataset_template.get_options()):
       intersects_string = f"--intersectsWith={ssaraopt_dict['intersectsWith']}"
    else:
       intersects_string = putils.generate_intersects_string(dataset_template, delta_lat=0.1)
       ssaraopt.insert(2, intersects_string)
    
    extent_str, extent_list = putils.convert_intersects_string_to_extent_string(intersects_string)
    print('New intersectsWith string using delta_lat=0.1: ', intersects_string)
    print('New extent string using delta_lat=0.1: ', extent_str)

    # create download_ssara_bash.cmd
    ssara_slc_download_cmd_bash = ['ssara_federated_query.bash'] + ssaraopt 
    ssara_slc_download_cmd_python = ['ssara_federated_query.py'] + ssaraopt + ['--maxResults=20000','--asfResponseTimeout=300', '--kml', '--print','--download']
    with open('download_ssara_bash.cmd', 'w') as f:
        f.write(' '.join(ssara_slc_download_cmd_bash) + '\n')
    with open('download_ssara_python.cmd', 'w') as f:
       f.write(' '.join(ssara_slc_download_cmd_python) + '\n')

    # create download_asf.sh
    asf_slc_download_cmd = ['asf_search_args.py', '--product=SLC'] + ssaraopt + ['--dir=SLC', '--print', '--download']
    with open('download_asf.sh', 'w') as f:
        retry_script = create_download_retry_bash_script(asf_slc_download_cmd)
        f.write(' '.join(retry_script) + '\n')
    with open('download_asf.sh', 'w') as f:
        retry_script = create_download_retry_bash_script(asf_slc_download_cmd)
        f.write(' '.join(retry_script) + '\n')
    with open('download_asf.cmd', 'w') as f:
        f.write(' '.join(asf_slc_download_cmd) + '\n')

    # create download_asf_burst.sh
    asf_burst_download_cmd = ['asf_search_args.py', '--product=BURST'] + ssaraopt + ['--dir=SLC', '--print', '--download','2>asf_download.e']
    run_burst2safe = [f'run_workflow.bash {template} --jobfile {inps.work_dir}/SLC/run_01_burst2safe']
    with open('download_asf_burst.sh', 'w') as f:
        retry_script = create_download_retry_bash_script(asf_burst_download_cmd)
        f.write(' '.join(retry_script) + '\n')
        f.write(' '.join(['bursts_to_burst2safe_jobfile.py','SLC']) + '\n')
        f.write(' '.join(run_burst2safe) + '\n')
    with open('download_asf_burst.cmd', 'w') as f:
        f.write(' '.join(asf_burst_download_cmd) + '\n')
        f.write(' '.join(['bursts_to_burst2safe_jobfile.py','SLC']) + '\n')
        f.write(' '.join(run_burst2safe) + '\n')
    
    os.chmod('download_asf.sh', 0o755)
    os.chmod('download_asf_burst.sh', 0o755)

    return 
   
###############################################
def main(iargs=None):

    # parse
    inps = create_parser()

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    generate_download_command(inps.custom_template_file,inps)

    return None

###############################################
if __name__ == "__main__":
    main()
