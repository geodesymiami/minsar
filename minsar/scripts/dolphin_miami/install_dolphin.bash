#!/usr/bin/env bash
########################################################################
# Install Dolphin from GitHub under $SCRATCHDIR/dolphin_test
# Requires: conda or mamba, git
# Usage: bash install_dolphin.bash
########################################################################
set -euo pipefail

WORKDIR="${SCRATCHDIR:?SCRATCHDIR must be set}/dolphin_test"
DOLPHIN_REPO_URL="https://github.com/isce-framework/dolphin.git"
DOLPHIN_CLONE_DIR="${WORKDIR}/dolphin"
ENV_NAME="dolphin-env"

echo "Installing Dolphin under ${WORKDIR}"
mkdir -p "${WORKDIR}"
cd "${WORKDIR}"

if [[ -d "${DOLPHIN_CLONE_DIR}/.git" ]]; then
    echo "Dolphin repo already cloned at ${DOLPHIN_CLONE_DIR}; pulling latest."
    (cd "${DOLPHIN_CLONE_DIR}" && git pull)
else
    echo "Cloning Dolphin from ${DOLPHIN_REPO_URL}"
    git clone "${DOLPHIN_REPO_URL}" "${DOLPHIN_CLONE_DIR}"
fi

cd "${DOLPHIN_CLONE_DIR}"

if command -v mamba &>/dev/null; then
    CONDA_CMD=mamba
else
    CONDA_CMD=conda
fi

if conda env list | grep -q "^${ENV_NAME} "; then
    echo "Conda env ${ENV_NAME} already exists; updating from conda-env.yml"
    "${CONDA_CMD}" env update --name "${ENV_NAME}" --file conda-env.yml
else
    echo "Creating conda env ${ENV_NAME} from conda-env.yml"
    "${CONDA_CMD}" env create --file conda-env.yml
fi

echo "Installing dolphin with pip (editable)"
conda run -n "${ENV_NAME}" python -m pip install --no-deps -e .

echo "Done. Activate with: conda activate ${ENV_NAME}"
echo "Dolphin clone: ${DOLPHIN_CLONE_DIR}"
