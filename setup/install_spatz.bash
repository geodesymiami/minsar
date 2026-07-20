#!/usr/bin/env bash
set -eo pipefail

### git clone the code   #################
git clone git@github.com:Andreas-Piter/SpaTZ.git tools/SpaTZ
pip install tools/SpaTZ
