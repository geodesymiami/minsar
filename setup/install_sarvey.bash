#!/usr/bin/env bash
set -eo pipefail

### Source the environment  #################
export MINSAR_HOME=$PWD
source setup/platforms_defaults.bash;
source setup/environment.bash;

[[ -d tools/sarvey ]] || \
  git clone git@github.com:luhipi/sarvey tools/sarvey

### Install GDAL into sarvey environment #########################
conda create --name sarvey python=3.10 pip -y
source tools/miniforge3/etc/profile.d/conda.sh
conda activate sarvey

mamba install --yes -c conda-forge libpq postgresql pysolid gdal psycopg2
pip install -e tools/sarvey[dev]
pip install PySide6

[[ -d tools/sarplotter-main ]] || \
   git clone git@github.com:falkamelung/sarplotter-main.git tools/sarplotter-main

[[ -d tools/insarmaps_scripts ]] || \
  git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts

# removed because of incompatibility with sarvey
#mamba install tippecanoe mintpy --yes -c conda-forge
#pip install pycurl geocoder

###  Reduce miniforge3 directory size #################
rm -rf tools/miniforge3/pkgs

echo ""
echo "Installation of sarvey (install_sarvey.bash) DONE"
echo ""

