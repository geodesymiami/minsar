#!/usr/bin/env bash
# Create/update the disp-s1 conda env used by ISCE3 opera-mode disp_s1_process.

set -eo pipefail

MINSAR_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_env_name="${DISP_S1_CONDA_ENV:-disp-s1-env}"
_env_dir="${MINSAR_HOME}/tools/miniforge3/envs/${_env_name}"

print_help() {
    cat <<EOF
usage: install_disp-s1.bash [-h]

Create or update conda env ${_env_name} for disp_s1_process (ISCE3 opera mode).

options:
  -h, --help   show this help

Examples:
  setup/install_disp-s1.bash
  DISP_S1_CONDA_ENV=disp-s1-env setup/install_disp-s1.bash
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        -*)
            echo "Error: unknown option: $1" >&2
            exit 1
            ;;
        *)
            echo "Error: unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ ! -f "${MINSAR_HOME}/tools/miniforge3/etc/profile.d/conda.sh" ]]; then
    echo "Error: miniforge3 not found under ${MINSAR_HOME}/tools/miniforge3" >&2
    exit 1
fi
if [[ ! -f "${MINSAR_HOME}/tools/disp-s1/conda-env.yml" ]]; then
    echo "Error: tools/disp-s1 missing; clone it (install_isce3.bash) first" >&2
    exit 1
fi

# shellcheck source=/dev/null
source "${MINSAR_HOME}/tools/miniforge3/etc/profile.d/conda.sh"
set +u

if [[ -x "${_env_dir}/bin/python" ]]; then
    echo "disp-s1 env exists: ${_env_dir} (updating editable install)"
else
    echo "Creating conda env ${_env_name} from tools/disp-s1/conda-env.yml ..."
    conda env create -n "${_env_name}" -f "${MINSAR_HOME}/tools/disp-s1/conda-env.yml"
fi

conda activate "${_env_name}"

ln -sf "${MINSAR_HOME}/additions/disp-s1/disp_s1_process.py" "${MINSAR_HOME}/tools/disp-s1/scripts/disp_s1_process.py"
ln -sf "${MINSAR_HOME}/additions/disp-s1/product.py" "${MINSAR_HOME}/tools/disp-s1/src/disp_s1/product.py"

pip install -e "${MINSAR_HOME}/tools/disp-s1"
python -c "import disp_s1; print(f'Verified disp_s1 {disp_s1.__file__}')"

echo "disp-s1 installation DONE (${_env_dir})"
