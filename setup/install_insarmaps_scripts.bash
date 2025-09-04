#!/usr/bin/env bash
set -eo pipefail

export MINSAR_HOME=$PWD
source setup/platforms_defaults.bash;
source setup/environment.bash;

source tools/miniforge3/etc/profile.d/conda.sh

[[ -d tools/insarmaps_scripts ]] || \
   git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts

conda create --name insarmaps_scripts python=3.10 pip -y
conda activate insarmaps_scripts

# Install GDAL and PostgreSQL support in one go. Mac needs gdal3.6* which has PostGresQL driver  built in
mamba install gdal=3.6.* libgdal postgresql libpq psycopg2 tippecanoe mintpy --yes -c conda-forge

pip install  pycurl geocoder
