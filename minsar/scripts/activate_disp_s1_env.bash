#!/usr/bin/env bash
# Activate the disp-s1 conda env for disp_s1_process.py (not SWEETS pixi).

set -euo pipefail

: "${MINSAR_HOME:?MINSAR_HOME must be set}"

_env_name="${DISP_S1_CONDA_ENV:-disp-s1-env}"

_disp_s1_source_conda_activate_hooks() {
    local _activate_d="${1}/etc/conda/activate.d"
    [[ -d "${_activate_d}" ]] || return 0
    local _had_u=0
    case $- in *u*) _had_u=1; set +u ;; esac
    local _sh
    for _sh in "${_activate_d}/"*.sh; do
        [[ -f "${_sh}" ]] || continue
        # shellcheck source=/dev/null
        source "${_sh}"
    done
    if (( _had_u )); then set -u; fi
}

_disp_s1_use_env_dir() {
    local _env_dir="$1"
    export CONDA_PREFIX="${_env_dir}"
    export PATH="${_env_dir}/bin:${PATH}"
    _disp_s1_source_conda_activate_hooks "${_env_dir}"
}

if [[ -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV}" == "${_env_name}" ]]; then
    return 0 2>/dev/null || exit 0
fi

if [[ -n "${DISP_S1_PYTHON:-}" && -x "${DISP_S1_PYTHON}" ]]; then
    _disp_s1_use_env_dir "$(cd "$(dirname "${DISP_S1_PYTHON}")/.." && pwd)"
    return 0 2>/dev/null || exit 0
fi

# Prefer the MinSAR-tree env created by setup/install_disp-s1.bash / install_isce3.
_minsar_env_dir="${MINSAR_HOME}/tools/miniforge3/envs/${_env_name}"
if [[ -x "${_minsar_env_dir}/bin/python" ]]; then
    _disp_s1_use_env_dir "${_minsar_env_dir}"
    return 0 2>/dev/null || exit 0
fi

_conda_base=""
if [[ -n "${CONDA_EXE:-}" ]]; then
    _conda_base="$(cd "$(dirname "${CONDA_EXE}")/.." && pwd)"
elif command -v conda >/dev/null 2>&1; then
    _conda_base="$(conda info --base 2>/dev/null || true)"
fi

if [[ -n "${_conda_base}" && -f "${_conda_base}/etc/profile.d/conda.sh" ]]; then
    # shellcheck source=/dev/null
    source "${_conda_base}/etc/profile.d/conda.sh"
    _env_dir="$(conda env list | awk -v n="${_env_name}" '$1 == n {print $NF; exit}')"
    if [[ -n "${_env_dir}" && -x "${_env_dir}/bin/python" ]]; then
        # Prefer PATH over `conda activate`: deactivate hooks (libxml2, isce2, …)
        # reference unset vars and abort under `set -u` in batch run scripts.
        _disp_s1_use_env_dir "${_env_dir}"
        return 0 2>/dev/null || exit 0
    fi
fi

echo "Error: disp-s1 conda env '${_env_name}' not active." >&2
echo "Create it with: bash ${MINSAR_HOME}/setup/install_disp-s1.bash" >&2
echo "Or set DISP_S1_PYTHON to a Python with disp-s1 installed." >&2
exit 1
