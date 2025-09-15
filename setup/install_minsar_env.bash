#!/usr/bin/env bash
set -eo pipefail

### Install code into minsar environment  #################
if [[ "$(uname)" == "Darwin" ]]; then
    cp minsar_env.yml minsar_env_macOS.yml
    sed -i '' '/- isce/ s/^/# /' minsar_env_MacOS.yml
    sed -i '' '/gdal$/ s/gdal$/gdal=3.6\*/' minsar_env_MacOS.yml                  # only gdal=3.6 ships with the built-in postgresQL
    sed -i '' '/- pymaxflow/ s/^/# /' minsar_env_MacOS.yml                        # out-comment conda pymaxflow installation
    sed -i '' '/#- pymaxflow/ s/#- pymaxflow/- pymaxflow/' minsar_env_MacOS.yml   # activate pip pymaxflow installation
fi

if [[ "$(uname)" == "Linux" ]]; then
    if [[ -f conda-lock.yml ]]; then
       echo "Lock file conda-lock.yml found. Using it for installation"
       tools/miniforge3/bin/mamba create --prefix tools/miniforge3/envs/minsar --file conda-lock.yml --yes
    else
       tools/miniforge3/bin/mamba --verbose env create -f minsar_env.yml --yes
    fi
elif [[ "$(uname)" == "Darwin" ]]; then
    # FA 9/2025 lockfile for macOS did not work as pip failed to build wheels (need to try pixi)
    tools/miniforge3/bin/mamba --verbose env create -f minsar_env_MacOS.yml --yes
fi

echo ""
echo "Running of install_minsar_env.bash DONE"
echo ""
