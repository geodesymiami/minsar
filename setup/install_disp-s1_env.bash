#!/usr/bin/env bash
# Create disp-s1-env conda env from tools/disp-s1 (clone via install_sweets_env.bash if missing).
set -eo pipefail

MINSAR_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISP_DIR="$MINSAR_HOME/tools/disp-s1"
ENV_NAME="disp-s1-env"

if [[ ! -d "$DISP_DIR" ]]; then
    echo "Error: $DISP_DIR missing. Clone first with: ./setup/install_sweets_env.bash" >&2
    exit 1
fi
[[ -f "$DISP_DIR/conda-env.yml" ]] || {
    echo "Error: missing $DISP_DIR/conda-env.yml" >&2
    exit 1
}

source "$MINSAR_HOME/tools/miniforge3/etc/profile.d/conda.sh"
set +u

# Recreate env if it already exists (repos may already be present).
conda env remove -n "$ENV_NAME" --yes 2>/dev/null || true
conda env create -n "$ENV_NAME" -f "$DISP_DIR/conda-env.yml"
conda activate "$ENV_NAME"

ln -sf "$MINSAR_HOME/additions/disp-s1/disp_s1_process.py" "$DISP_DIR/scripts/disp_s1_process.py"
ln -sf "$MINSAR_HOME/additions/disp-s1/product.py" "$DISP_DIR/src/disp_s1/product.py"

pip install -e "$DISP_DIR"

echo "Running of install_disp-s1_env.bash DONE"
