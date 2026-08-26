#!/usr/bin/env python3
"""Write horzvert_timeseries.job for a script-style run file via JOB_SUBMIT."""

from __future__ import annotations

import argparse
import os
import shlex
import sys

from minsar.job_submission import JOB_SUBMIT

EXAMPLE = """Examples:
create_horzvert_runfile_job.py --from-file run_horzvert2timeseries
create_horzvert_runfile_job.py --from-file run_horzvert2timeseries --queue skx
"""


def create_parser():
    parser = argparse.ArgumentParser(
        description="Create horzvert_timeseries.job (job_submission.py) for a run file.",
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--from-file",
        required=True,
        metavar="RUNFILE",
        help="Script-style run file (job body: bash RUNFILE)",
    )
    parser.add_argument(
        "--job-name",
        default="horzvert_timeseries",
        help="SLURM job name and .job basename (default: horzvert_timeseries)",
    )
    parser.add_argument(
        "--queue",
        default=os.getenv("QUEUENAME"),
        help="Queue (default: $QUEUENAME)",
    )
    parser.add_argument(
        "--walltime",
        dest="wall_time",
        default=None,
        metavar="HH:MM[:SS]",
        help="Walltime override (default: job_defaults.cfg)",
    )
    return parser


def write_runfile_job(from_file, job_name="horzvert_timeseries", queue=None, wall_time=None, work_dir=None):
    """Write <job_name>.job in work_dir. Return absolute job path."""
    run_file = os.path.abspath(from_file)
    if not os.path.isfile(run_file):
        raise FileNotFoundError(run_file)

    work_dir = os.path.abspath(work_dir or os.getcwd())
    inps = argparse.Namespace(
        work_dir=work_dir,
        num_data=1,
        queue=queue or os.getenv("QUEUENAME"),
        wall_time=wall_time,
    )
    job_obj = JOB_SUBMIT(inps)
    command = f"bash {shlex.quote(run_file)}"
    job_obj.submit_script(job_name, job_name, [command], writeOnly="True")
    return os.path.join(work_dir, f"{job_name}.job")


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        job_path = write_runfile_job(
            inps.from_file,
            job_name=inps.job_name,
            queue=inps.queue,
            wall_time=inps.wall_time,
        )
    except FileNotFoundError as exc:
        print(f"Error: --from-file not found: {exc}", file=sys.stderr)
        return 1
    print(f"jobfile created: {os.path.basename(job_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
