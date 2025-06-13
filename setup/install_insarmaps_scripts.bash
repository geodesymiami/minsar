#!/usr/bin/env bash
set -eo pipefail

export MINSAR_HOME=$PWD
source setup/platforms_defaults.bash;
source setup/environment.bash;
[[ -d tools/insarmaps_scripts ]] || \
   git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts

conda create --name insarmaps_scripts python=3.10 pip -y
source tools/miniforge3/etc/profile.d/conda.sh
conda activate insarmaps_scripts

mamba install tippecanoe mintpy --yes -c conda-forge
pip install psycopg2 pycurl geocoder
