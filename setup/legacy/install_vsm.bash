#!/usr/bin/env bash
set -eo pipefail

git clone git@github.com:EliTras/VSM.git tools/VSM

### Install dependencies into vsm environment #########################
tools/miniforge3/bin/conda create --name vsm python=3.10 pip -y

source tools/miniforge3/etc/profile.d/conda.sh
set +u   # for circleCI
conda activate vsm

pip install -r tools/VSM/VSM/requirements.txt
#pip install -e tools/VSM
###  Reduce miniforge3 directory size #################
rm -rf tools/miniforge3/pkgs

echo ""
echo "Installation of install_VSM.bash DONE"
