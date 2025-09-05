#!/usr/bin/env bash
set -eo pipefail

### Source the environment variables  #################
export MINSAR_HOME=$PWD
source setup/platforms_defaults.bash;
source setup/environment.bash;

### Create orbits and aux directories
echo "mkdir -p $SENTINEL_ORBITS $SENTINEL_AUX"
mkdir -p $SENTINEL_ORBITS $SENTINEL_AUX
ls -d $SENTINEL_ORBITS $SENTINEL_AUX

echo ""
echo "Done testing or creating orbit directories"
echo ""
