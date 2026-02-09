#!/usr/bin/env python3

import os
import sys
import glob
import argparse
from pathlib import Path
from collections import defaultdict

from minsar.objects import message_rsmas
from minsar.objects.auto_defaults import PathFind
from minsar.job_submission import JOB_SUBMIT

# pathObj = PathFind()
inps = None

##############################################################################
DOCS_README = "docs/README_burst_download.md"

EXAMPLE = """example:
    bursts_to_burst2safe_jobfile.py SLC

    Creates runfile for burst2safe: one line per (date, hash, subswath) so that:
    - Bursts from different SLCs (different hashes) are never mixed.
    - Bursts from different subswaths (IW1/IW2/IW3) are in separate SAFEs, avoiding
      burst2safe "Products from subswaths ... do not overlap" errors.
    See %s for details.
""" % DOCS_README

DESCRIPTION = ("""
     Creates runfile and jobfile for burst2safe (run after downloading bursts).
     Documentation: %s
""" % DOCS_README)

def create_parser():
    synopsis = 'Create burst2safe run_file'
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    # parser.add_argument('ssara_listing_path', help='file name\n')
    parser.add_argument('burst_dir_path', metavar="DIRECTORY", help='bursts directory')

    parser.add_argument("--queue", dest="queue", metavar="QUEUE", help="Name of queue to submit job to")

    inps = parser.parse_args()

    # inps.ssara_listing_path = Path(inps.ssara_listing_path).resolve()
    
    return inps

###############################################
def clean_path(f):
        p = Path(f)
        # Remove all suffixes
        while p.suffix:
            p = p.with_suffix('')
        # Return only the filename (i.e., remove the "SLC/" part)
        return p.name


def burst_hash(burst_basename):
    """Extract hash from burst filename, e.g. S1_185679_IW1_20251112T161529_VV_8864-BURST -> 8864.
    Bursts with the same (date, hash) come from the same SLC; different hashes must not be mixed in one SAFE.
    """
    # Last segment is like '8864-BURST'
    return burst_basename.split('_')[-1].replace('-BURST', '')


def burst_subswath(burst_basename):
    """Extract subswath from burst filename, e.g. S1_185679_IW1_20251112T161529_VV_8864-BURST -> IW1.
    One burst2safe call per subswath avoids 'Products from subswaths IW2 and IW3 do not overlap' errors
    when burst ID ranges of adjacent subswaths do not satisfy burst2safe's overlap rule.
    """
    # Pattern: S1_<id>_<IW1|IW2|IW3>_<datetime>_VV_<hash>-BURST
    return burst_basename.split('_')[2]


###############################################

def main(iargs=None):

    # parse
    inps = create_parser()

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    inps.work_dir = os.getcwd()
    run_01_burst2safe_path = Path(inps.work_dir) / inps.burst_dir_path / 'run_01_burst2safe'

    burst_list_fullpath = glob.glob(inps.burst_dir_path + '/*.tiff')
    burst_list = [clean_path(f) for f in burst_list_fullpath ]

    # Group by (date, hash, subswath): one burst2safe call per group.
    # - Same hash = same source SLC; mixing hashes causes burst2safe errors.
    # - One call per subswath avoids "Products from subswaths IW2 and IW3 do not overlap"
    #   when adjacent subswaths' burst ID ranges don't satisfy burst2safe's overlap rule.
    bursts_by_date_hash_swath = defaultdict(list)
    for burst in burst_list:
        date_str = burst.split('_')[3][:8]  # YYYYMMDD
        h = burst_hash(burst)
        swath = burst_subswath(burst)
        bursts_by_date_hash_swath[(date_str, h, swath)].append(burst)

    date_to_remove = ['20250429', '20250430', '20250501', '20250313']
    # One jobfile line per (date, hash, subswath) group with >1 burst; skip excluded dates.
    groups = [
        ((date_str, h, swath), bursts)
        for (date_str, h, swath), bursts in bursts_by_date_hash_swath.items()
        if len(bursts) > 1 and date_str not in date_to_remove
    ]
    if not groups:
        raise RuntimeError(
            "USER ERROR: no (date, hash, subswath) group has more than 1 burst. "
            "Need more than 1 burst per SLC for ISCE processing (run_07_merge* step)."
        )

    output_dir = str(Path(inps.work_dir) / inps.burst_dir_path)
    with open(run_01_burst2safe_path, "w") as f:
        for (date_str, h, swath), bursts in sorted(groups):
            f.write("burst2safe " + ' '.join(sorted(bursts)) + " --keep-files --output-dir " + output_dir + "\n")

    print("Created: ", run_01_burst2safe_path, "(%d lines, one SAFE per date+hash+subswath)" % len(groups))
    
    # find *template file (needed currently for run_workflow.bash)
    current_directory = Path(os.getcwd())
    parent_directory = current_directory.parent
    template_files_current = glob.glob(str(current_directory / '*.template'))
    template_files_parent = glob.glob(str(parent_directory / '*.template'))
    template_files = template_files_current + template_files_parent
    if template_files:
        inps.custom_template_file = template_files[0]
    else:
        raise FileNotFoundError("No file found ending with *template")

    inps.out_dir = inps.burst_dir_path
    inps.num_data = 1
    job_obj = JOB_SUBMIT(inps)  
    job_obj.write_batch_jobs(batch_file = str(run_01_burst2safe_path) )

###############################################
if __name__ == "__main__":
    main()
