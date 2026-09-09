#!/usr/bin/env bash
# Clone isceplus (skip if present) and create its conda env.
set -eo pipefail

clone_repo() {
    [[ -e "$2" ]] && echo "skip clone (exists): $2" && return 0
    git clone "$1" "$2"
}

### git clone the code   #################
clone_repo git@github.com:isceplus/2026-isceplus.git tools/isceplus

[[ -d tools/isceplus ]] || {
    echo "Error: tools/isceplus missing after clone" >&2
    exit 1
}

YML_DIR="tools/isceplus/S07_Installing_the_course_environment_with_conda"
ENV_NAME="earthscope_insar"

source tools/miniforge3/etc/profile.d/conda.sh
set +u

# Recreate env if it already exists (repo may already be present).
conda env remove -n "$ENV_NAME" --yes 2>/dev/null || true

### Install code into conda environment  #################
if [[ "$(uname)" == "Darwin" ]]; then
    cp "$YML_DIR/isceplus2026.yml" "$YML_DIR/isceplus2026_MacOS.yml"
    sed -i '' '/- isce2/ s/^/# /' "$YML_DIR/isceplus2026_MacOS.yml"
    sed -i '' '/- pv/ s/^/# /' "$YML_DIR/isceplus2026_MacOS.yml"  # pv: brew install pv
    sed -i '' '/- whirlwind-insar/ s/^/# /' "$YML_DIR/isceplus2026_MacOS.yml"
    mamba env create -f "$YML_DIR/isceplus2026_MacOS.yml" --yes
else
    mamba env create -f "$YML_DIR/isceplus2026.yml" --yes
fi

conda activate earthscope-insar 2>/dev/null || conda activate "$ENV_NAME"

###  Reduce miniforge3 directory size #################
rm -rf tools/miniforge3/pkgs

echo "Running of install_isceplus_env.bash DONE"
