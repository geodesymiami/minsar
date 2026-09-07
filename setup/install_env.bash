#!/usr/bin/env bash
# Create the minsar conda env from lockfile (Linux) or minsar_env_MacOS.yml (Darwin),
# then pip install -e core packages. Set RECREATE_ENV=1 to replace an existing env.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    helptext="
    usage: install_env.bash

    Create tools/miniforge3/envs/minsar from conda-lock.yml (Linux) or
    minsar_env_MacOS.yml (Darwin), then pip install -e MintPy/MiaplPy/sardem/sarvey.
    Skips env create if the prefix exists unless RECREATE_ENV=1.

    Examples:
        ./setup/install_env.bash
        RECREATE_ENV=1 ./setup/install_env.bash
    "
    echo -e "$helptext"
    exit 0
fi

ENV_PREFIX="${REPO_ROOT}/tools/miniforge3/envs/minsar"

### Install code into minsar environment  #################
if [[ "$(uname)" == "Darwin" ]]; then
    cp minsar_env.yml minsar_env_macOS.yml
    sed -i '' '/- isce/ s/^/# /' minsar_env_MacOS.yml
    sed -i '' '/gdal$/ s/gdal$/gdal=3.6\*/' minsar_env_MacOS.yml                  # only gdal=3.6 ships with the built-in postgresQL
    sed -i '' '/- pymaxflow/ s/^/# /' minsar_env_MacOS.yml                        # out-comment conda pymaxflow installation
    sed -i '' '/#- pymaxflow/ s/#- pymaxflow/- pymaxflow/' minsar_env_MacOS.yml   # activate pip pymaxflow installation
fi

create_env=1
if [[ -d "${ENV_PREFIX}" ]]; then
    if [[ "${RECREATE_ENV:-}" == "1" ]]; then
        echo "RECREATE_ENV=1: removing ${ENV_PREFIX}"
        rm -rf "${ENV_PREFIX}"
    else
        echo "minsar env exists at ${ENV_PREFIX}; skip create (RECREATE_ENV=1 to recreate)"
        create_env=0
    fi
fi

if [[ "${create_env}" == "1" ]]; then
    if [[ "$(uname)" == "Linux" ]]; then
        if [[ -f conda-lock.yml ]]; then
            echo "Lock file conda-lock.yml found. Using it for installation"
            # create lockfile: tools/miniforge3/bin/conda-lock lock -f minsar_env.yml --lockfile conda-lock.yml --platform linux-64
            tools/miniforge3/bin/mamba create --prefix "${ENV_PREFIX}" --file conda-lock.yml --yes
        else
            tools/miniforge3/bin/mamba --verbose env create -f minsar_env.yml --yes
        fi
    elif [[ "$(uname)" == "Darwin" ]]; then
        # FA 9/2025 lockfile for macOS did not work as pip failed to build wheels (need to try pixi)
        tools/miniforge3/bin/mamba --verbose env create -f minsar_env_MacOS.yml --yes
    fi
fi

source tools/miniforge3/etc/profile.d/conda.sh
set +u         # needed for circleCI
conda activate minsar

pip install -e tools/MintPy
pip install -e tools/MiaplPy
pip install -e tools/sardem
pip install -e tools/sarvey[dev] --no-deps

###  Reduce miniforge3 directory size #################
if [[ "${create_env}" == "1" ]]; then
    rm -rf tools/miniforge3/pkgs
fi

echo ""
echo "Running of install_env.bash DONE"
echo ""
