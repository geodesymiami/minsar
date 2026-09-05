#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
usage: install_disp-s1.bash [-h]

Create disp-s1-env (conda) and link MinSAR's patched disp_s1_process.py into tools/disp-s1.

Requires tools/disp-s1 (clone via setup/install_isce3.bash). Installs disp-s1-env under
tools/miniforge3/envs/minsar/envs/ so activate_disp_s1_env.bash finds it with MinSAR loaded.

options:
  -h, --help  show this help

Examples:
  bash setup/install_disp-s1.bash
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -?*)
            echo "Error: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            echo "Error: unexpected argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINSAR_HOME="$(cd "${SCRIPT_DIR}/.." && pwd)"
export MINSAR_HOME

DISP_S1_REPO="${MINSAR_HOME}/tools/disp-s1"
CONDA_ENV_FILE="${DISP_S1_REPO}/conda-env.yml"
PATCHED_SCRIPT="${MINSAR_HOME}/additions/disp-s1/disp_s1_process.py"
TARGET_SCRIPT="${DISP_S1_REPO}/scripts/disp_s1_process.py"
ENV_NAME="disp-s1-env"
CONDA_SH="${MINSAR_HOME}/tools/miniforge3/etc/profile.d/conda.sh"
MAMBA="${MINSAR_HOME}/tools/miniforge3/bin/mamba"
NESTED_ENVS="${MINSAR_HOME}/tools/miniforge3/envs/minsar/envs"

if [[ ! -d "${DISP_S1_REPO}/.git" && ! -f "${CONDA_ENV_FILE}" ]]; then
    echo "Error: ${DISP_S1_REPO} not found." >&2
    echo "Clone it first: bash setup/install_isce3.bash (or git clone git@github.com:opera-adt/disp-s1.git ${DISP_S1_REPO})" >&2
    exit 1
fi

if [[ ! -f "${PATCHED_SCRIPT}" ]]; then
    echo "Error: patched script not found: ${PATCHED_SCRIPT}" >&2
    exit 1
fi

if [[ ! -f "${CONDA_SH}" ]]; then
    echo "Error: miniforge not found at ${MINSAR_HOME}/tools/miniforge3 (run setup/install_python.bash and setup/install_minsar.bash first)." >&2
    exit 1
fi

if [[ ! -x "${MAMBA}" ]]; then
    MAMBA="${MINSAR_HOME}/tools/miniforge3/bin/conda"
fi

# shellcheck source=/dev/null
source "${CONDA_SH}"
mkdir -p "${NESTED_ENVS}"
export CONDA_ENVS_PATH="${NESTED_ENVS}"

if "${MAMBA}" env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
    echo "Conda env '${ENV_NAME}' already exists at ${NESTED_ENVS}/${ENV_NAME}"
else
    echo "Creating conda env '${ENV_NAME}' from ${CONDA_ENV_FILE}..."
    "${MAMBA}" env create -n "${ENV_NAME}" -f "${CONDA_ENV_FILE}" --yes
fi

set +u
conda activate "${ENV_NAME}"
set -u

echo "Installing disp-s1 package (editable) from ${DISP_S1_REPO}..."
python -m pip install -e "${DISP_S1_REPO}"

mkdir -p "$(dirname "${TARGET_SCRIPT}")"
ln -sf "${PATCHED_SCRIPT}" "${TARGET_SCRIPT}"
echo "Linked ${TARGET_SCRIPT} -> ${PATCHED_SCRIPT}"

echo "disp-s1 installation DONE"
echo "Activate with: source ${MINSAR_HOME}/minsar/scripts/activate_disp_s1_env.bash"
