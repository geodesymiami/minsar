#!/usr/bin/env bash
set -eo pipefail

### Source the environment  #################
export MINSAR_HOME=$PWD

source setup/platforms_defaults.bash;
source setup/environment.bash;


### git clone the code   #################
git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts
git clone git@github.com:geodesymiami/insarmaps.git tools/insarmaps

mamba install --file tools/insarmaps_scripts/conda_requirements.txt --yes -c conda-forge
pip install -r tools/insarmaps_scripts/pip_requirements.txt

###  Reduce miniforge3 directory size #################
rm -rf tools/miniforge3/pkgs

echo ""
echo "Installation of install_insarmaps_scripts.bash DONE"
echo ""
