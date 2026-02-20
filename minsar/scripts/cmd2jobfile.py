#!/usr/bin/env python3
"""
Create a SLURM jobfile from a script file or a command line.
Uses QUEUENAME and job_defaults.cfg (via JOB_SUBMIT). No launcher.
"""

import os
import sys
import argparse
import subprocess
import shutil
from pathlib import Path

from minsar.objects import message_rsmas
from minsar.job_submission import JOB_SUBMIT

EXAMPLE = """Examples:
  cmd2jobfile.py download_asf_burst2stack.sh
  cmd2jobfile.py download_asf_burst2stack.sh --submit
  cmd2jobfile.py download_asf_burst.sh --background
  cmd2jobfile.py -- my_command arg1 arg2
  cmd2jobfile.py my_script.sh --queue icx --walltime 0:30:00
"""


def create_parser():
    parser = argparse.ArgumentParser(
        description='Create a SLURM .job file from a script file or command. '
                    'Uses QUEUENAME and job_defaults.cfg.',
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        'args',
        nargs='+',
        metavar='FILE_OR_CMD',
        help='Path to a script file (single arg) or command + args (multiple).',
    )
    parser.add_argument(
        '--queue', '-q',
        dest='queue',
        default=os.getenv('QUEUENAME'),
        help='Queue name (default: QUEUENAME env).',
    )
    parser.add_argument(
        '--walltime', '-t',
        dest='wall_time',
        metavar='HH:MM or HH:MM:SS',
        default=None,
        help='Job walltime (default: from job_defaults.cfg).',
    )
    parser.add_argument(
        '--submit', '-s',
        dest='submit',
        action='store_true',
        help='Submit after creating the jobfile (foreground: run_workflow.bash).',
    )
    parser.add_argument(
        '--background', '-b',
        dest='background',
        action='store_true',
        help='Submit via sbatch (background). Implies submit. Use alone or with --submit.',
    )
    return parser.parse_args()


def find_run_workflow_bash():
    """Resolve run_workflow.bash from PATH or RSMASINSAR_HOME/MINSAR_HOME."""
    path = shutil.which('run_workflow.bash')
    if path:
        return os.path.abspath(path)
    for env in ('RSMASINSAR_HOME', 'MINSAR_HOME'):
        base = os.environ.get(env)
        if base:
            p = os.path.join(base, 'minsar', 'bin', 'run_workflow.bash')
            if os.path.isfile(p):
                return os.path.abspath(p)
    return None


def main(iargs=None):
    if iargs is not None:
        sys.argv = [sys.argv[0]] + iargs
    inps = create_parser()
    inps.work_dir = os.getcwd()
    inps.num_data = 1

    args = inps.args
    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(args))

    # File mode: single existing file -> job name from basename, body = file contents
    if len(args) == 1 and os.path.isfile(args[0]):
        path = Path(args[0])
        job_name = path.stem
        body = path.read_text()
        # Strip leading shebang so job file stays clean
        if body.startswith('#!'):
            first_newline = body.find('\n')
            if first_newline != -1:
                body = body[first_newline + 1:].lstrip('\n')
            else:
                body = ''
    else:
        # Command mode: all args form one command line
        job_name = args[0] if args else 'cmd2job'
        body = ' '.join(args)

    job_obj = JOB_SUBMIT(inps)
    job_obj.get_memory_walltime(job_name, job_type='script')
    job_obj.submit_script(job_name, job_name, [body], writeOnly='True')

    job_file_path = os.path.join(inps.work_dir, job_name + '.job')
    job_file_abs = os.path.abspath(job_file_path)
    job_file_basename = os.path.basename(job_file_path)
    print('jobfile created:', job_name + '.job')
    do_submit = inps.submit or inps.background
    if not do_submit:
        print('To run: run_workflow.bash --jobfile', job_file_abs)
    elif inps.background:
        pass  # sbatch output will follow
    else:
        print('Running..... run_workflow.bash --jobfile', job_file_basename)

    if do_submit:
        if inps.background:
            try:
                result = subprocess.run(
                    ['sbatch', job_file_path],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                print('Job submitted:', result.stdout.strip())
            except subprocess.CalledProcessError as e:
                print('Error submitting job:', e.stderr, file=sys.stderr)
                return 1
            except FileNotFoundError:
                print('Error: sbatch not found. Are you on a SLURM cluster?', file=sys.stderr)
                return 1
        else:
            run_workflow_bash = find_run_workflow_bash()
            if not run_workflow_bash:
                print('Error: run_workflow.bash not found in PATH or RSMASINSAR_HOME/MINSAR_HOME.', file=sys.stderr)
                return 1
            # Exec the shell to run the script (kernel cannot exec a .bash script directly)
            argv = ['bash', run_workflow_bash, '--jobfile', job_file_abs]
            os.execv('/bin/bash', argv)
            # execv does not return on success

    return None


if __name__ == '__main__':
    sys.exit(main() or 0)
