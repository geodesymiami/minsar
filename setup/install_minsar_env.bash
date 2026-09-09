#!/usr/bin/env bash
# Create minsar conda env (lock on Linux; minsar_env_MacOS.yml on Darwin) + pip -e.
set -eo pipefail

ENV_PREFIX=tools/miniforge3/envs/minsar

if [[ "$(uname)" == "Darwin" ]]; then
    cp minsar_env.yml minsar_env_macOS.yml
    sed -i '' '/- isce/ s/^/# /' minsar_env_MacOS.yml
    # PG driver: minsar_env.yml includes libgdal-pg (do not pin gdal=3.6*)
    sed -i '' '/- pymaxflow/ s/^/# /' minsar_env_MacOS.yml                        # out-comment conda pymaxflow installation
    sed -i '' '/#- pymaxflow/ s/#- pymaxflow/- pymaxflow/' minsar_env_MacOS.yml   # activate pip pymaxflow installation
fi

rm -rf "$ENV_PREFIX"

if [[ "$(uname)" == "Linux" ]]; then
    if [[ -f conda-lock.yml ]]; then
        echo "Lock file conda-lock.yml found. Using it for installation"
        tools/miniforge3/bin/mamba create --prefix "$ENV_PREFIX" --file conda-lock.yml --yes
    else
        tools/miniforge3/bin/mamba --verbose env create -f minsar_env.yml --yes
    fi
elif [[ "$(uname)" == "Darwin" ]]; then
    # FA 9/2025 lockfile for macOS did not work as pip failed to build wheels (need to try pixi)
    # --override-channels: ignore ~/.condarc defaults (mix with conda-forge makes solves hang/fail)
    tools/miniforge3/bin/mamba --verbose env create -f minsar_env_MacOS.yml --yes -c conda-forge --override-channels
fi

source tools/miniforge3/etc/profile.d/conda.sh
set +u
conda activate minsar

pip install -e tools/MintPy
pip install -e tools/MiaplPy
pip install -e tools/sardem
pip install -e tools/sarvey[dev] --no-deps

rm -rf tools/miniforge3/pkgs

echo "Running of install_minsar_env.bash DONE"
