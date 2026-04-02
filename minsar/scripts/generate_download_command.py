#!/usr/bin/env python3

import os
import sys
import re
import shlex
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
    ssaraopt = shlex.split(ssaraopt_string)
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

    # create download_ssara_bash.cmd (one line per collection when multiple collections)
    raw_collections = dataset_template.options.get('ssaraopt.collectionName', '').strip("'\"")
    collection_names = [c.strip() for c in raw_collections.split(',') if c.strip()]

    if len(collection_names) > 1:
        # Build base options from ssaraopt_dict to avoid shlex.split corrupting
        # comma-containing collectionName (e.g. "TSX A, TSX B" -> stray token in output)
        def _v(k, default=''):
            return ssaraopt_dict.get(k, default).strip().strip("'\"") or default

        base_ssaraopt = [f"--relativeOrbit={_v('relativeOrbit')}"]
        if 'platform' in ssaraopt_dict:
            base_ssaraopt.append(f"--platform={_v('platform')}")
        base_ssaraopt.append(intersects_string)
        if 'beamMode' in ssaraopt_dict:
            base_ssaraopt.append(f"--beamMode={_v('beamMode')}")
        if 'beamSwath' in ssaraopt_dict:
            base_ssaraopt.append(f"--beamSwath={_v('beamSwath')}")
        if 'frame' in ssaraopt_dict:
            base_ssaraopt.append(f"--frame={_v('frame')}")
        base_ssaraopt.append(f"--start={_v('start')}")
        base_ssaraopt.append(f"--end={_v('end')}")
        base_ssaraopt.append(f"--parallel={_v('parallel') or '6'}")
        with open('download_ssara_bash.cmd', 'w') as f:
            for name in collection_names:
                opt = base_ssaraopt + [f"--collectionName='{name}'"]
                f.write(' '.join(['ssara_federated_query.bash'] + opt) + '\n')
        with open('download_ssara_python.cmd', 'w') as f:
            for name in collection_names:
                opt = base_ssaraopt + [f"--collectionName='{name}'"]
                f.write(' '.join(['ssara_federated_query.py'] + opt + ['--maxResults=20000', '--asfResponseTimeout=300', '--kml', '--print', '--download']) + '\n')
    else:
        ssara_slc_download_cmd_bash = ['ssara_federated_query.bash'] + ssaraopt
        ssara_slc_download_cmd_python = ['ssara_federated_query.py'] + ssaraopt + ['--maxResults=20000', '--asfResponseTimeout=300', '--kml', '--print', '--download']
        with open('download_ssara_bash.cmd', 'w') as f:
            f.write(' '.join(ssara_slc_download_cmd_bash) + '\n')
        with open('download_ssara_python.cmd', 'w') as f:
            f.write(' '.join(ssara_slc_download_cmd_python) + '\n')

    # create download_slc.sh (slc method)
    asf_slc_download_cmd = ['asf_search_args.py', '--processingLevel=SLC'] + ssaraopt + ['--dir=SLC', '--print', '--download']
    with open('download_slc.sh', 'w') as f:
        asf_slc_download_cmd = [arg for arg in asf_slc_download_cmd if arg != '--print']
        f.write(f"#!/usr/bin/env bash\n")
        f.write(' '.join(['asf_download.sh'] + asf_slc_download_cmd[1:]) + '\n')
        f.write(f"check_download.py $PWD/SLC --delete\n")
        f.write(' '.join(['asf_download.sh'] + asf_slc_download_cmd[1:]) + '\n')
    #with open('download_slc.cmd', 'w') as f:
    #    f.write(' '.join(asf_slc_download_cmd) + '\n')

    # create download_burst2safe.sh (burst2safe method: download only, listing + two download runs)
    asf_burst_download_opts = ['--processingLevel=BURST'] + ssaraopt + ['--dir=SLC']
    rel_orbit = dataset_template.options.get('ssaraopt.relativeOrbit', '')
    start_date = _to_iso_date(dataset_template.options.get('ssaraopt.startDate', '2000-01-01'))
    end_date = _to_iso_date(dataset_template.options.get('ssaraopt.endDate', '2099-12-31'))
    extent_args = ' '.join(str(x) for x in extent_list)  # W S E N (lon lat lon lat)
    with open('download_burst2safe.sh', 'w') as f:
        f.write(f"#!/usr/bin/env bash\n")
        f.write(f"mkdir -p SLC\n")
        f.write(f"set -e\n")
        f.write(' '.join(['asf_download.sh'] + asf_burst_download_opts + ['--print', '>SLC/asf_burst_listing.txt']) + '\n')
        f.write(' '.join(['asf_download.sh'] + asf_burst_download_opts + ['--download', '2>burst2safe_download1.e']) + '\n')
        f.write(' '.join(['asf_download.sh'] + asf_burst_download_opts + ['--download', '2>burst2safe_download2.e']) + '\n')

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

    # create burst2stack_cmd.sh (burst2stack single-command; used by burst_download.bash)
    with open('burst2stack_cmd.sh', 'w') as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("set -e\n")
        f.write("mkdir -p SLC\n")
        f.write("cd SLC\n")
        f.write("burst2stack --rel-orbit " + str(rel_orbit) + " --start-date " + start_date + " --end-date " + end_date + " --extent " + extent_args + "\n")
        f.write("cd -\n")
    os.chmod('burst2stack_cmd.sh', 0o755)

    # create download_burst2stack.sh (burst_download.bash for burst2stack / standalone mode)
    polygon_val = ssaraopt_dict.get('intersectsWith', '').strip("'\"")
    if not polygon_val:
        # intersects_string from generate_intersects_string: --intersectsWith='Polygon(...)'
        match = re.search(r"--intersectsWith=['\"]([^'\"]+)['\"]", str(intersects_string))
        if match:
            polygon_val = match.group(1)
    burst_download_cmd = (
        f"burst_download.bash --relativeOrbit {rel_orbit} "
        f"--intersectsWith='{polygon_val}' "
        f"--start-date {start_date} --end-date {end_date} "
        f"--dir SLC"
    )
    with open('download_burst2stack.sh', 'w') as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("set -e\n")
        f.write(burst_download_cmd + "\n")
    os.chmod('download_burst2stack.sh', 0o755)

    os.chmod('download_slc.sh', 0o755)
    os.chmod('download_burst2safe.sh', 0o755)
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
