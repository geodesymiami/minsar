#! /usr/bin/env python3
"""Update a SLURM job file after timeout: increase walltime and optionally switch queue (config-driven)."""
import argparse
import os
import sys

import minsar.utils.process_utilities as putils


def main(iargs=None):
    parser = argparse.ArgumentParser(description='Update job file walltime (and optionally queue) for timeout rerun.')
    parser.add_argument('job_file_name', help='The job file that failed with a timeout error.')
    inps = parser.parse_args(args=iargs)

    if not os.path.isfile(inps.job_file_name):
        print('Error: job file not found: {}'.format(inps.job_file_name), file=sys.stderr)
        sys.exit(1)

    new_walltime, new_queue = putils.compute_rerun_walltime_and_queue(inps.job_file_name)
    putils.replace_walltime_in_job_file(inps.job_file_name, new_walltime)
    if new_queue is not None:
        putils.replace_queuename_in_job_file(inps.job_file_name, new_queue)


if __name__ == '__main__':
    main()
