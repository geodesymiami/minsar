#!/usr/bin/env python3
########################
# Author: Falk Amelung
#######################

import os
import sys
import argparse
from pathlib import Path


DESCRIPTION = ("""Creates jobfile to export MiaplPy network products to HDF-EOS5 (radar coordinates).""")
EXAMPLE = """Examples:
create_save_hdfeos5_jobfile.py $SAMPLESDIR/unittestGalapagosSenDT128.template miaplpy_SN_201606_201608/network_single_reference
create_save_hdfeos5_jobfile.py $SAMPLESDIR/unittestGalapagosSenDT128.template miaplpy_SN_201606_201608/network_single_reference --queue skx-dev
"""

###########################################################################################
def create_parser(iargs=None):

    default_queuename = os.environ.get("QUEUENAME")

    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('custom_template_file', help='template file\n')
    parser.add_argument('processing_dir', default=None, help='miaplpy network_* directory with data for hdf5 file\n')
    parser.add_argument("--queue", dest="queue", metavar="QUEUE", default=default_queuename, help="Name of queue to submit job to")
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM:SS)", help='walltime for submitting the script as a job')
    parser.add_argument('--filter', dest='filter_par', type=float, default=0.7, help='Set the filtering parameter (default: 0.7)')
    parser.add_argument('--no-filter', dest='filter_par', action='store_const', const=None, help='Disable filtering')
    parser.add_argument('--outdir', dest='outdir', type=str, default=os.getcwd(), help='Output directory (Default: current directory.)')
    parser.add_argument('--outfile', dest='outfile', type=str, default='save_hdfeos5_radar', help='job file name (Default: save_hdfeos5_radar')

    inps = parser.parse_args(args=iargs)
    return inps


def get_network_prefix(network_dir):
    network_name = network_dir.split('network_')[1]
    if 'delaunay_4' in network_name:
        prefix = 'Del4'
    elif 'single_reference' in network_name:
        prefix = 'Sing'
    elif 'sequential_1' in network_name:
        prefix = 'Seq1'
    elif 'sequential_2' in network_name:
        prefix = 'Seq2'
    elif 'sequential_3' in network_name:
        prefix = 'Seq3'
    elif 'sequential_4' in network_name:
        prefix = 'Seq4'
    elif 'sequential_5' in network_name:
        prefix = 'Seq5'
    elif 'sequential_6' in network_name:
        prefix = 'Seq6'
    elif 'sequential_8' in network_name:
        prefix = 'Seq8'
    elif 'mini_stacks' in network_name:
        prefix = 'Mini'
    else:
        raise Exception("USER ERROR: network name not recognized")

    return prefix


def build_job_commands(processing_dir, prefix, filter_par, mask_thresh):
    """Build shell command lines for the save_hdfeos5_radar job body."""
    command = [f'cd {processing_dir}']

    save_cmd = f'save_miaplpy_hdfeos5.bash -t smallbaselineApp.cfg --prefix {prefix} --mask-thresh {mask_thresh}'
    if filter_par is None:
        save_cmd += ' --no-filter'
    else:
        save_cmd += f' --filter {filter_par}'
    command.append(save_cmd)

    # Summary PNGs only when MintPy full plotting is OFF (runtime check of smallbaselineApp.cfg)
    command.append('# Summary PNGs only when MintPy full plotting is OFF')
    command.append(
        "plot_val=$(awk -F= '/^[[:space:]]*mintpy\\.plot[[:space:]]*=/ {"
        " gsub(/[[:space:]]/, \"\", $2); print tolower($2); exit"
        " }' smallbaselineApp.cfg)"
    )
    command.append(
        'if [[ "$plot_val" == "no" || "$plot_val" == "false" || "$plot_val" == "0" ]]; then\n'
        '  plot_mintpy_summary_pngs.py --dir . -t smallbaselineApp.cfg\n'
        'fi'
    )
    return command


def main(iargs=None):

    if iargs is not None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1:]

    inps = create_parser(input_arguments)
    inps.work_dir = os.getcwd()

    from minsar.objects import message_rsmas
    from minsar.job_submission import JOB_SUBMIT
    from minsar.objects.dataset_template import Template

    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    dataset_template = Template(inps.custom_template_file)

    try:
        min_temp_coh = dataset_template.get_options()['mintpy.networkInversion.minTempCoh']
    except Exception:
        min_temp_coh = 0.7

    inps.prefix = 'tops'   # in create_runfiles.py it was just there

    path_obj = Path(inps.processing_dir)
    network_dir = path_obj.name

    prefix = get_network_prefix(network_dir)

    processing_dir = inps.work_dir + '/' + inps.processing_dir
    processing_dir = processing_dir.rstrip(os.path.sep)

    job_name = f'{inps.outdir}/{inps.outfile}'
    job_file_name = job_name

    mask_thresh = min_temp_coh
    command = build_job_commands(processing_dir, prefix, inps.filter_par, mask_thresh)
    final_command = ['\n'.join(command)]

    # create job file
    inps.num_data = 1
    job_obj = JOB_SUBMIT(inps)
    job_obj.get_memory_walltime(job_name="save_hdfeos5_radar", job_type='script')
    job_obj.submit_script(job_name, job_file_name, final_command, writeOnly='True')
    print('jobfile created: ', job_file_name + '.job')

    return

###########################################################################################


if __name__ == "__main__":
    main()
