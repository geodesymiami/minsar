#!/usr/bin/env bash
set -eo pipefail

### git clone the code   #################
git clone git@github.com:isceplus/2026-isceplus.git tools/isceplus

### Install code into minsar environment  #################
if [[ "$(uname)" == "Darwin" ]]; then
    cp tools/isceplus/S07_Installing_the_course_environment_with_conda/isceplus2026.yml tools/isceplus/S07_Installing_the_course_environment_with_conda/isceplus2026_MacOS.yml
    sed -i '' '/- isce2/ s/^/# /' tools/isceplus/S07_Installing_the_course_environment_with_conda/isceplus2026_MacOS.yml
    sed -i '' '/- pv/ s/^/# /' tools/isceplus/S07_Installing_the_course_environment_with_conda/isceplus2026_MacOS.yml  # pv needs to be installed on Mac using "brew install pv"
    sed -i '' '/- whirlwind-insar/ s/^/# /' tools/isceplus/S07_Installing_the_course_environment_with_conda/isceplus2026_MacOS.yml
    mamba env create -f tools/isceplus/S07_Installing_the_course_environment_with_conda/isceplus2026_MacOS.yml
fi

mamba env create -f tools/isceplus/S07_Installing_the_course_environment_with_conda/isceplus2026.yml



source tools/miniforge3/etc/profile.d/conda.sh
set +u         # needed for circleCI
conda activate earthscope-insar

###  Reduce miniforge3 directory size #################
rm -rf tools/miniforge3/pkgs

