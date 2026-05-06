#!/usr/bin/env python3

import os
import argparse
from datetime import datetime
import shlex as _shlex
from minsar.objects.auto_defaults import PathFind
from minsar.objects.dataset_template import Template


W2 = os.getenv('WORK2')
SWEET = os.path.join(W2, 'code', 'sweets')
ORBITS = os.getenv('SENTINEL_ORBITS')
pathObj = PathFind()

DESCRIPTION = 'Create SWEET config files'

EXAMPLE = """
Example:
  create_sweet.py template.txt
"""

def create_parser():
    synopsis = 'Create download commands'
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('template', help='custom template with option settings.\n')

    inps = parser.parse_args()
    return inps

inps = create_parser()

dataset_template = Template(inps.template)
dataset_template.options.update(pathObj.correct_for_ssara_date_format(dataset_template.options))

ssaraopt_string, ssaraopt_dict = dataset_template.generate_ssaraopt_string()

options = dataset_template.get_options()
bbox = (
    options.get('miaplpy.subset.lalo')
    or options.get('mintpy.subset.lalo')
    or options.get('topsStack.boundingBox')
)

if options.get('dataset', None):
    if options.get('dataset') in os.getcwd():
      dir = os.getcwd()
    elif os.getenv('SCRATCHDIR'):
      dir = os.path.join(os.getenv('SCRATCHDIR'), options.get('dataset'))
    else:
      dir = os.getcwd()
else:
    dir = os.getcwd()

template_args = [
    "pixi",
    "run",
    "sweets",
    "config",
    "--no-gpu-enabled",
    "--orbit-dir",
    ORBITS or "",
    "--out-dir",
    f"{dir}/SLC",
    "--work-dir",
    f"{dir}",
    "--output",
    f"{dir}/sweets_config.yaml",
]

# Parse bbox components only if bbox is provided
if bbox:
    if ',' in bbox:
        lat, lon = bbox.split(',')
        lat1, lat2 = lat.split(':')
        lon1, lon2 = lon.split(':')
    else:
        lat1, lat2, lon1, lon2 = bbox.split(' ')

# Add optional ssara arguments when present
start_val = ssaraopt_dict.get('start', '2014-01-01')
end_val = ssaraopt_dict.get('end', datetime.today().strftime('%Y-%m-%d'))
rel_orbit = ssaraopt_dict.get('relativeOrbit') or ssaraopt_dict.get('orbit')

if start_val:
    template_args += ["--start", start_val]

if end_val:
    template_args += ["--end", end_val]

if bbox:
    template_args += ["--bbox", lon1, lat1, lon2, lat2]

if rel_orbit:
    template_args += ["--track", rel_orbit]

# Keep an equivalent string for legacy code that might expect a single string
config = ' '.join(_shlex.quote(str(a)) for a in template_args if a is not None and a != '')


###### CREATE RUN FILE ######
def create_run_file(cores, time, queue, cmd):
    return f"""
    #!/bin/bash
    #SBATCH -J sweets_job
    #SBATCH -o sweets_%j.out
    #SBATCH -e sweets_%j.err
    #SBATCH -N 1
    #SBATCH -n 1
    #SBATCH -c {cores}
    #SBATCH -t {time}
    #SBATCH -p {queue}

    source ~/.bashrc
    export PATH=$HOME/.pixi/bin:$PATH
    export CUDA_VISIBLE_DEVICES=""
    export ISCE3_FORCE_CPU=1
    export OMP_NUM_THREADS=1
    export CUDA_VISIBLE_DEVICES=""
    export NVIDIA_VISIBLE_DEVICES="none"
    export ISCE3_USE_GPU=0

    # Go to Pixi project (IMPORTANT)
    cd {W2}/code/sweets

    # Run sweets
    {cmd}
    """

# CONFIG FILE
with open(f"{dir}/config_sweets.job", 'w') as f:
    cores = 1
    time = "00:02:00"
    queue = "skx-dev"
    cmd = config
    f.write(create_run_file(cores, time, queue, cmd))
# RUN FILE
with open(f"{dir}/run_sweets.job", 'w') as f:
    cores = 48
    time = "06:00:00"
    queue = os.getenv("QUEUENAME") if os.getenv("QUEUENAME") else "skx"
    cmd = f"pixi run sweets run {dir}/sweets_config.yaml"
    f.write(create_run_file(cores, time, queue, cmd))