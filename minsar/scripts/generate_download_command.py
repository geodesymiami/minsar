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
    parser.add_argument('--delta-lat', dest='delta_lat', default=0.1, type=float, help='delta to add to latitude from boundingBox field, default is 0.1')
    parser.add_argument('--delta-lon', dest='delta_lon', default=0.1, type=float, help='delta to add to longitude from boundingBox field, default is 0.1')
    parser.add_argument('--seasonalStartDate', dest='seasonalStartDate', type=str,
                             help='seasonal start date to specify download dates within start and end dates, example: a seasonsal start date of January 1 would be added as --seasonalEndDate 0101')
    parser.add_argument('--seasonalEndDate', dest='seasonalEndDate', type=str,
                             help='seasonal end date to specify download dates within start and end dates, example: a seasonsal end date of December 31 would be added as --seasonalEndDate 1231')

    inps = parser.parse_args()
    inps = putils.create_or_update_template(inps)

    return inps


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
       intersects_string = putils.generate_intersects_string(dataset_template, delta_lat=inps.delta_lat, delta_lon=inps.delta_lon)
       ssaraopt.insert(2, intersects_string)

    extent_str, extent_list = putils.convert_intersects_string_to_extent_string(intersects_string)
    print(f"New intersectsWith string using delta_lat, delta_lon: {inps.delta_lat},{inps.delta_lon}: ", intersects_string)
    print(f'New extent string: ', extent_str)

    def _to_iso_date(ymd):
        """Convert YYYYMMDD to YYYY-MM-DD if needed."""
        s = str(ymd).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s

    # create download_ssara_bash.cmd
    ssara_slc_download_cmd_bash = ['ssara_federated_query.bash'] + ssaraopt
    ssara_slc_download_cmd_python = ['ssara_federated_query.py'] + ssaraopt + ['--maxResults=20000','--asfResponseTimeout=300', '--kml', '--print','--download']
    with open('download_ssara_bash.cmd', 'w') as f:
        f.write(' '.join(ssara_slc_download_cmd_bash) + '\n')
    with open('download_ssara_python.cmd', 'w') as f:
       f.write(' '.join(ssara_slc_download_cmd_python) + '\n')

    # create download_asf.sh
    asf_slc_download_cmd = ['asf_search_args.py', '--processingLevel=SLC'] + ssaraopt + ['--dir=SLC', '--print', '--download']
    with open('download_asf.sh', 'w') as f:
        asf_slc_download_cmd = [arg for arg in asf_slc_download_cmd if arg != '--print']
        f.write(f"#!/usr/bin/env bash\n")
        f.write(' '.join(['asf_download.sh'] + asf_slc_download_cmd[1:]) + '\n')
        f.write(f"check_download.py $PWD/SLC --delete\n")
        f.write(' '.join(['asf_download.sh'] + asf_slc_download_cmd[1:]) + '\n')
    #with open('download_asf.cmd', 'w') as f:
    #    f.write(' '.join(asf_slc_download_cmd) + '\n')

    # create download_asf_burst.sh (download only: listing + two download runs)
    asf_burst_download_opts = ['--processingLevel=BURST'] + ssaraopt + ['--dir=SLC']
    rel_orbit = dataset_template.options.get('ssaraopt.relativeOrbit', '')
    start_date = _to_iso_date(dataset_template.options.get('ssaraopt.startDate', '2000-01-01'))
    end_date = _to_iso_date(dataset_template.options.get('ssaraopt.endDate', '2099-12-31'))
    extent_args = ' '.join(str(x) for x in extent_list)  # W S E N (lon lat lon lat)
    with open('download_asf_burst.sh', 'w') as f:
        f.write(f"#!/usr/bin/env bash\n")
        f.write(f"mkdir -p SLC\n")
        f.write(f"set -e\n")
        f.write(' '.join(['asf_download.sh'] + asf_burst_download_opts + ['--print', '>SLC/asf_burst_listing.txt']) + '\n')
        f.write(' '.join(['asf_download.sh'] + asf_burst_download_opts + ['--download', '2>asf_burst_download1.e']) + '\n')
        f.write(' '.join(['asf_download.sh'] + asf_burst_download_opts + ['--download', '2>asf_burst_download2.e']) + '\n')

    # create pack_bursts.sh (burst2safe jobfile, run_workflow, check, rerun timeouts)
    with open('pack_bursts.sh', 'w') as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("set -e\n")
        f.write(' '.join(['bursts_to_burst2safe_jobfile.py', 'SLC']) + '\n')
        f.write(' '.join(['run_workflow.bash', '--jobfile', f'{inps.work_dir}/SLC/run_01_burst2safe', '--no-check-job-outputs']) + '\n')
        f.write(' '.join(['check_burst2safe_job_outputs.py', 'SLC']) + '\n')
        f.write("if [[ -s SLC/run_01_burst2safe_timeout_0 ]]; then\n")
        f.write("    rerun_burst2safe.sh SLC/run_01_burst2safe_timeout_0.job\n")
        f.write("fi\n")
        f.write("# Need to convert to scripts/pack_bursts.bash SLC\n")

    # create download_asf_burst2stack.sh (burst2stack command only)
    with open('download_asf_burst2stack.sh', 'w') as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("set -e\n")
        f.write("mkdir -p SLC\n")
        f.write("cd SLC\n")
        f.write("burst2stack --rel-orbit " + str(rel_orbit) + " --start-date " + start_date + " --end-date " + end_date + " --extent " + extent_args + "\n")
        f.write("cd -\n")
    os.chmod('download_asf_burst2stack.sh', 0o755)

    os.chmod('download_asf.sh', 0o755)
    os.chmod('download_asf_burst.sh', 0o755)
    os.chmod('pack_bursts.sh', 0o755)

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
