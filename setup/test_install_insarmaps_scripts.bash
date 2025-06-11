#!/usr/bin/env bash
printf "First run:\n env -i HOME=$HOME PATH=/usr/bin:/bin:/sbin SHELL=/bin/bash USER=circleci bash --noprofile --norc\n"
printf "Then run ./test_install_insarmasp_scripts.bash\n"
set -eox pipefail
git clone git@github.com:geodesymiami/minsar.git ;
cd minsar
bash -x setup/install_python.bash

export MINSAR_HOME=$PWD
source setup/platforms_defaults.bash;
source setup/environment.bash;
git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts
git clone git@github.com:geodesymiami/insarmaps.git tools/insarmaps
mamba install tippecanoe mintpy --yes -c conda-forge
pip install psycopg2 pycurl

#conda list | grep numpy
#onda list | grep mintpy
#conda list | grep h5py
#conda list | grep pycurl
#conda list | grep psycopg2
