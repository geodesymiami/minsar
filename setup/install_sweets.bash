#!/usr/bin/env bash
set -eo pipefail

### Install python #########################
git clone https://github.com/isce-framework/sweets.git tools/sweets && cd tools/sweets
pixi install
pixi shell

echo "sweets installation DONE"
