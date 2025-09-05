#!/usr/bin/env bash
set -eo pipefail

[[ -d tools/insarmaps_scripts ]] || \
   git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts

tools/miniforge3/bin/mamba --verbose env create -f tools/insarmaps_scripts/environment.yml --yes

source tools/miniforge3/etc/profile.d/conda.sh

# conda create --name insarmaps_scripts python=3.10 pip -y
# conda activate insarmaps_scripts
# 
# # Install GDAL and PostgreSQL support in one go. Mac needs gdal3.6* which has PostGresQL driver  built in
# mamba install gdal=3.6.* libgdal postgresql libpq psycopg2 tippecanoe mintpy --yes -c conda-forge
# 
# pip install  pycurl geocoder
