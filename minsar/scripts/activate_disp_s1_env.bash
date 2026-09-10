#!/usr/bin/env bash
# Activate the disp-s1 conda env for disp_s1_process.py (not SWEETS pixi).

set -euo pipefail

: "${MINSAR_HOME:?MINSAR_HOME must be set}"

_env_name="${DISP_S1_CONDA_ENV:-disp-s1-env}"
_minsar_env_dir="${MINSAR_HOME}/tools/miniforge3/envs/${_env_name}"

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
    if [[ ! -x "${_env_dir}/bin/python" ]]; then
        echo "Error: disp-s1 env python missing: ${_env_dir}/bin/python" >&2
        exit 1
    fi
    export CONDA_PREFIX="${_env_dir}"
    export CONDA_DEFAULT_ENV="${_env_name}"
    # Prepend env bin; drop a bare conda base python that lacks disp-s1 deps.
    export PATH="${_env_dir}/bin:${PATH}"
    _disp_s1_source_conda_activate_hooks "${_env_dir}"
}

# Explicit override (must be that env's python, not minsar/base).
if [[ -n "${DISP_S1_PYTHON:-}" ]]; then
    if [[ ! -x "${DISP_S1_PYTHON}" ]]; then
        echo "Error: DISP_S1_PYTHON is not executable: ${DISP_S1_PYTHON}" >&2
        exit 1
    fi
    _disp_s1_use_env_dir "$(cd "$(dirname "${DISP_S1_PYTHON}")/.." && pwd)"
    return 0 2>/dev/null || exit 0
fi

# Canonical location from setup/install_disp-s1_env.bash (ignore stale CONDA_* from sbatch).
if [[ -x "${_minsar_env_dir}/bin/python" ]]; then
    _disp_s1_use_env_dir "${_minsar_env_dir}"
    return 0 2>/dev/null || exit 0
fi

# Fallback: same env name under whatever conda base is on this host.
_conda_base=""
if [[ -f "${MINSAR_HOME}/tools/miniforge3/etc/profile.d/conda.sh" ]]; then
    _conda_base="${MINSAR_HOME}/tools/miniforge3"
elif [[ -n "${CONDA_EXE:-}" ]]; then
    _conda_base="$(cd "$(dirname "${CONDA_EXE}")/.." && pwd)"
elif command -v conda >/dev/null 2>&1; then
    _conda_base="$(conda info --base 2>/dev/null || true)"
fi

if [[ -n "${_conda_base}" && -f "${_conda_base}/etc/profile.d/conda.sh" ]]; then
    # shellcheck source=/dev/null
    source "${_conda_base}/etc/profile.d/conda.sh"
    _env_dir="$(conda env list | awk -v n="${_env_name}" '$1 == n {print $NF; exit}')"
    if [[ -n "${_env_dir}" && -x "${_env_dir}/bin/python" ]]; then
        _disp_s1_use_env_dir "${_env_dir}"
        return 0 2>/dev/null || exit 0
    fi
fi

echo "Error: disp-s1 conda env '${_env_name}' not found at:" >&2
echo "  ${_minsar_env_dir}" >&2
echo "Create it with: bash ${MINSAR_HOME}/setup/install_disp-s1_env.bash" >&2
echo "Or set DISP_S1_PYTHON to that env's python." >&2
exit 1
