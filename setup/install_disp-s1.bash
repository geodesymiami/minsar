#!/usr/bin/env bash
set -eo pipefail

# Run from the MinSAR repo root (same as other setup/install_*.bash).
# Uses an explicit prefix so the env is not nested under an active minsar env.

source tools/miniforge3/etc/profile.d/conda.sh
set +u

conda activate base
conda env create -p "$PWD/tools/miniforge3/envs/disp-s1-env" -f tools/disp-s1/conda-env.yml
conda activate "$PWD/tools/miniforge3/envs/disp-s1-env"

ln -sf "$PWD/additions/disp-s1/disp_s1_process.py" tools/disp-s1/scripts/disp_s1_process.py
ln -sf "$PWD/additions/disp-s1/product.py" tools/disp-s1/src/disp_s1/product.py

pip install -e tools/disp-s1
pip install 'zarr>=2,<4'

echo "disp-s1 installation DONE"
