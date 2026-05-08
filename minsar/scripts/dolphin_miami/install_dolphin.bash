#!/usr/bin/env bash
########################################################################
# Install Dolphin from GitHub (isce-framework/dolphin)
# Creates conda env 'dolphin-env' and installs dolphin.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-${SCRIPT_DIR}/dolphin}"
DOLPHIN_REPO="${DOLPHIN_REPO:-https://github.com/isce-framework/dolphin.git}"

usage() {
    echo "Usage: ${0##*/} [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --install-dir DIR   Clone dolphin into DIR (default: ${SCRIPT_DIR}/dolphin)"
    echo "  -h, --help          Show this help"
    echo ""
    echo "Requires: conda or mamba, git"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

if ! command -v conda &>/dev/null; then
    echo "Error: conda not found. Install Miniconda or Anaconda first." >&2
    exit 1
fi

echo "Installing Dolphin into: ${INSTALL_DIR}"
mkdir -p "$(dirname "${INSTALL_DIR}")"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo "Existing clone found; pulling latest..."
    (cd "${INSTALL_DIR}" && git pull)
else
    git clone "${DOLPHIN_REPO}" "${INSTALL_DIR}"
fi

if command -v mamba &>/dev/null; then
    MAMBA_CMD="mamba"
else
    MAMBA_CMD="conda"
fi

if conda env list | grep -q '^dolphin-env '; then
    echo "Updating existing conda env dolphin-env..."
    ${MAMBA_CMD} env update --name dolphin-env --file "${INSTALL_DIR}/conda-env.yml"
else
    echo "Creating conda env dolphin-env..."
    ${MAMBA_CMD} env create --file "${INSTALL_DIR}/conda-env.yml"
fi

echo "Installing dolphin package..."
(
    eval "$(conda shell.bash hook)"
    conda activate dolphin-env
    python -m pip install -e "${INSTALL_DIR}"
)

echo "Done. Activate with: conda activate dolphin-env"
echo "Then run: dolphin config --help"
