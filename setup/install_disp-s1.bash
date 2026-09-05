#!/usr/bin/env bash
set -eo pipefail

source tools/miniforge3/etc/profile.d/conda.sh
set +u

conda env create -n disp-s1-env -f tools/disp-s1/conda-env.yml
conda activate disp-s1-env
pip install -e tools/disp-s1

echo "disp-s1 installation DONE"
