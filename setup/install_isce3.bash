#!/usr/bin/env bash
set -eo pipefail

### Install #########################
git clone git@github.com:opera-adt/COMPASS.git tools/COMPASS
git clone git@github.com:opera-adt/disp-s1.git tools/disp-s1
git clone git@github.com:OPERA-Cal-Val/OPERA_Applications.git tools/OPERA_Applications

# chttps://github.com/scottstanie/opera-utils.git@develop-scott"
git clone https://github.com/isce-framework/sweets.git tools/sweets && cd tools/sweets
pixi install
pixi upgrade asf_search
###pixi shell

echo "sweets installation DONE"


