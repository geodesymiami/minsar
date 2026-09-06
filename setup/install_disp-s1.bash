#!/usr/bin/env bash
set -eo pipefail

MINSAR_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$MINSAR_HOME/tools/miniforge3/etc/profile.d/conda.sh"
set +u

conda env create -n disp-s1-env -f "$MINSAR_HOME/tools/disp-s1/conda-env.yml"
conda activate disp-s1-env

ln -sf "$MINSAR_HOME/additions/disp-s1/disp_s1_process.py" "$MINSAR_HOME/tools/disp-s1/scripts/disp_s1_process.py"
ln -sf "$MINSAR_HOME/additions/disp-s1/product.py" "$MINSAR_HOME/tools/disp-s1/src/disp_s1/product.py"

pip install -e "$MINSAR_HOME/tools/disp-s1"

echo "disp-s1 installation DONE"
