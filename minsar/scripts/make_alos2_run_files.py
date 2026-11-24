#!/usr/bin/env python3
"""Write MinSAR run files for an alosStack directory with ionosphere turned off."""

import argparse
import sys
from pathlib import Path

from minsar.utils.alos2_run_files import plan_alos2_run_files, write_alos2_run_files

DESCRIPTION = "Write run_01..run_16 from alosStack cmd_1.sh, cmd_2.sh, and cmd_4.sh."
EXAMPLE = """
Examples:
    make_alos2_run_files.py alos2_cmds
    make_alos2_run_files.py --dry-run /path/project/alos2_cmds
    make_alos2_run_files.py --unw-method snaphu alos2_cmds
"""


def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("alos2_cmds", metavar="ALOS2_CMDS", help="directory that contains cmd_1.sh, cmd_2.sh, and cmd_4.sh")
    parser.add_argument("--work-dir", type=Path, help="project directory (default: parent of ALOS2_CMDS)")
    parser.add_argument("--out-dir", type=Path, help="run_files directory (default: WORK/run_files)")
    parser.add_argument("--unw-method", default="whirlwind", choices=["snaphu", "whirlwind"], help="unwrapper for run_15_unwrap (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="print run-file names and line counts and do not write")
    return parser


def main(argv=None):
    args = create_parser().parse_args(argv)
    alos2_cmds = Path(args.alos2_cmds)
    if not alos2_cmds.is_dir():
        print(f"ERROR: directory not found: {alos2_cmds}", file=sys.stderr)
        return 1
    work_dir = args.work_dir if args.work_dir is not None else alos2_cmds.parent
    run_dir = args.out_dir if args.out_dir is not None else work_dir / "run_files"
    try:
        planned = plan_alos2_run_files(alos2_cmds, args.unw_method)
        if args.dry_run:
            for name, tasks in planned:
                print(f"{name} {len(tasks)}")
            return 0
        written = write_alos2_run_files(alos2_cmds, run_dir, work_dir, args.unw_method)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
