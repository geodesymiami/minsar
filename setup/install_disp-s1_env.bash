#!/usr/bin/env bash
# Create disp-s1-env conda env from tools/disp-s1 (clone via install_sweets_env.bash if missing).
set -eo pipefail

MINSAR_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISP_DIR="$MINSAR_HOME/tools/disp-s1"
ENV_NAME="disp-s1-env"
ENV_PREFIX="$MINSAR_HOME/tools/miniforge3/envs/$ENV_NAME"
MAMBA="$MINSAR_HOME/tools/miniforge3/bin/mamba"
CONDA_SH="$MINSAR_HOME/tools/miniforge3/etc/profile.d/conda.sh"

if [[ ! -d "$DISP_DIR" ]]; then
    echo "Error: $DISP_DIR missing. Clone first with: ./setup/install_sweets_env.bash" >&2
    exit 1
fi
[[ -f "$DISP_DIR/conda-env.yml" ]] || {
    echo "Error: missing $DISP_DIR/conda-env.yml" >&2
    exit 1
}

if [[ "$(uname)" == "Darwin" ]]; then
    # Mac-only: tophu is Linux-only. Write a .yml (extension required by mamba) without
    # tophu or pip extras; install dolphin/opera-utils/spurt/zarr with pip after.
    # env -i install (docs) has PATH=/usr/bin:/bin:/sbin; mamba needs miniforge on PATH.
    export PATH="$MINSAR_HOME/tools/miniforge3/bin:/usr/bin:/bin:/sbin"
    export TMPDIR="${TMPDIR:-/tmp}"
    export MAMBA_ROOT_PREFIX="$MINSAR_HOME/tools/miniforge3"
    if [[ -f "$MINSAR_HOME/tools/miniforge3/ssl/cert.pem" ]]; then
        export SSL_CERT_FILE="${SSL_CERT_FILE:-$MINSAR_HOME/tools/miniforge3/ssl/cert.pem}"
    fi
    rm -rf "$ENV_PREFIX"
    TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/disp-s1-conda.XXXXXX")
    TMP_YML="$TMP_DIR/conda-env.yml"
    cat > "$TMP_YML" <<'EOF'
name: disp-s1-env
channels:
  - conda-forge
dependencies:
  - python>=3.9,<3.13
  - pip>=21.3
  - git
  - click>=7.0
  - cmap
  - gdal>=3.8
  - libgdal-netcdf
  - libgdal-hdf5
  - h5netcdf>=1.0
  - matplotlib-base
  - pydantic>=2.1
  - ruamel.yaml>=0.15
  - yamale
  - pysolid
  - xarray
  - snaphu>=0.4.1
  - isce3-cpu>=0.16.0
  - rich
  - pip
EOF
    echo "Creating $ENV_NAME on macOS without tophu (Linux-only on conda-forge)"
    "$MAMBA" env create -p "$ENV_PREFIX" -f "$TMP_YML" --yes -c conda-forge --override-channels
    rm -rf "$TMP_DIR"
    source "$CONDA_SH"
    set +u
    conda activate "$ENV_PREFIX"
    pip install -e "$DISP_DIR"
    pip install 'dolphin>=0.42.7' 'opera-utils>=0.25.7' 'spurt>=0.1.0'
else
    source "$CONDA_SH"
    set +u
    # Recreate env if it already exists (repos may already be present).
    conda env remove -n "$ENV_NAME" --yes 2>/dev/null || true
    conda env create -n "$ENV_NAME" -f "$DISP_DIR/conda-env.yml"
    conda activate "$ENV_NAME"
    pip install -e "$DISP_DIR"
fi
# MinSAR disp_s1_process.py writes a zarr stack; not in upstream conda-env.yml.
pip install 'zarr>=2,<4'
python -c "import zarr; print('Verified zarr in disp-s1-env')"

ln -sf "$MINSAR_HOME/additions/disp-s1/disp_s1_process.py" "$DISP_DIR/scripts/disp_s1_process.py"
ln -sf "$MINSAR_HOME/additions/disp-s1/product.py" "$DISP_DIR/src/disp_s1/product.py"

echo "Running of install_disp-s1_env.bash DONE"
