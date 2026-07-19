#!/usr/bin/env python3
########################
# Author: Falk Amelung
#######################

import os
import sys
import argparse
from pathlib import Path


DESCRIPTION = ("""Creates jobfile to run smallbaselineApp.py""")
EXAMPLE = """example:
    create_mintpy_jobfile.py $SAMPLESDIR/unittestGalapagosSenDT128.template mintpy
"""


###########################################################################################
def create_parser(iargs=None):

    default_queuename = os.environ.get("QUEUENAME")

    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('custom_template_file', help='template file\n')
    parser.add_argument('processing_dir', help='Processing directory')

    parser.add_argument("--queue", dest="queue", metavar="QUEUE", default=default_queuename, help="Name of queue to submit job to")
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM:SS)", help='walltime for submitting the script as a job')

    inps = parser.parse_args(args=iargs)
    return inps


def effective_template_for_job(custom_template_file, processing_dir):
    """Return template path for smallbaselineApp; inject mintpy.plot if $TE omits it.

    If the custom template already sets mintpy.plot to yes/no, use it as-is.
    Otherwise write ``{processing_dir}/.minsar_mintpy_template.template`` with
    ``mintpy.plot`` from the ssaraopt span rule (does not rewrite $TE).
    """
    from minsar.utils.mintpy_plot_policy import (
        apply_mintpy_plot_line,
        mintpy_plot_from_ssaraopt_span,
        read_template_option,
        template_has_explicit_mintpy_plot,
    )

    custom_path = Path(custom_template_file)
    content = custom_path.read_text()
    if template_has_explicit_mintpy_plot(content):
        return str(custom_path)

    start = read_template_option(content, "ssaraopt.startDate")
    end = read_template_option(content, "ssaraopt.endDate")
    plot_val = mintpy_plot_from_ssaraopt_span(start, end)
    proc = Path(processing_dir)
    proc.mkdir(parents=True, exist_ok=True)
    out = proc / ".minsar_mintpy_template.template"
    out.write_text(apply_mintpy_plot_line(content, plot_val))
    print(
        f"WARNING: {custom_path} omits mintpy.plot; "
        f"using mintpy.plot = {plot_val} from ssaraopt span in {out}",
        file=sys.stderr,
    )
    return str(out)


def build_job_commands(template_file, processing_dir):
    """Build shell command lines for the smallbaseline_wrapper job body."""
    command = []
    command.append(f"check_timeseries_file.bash --dir {processing_dir}")
    command.append(f"smallbaselineApp.py {template_file} --dir {processing_dir}")
    # Summary PNGs only when MintPy full plotting is OFF (runtime check of smallbaselineApp.cfg)
    command.append('# Summary PNGs only when MintPy full plotting is OFF')
    command.append(
        f"plot_val=$(awk -F= '/^[[:space:]]*mintpy\\.plot[[:space:]]*=/ {{"
        f" gsub(/[[:space:]]/, \"\", $2); print tolower($2); exit"
        f" }}' {processing_dir}/smallbaselineApp.cfg)"
    )
    command.append(
        'if [[ "$plot_val" == "no" || "$plot_val" == "false" || "$plot_val" == "0" ]]; then\n'
        f'  plot_mintpy_summary_pngs.py --dir {processing_dir} -t smallbaselineApp.cfg\n'
        'fi'
    )
    command.append(f"create_html.py {processing_dir}/pic")
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

    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    template_for_job = effective_template_for_job(
        inps.custom_template_file,
        inps.processing_dir,
    )
    command = build_job_commands(template_for_job, inps.processing_dir)

    # Join the list into a string with linefeeds
    final_command = ['\n'.join(command)]

    # create job file
    job_name = 'smallbaseline_wrapper'
    job_file_name = job_name

    inps.num_data = 1
    job_obj = JOB_SUBMIT(inps)
    job_obj.get_memory_walltime(job_name="smallbaseline_wrapper", job_type='script')
    job_obj.submit_script(job_name, job_file_name, final_command, writeOnly='True')
    print('jobfile created: ', job_file_name + '.job')

    return


###########################################################################################

if __name__ == "__main__":
    main()
