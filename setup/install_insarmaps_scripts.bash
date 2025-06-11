#!/usr/bin/env bash
set -eox pipefail

export MINSAR_HOME=$PWD
source setup/platforms_defaults.bash;
source setup/environment.bash;
git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts
mamba install tippecanoe mintpy --yes -c conda-forge
pip install psycopg2 pycurl
