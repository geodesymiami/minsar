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

    Creates runfile for burst2safe. Prefers one SAFE per (date, hash) when subswaths
    overlap (one product with IW1+IW2+IW3 for ISCE). Splits by subswath only when
    burst2safe would fail with "Products from subswaths ... do not overlap".
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
    """Extract subswath from burst filename, e.g. S1_185679_IW1_20251112T161529_VV_8864-BURST -> IW1."""
    return burst_basename.split('_')[2]


def burst_id_from_name(burst_basename):
    """Extract relative burst ID from filename, e.g. S1_185682_IW1_... -> 185682."""
    return int(burst_basename.split('_')[1])


def subswaths_overlap(bursts_by_swath):
    """
    Return True if adjacent subswaths (IW1-IW2, IW2-IW3) satisfy burst2safe's overlap rule:
    |min_burst_id difference| <= 1 and |max_burst_id difference| <= 1.
    bursts_by_swath: dict mapping subswath name (e.g. 'IW1') to list of burst basenames.
    """
    order = ['IW1', 'IW2', 'IW3']
    ranges = {}
    for sw in order:
        if sw not in bursts_by_swath or not bursts_by_swath[sw]:
            continue
        ids = [burst_id_from_name(b) for b in bursts_by_swath[sw]]
        ranges[sw] = (min(ids), max(ids))
    if len(ranges) <= 1:
        return True
    for i in range(len(order) - 1):
        s1, s2 = order[i], order[i + 1]
        if s1 not in ranges or s2 not in ranges:
            continue
        (min1, max1), (min2, max2) = ranges[s1], ranges[s2]
        if abs(min1 - min2) > 1 or abs(max1 - max2) > 1:
            return False
    return True


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

    # Group by (date, hash) then by subswath.
    bursts_by_date_hash = defaultdict(lambda: defaultdict(list))
    for burst in burst_list:
        date_str = burst.split('_')[3][:8]  # YYYYMMDD
        h = burst_hash(burst)
        swath = burst_subswath(burst)
        bursts_by_date_hash[(date_str, h)][swath].append(burst)

    date_to_remove = ['20250429', '20250430', '20250501', '20250313']
    # Prefer one burst2safe call per (date, hash) when subswaths overlap (one SAFE = all subswaths, ISCE-compatible).
    # Only split by subswath when overlap rule would fail (multiple SAFEs per date then require ISCE to handle per-subswath SAFEs).
    groups = []
    for (date_str, h), swath_dict in sorted(bursts_by_date_hash.items()):
        if date_str in date_to_remove:
            continue
        if subswaths_overlap(swath_dict):
            all_bursts = []
            for sw in ['IW1', 'IW2', 'IW3']:
                all_bursts.extend(swath_dict.get(sw, []))
            if len(all_bursts) > 1:
                groups.append((None, (date_str, h), all_bursts))  # one line for whole (date, hash)
        else:
            for swath, bursts in sorted(swath_dict.items()):
                if len(bursts) > 1:
                    groups.append((swath, (date_str, h), bursts))

    if not groups:
        raise RuntimeError(
            "USER ERROR: no (date, hash) or (date, hash, subswath) group has more than 1 burst. "
            "Need more than 1 burst per SLC for ISCE processing (run_07_merge* step)."
        )

    output_dir = str(Path(inps.work_dir) / inps.burst_dir_path)
    with open(run_01_burst2safe_path, "w") as f:
        for key, (date_str, h), bursts in sorted(groups, key=lambda x: (x[1], x[0] or '')):
            f.write("burst2safe " + ' '.join(sorted(bursts)) + " --keep-files --output-dir " + output_dir + "\n")

    print("Created: ", run_01_burst2safe_path, "(%d lines)" % len(groups))
    
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
