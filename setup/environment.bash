#!/usr/bin/env bash
if [[ $- != *i* ]]; then
  # non-interactive: turn on strict error checking
  set -euo pipefail
fi

echo "sourcing ${MINSAR_HOME}/setup/environment.bash ..."
#####################################
# Setting the environment (don't modify)
# check for required variables
: "${MINSAR_HOME:?ERROR: MINSAR_HOME is a required variable}"

source ${MINSAR_HOME}/setup/platforms_defaults.bash

: "${SCRATCHDIR:?ERROR: SCRATCHDIR is a required variable}"

# set required variables to standard values if not given
export JOBSCHEDULER="${JOBSCHEDULER:-SLURM}"
export QUEUENAME="${QUEUENAME:-normal}"
export WORKDIR="${WORKDIR:-$SCRATCHDIR}"

#  set customizable variables to defaults if not given
export USER_PREFERRED="${USER_PREFERRED:-$USER}"
export NOTIFICATIONEMAIL="${NOTIFICATIONEMAIL:-${USER_PREFERRED}@rsmas.miami.edu}"
export JOBSCHEDULER_PROJECTNAME="${JOBSCHEDULER_PROJECTNAME:-insarlab}"
export INSARMAPSHOST_RECENTDATA="${INSARMAPSHOST_RECENTDATA:-insarmaps.miami.edu}"
export INSARMAPSHOST_OLDDATA="${INSARMAPSHOST_OLDDATA:-insarmaps.miami.edu}"

export SENTINEL_ORBITS="${SENTINEL_ORBITS:-$WORKDIR/S1orbits}"
export SENTINEL_AUX="${SENTINEL_AUX:-$WORKDIR/S1aux}"
export WEATHER_DIR="${WEATHER_DIR:-$WORKDIR/WEATHER}"
export PRECIP_DIR="${PRECIP_DIR:-$SCRATCHDIR/gpm_data}"
export PRECIPPRODUCTS_DIR="${PRECIPPRODUCTS_DIR:-$SCRATCHDIR/precip_products}"
export TESTDATA_ISCE="${TESTDATA_ISCE:-$WORKDIR/TESTDATA_ISCE}"

############ FOR PROCESSING  #########
python_version="python$(${MINSAR_HOME}/tools/miniforge3/envs/minsar/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
export SSARAHOME=${MINSAR_HOME}/tools/ssara_client
export ISCE_HOME=${MINSAR_HOME}/tools/miniforge3/envs/minsar/lib/$python_version/site-packages/isce
export ISCE_STACK=${MINSAR_HOME}/tools/miniforge3/envs/minsar/share/isce2
export MINTPY_HOME=${MINSAR_HOME}/tools/MintPy
export MIAPLPY_HOME=${MINSAR_HOME}/tools/MiaplPy
export MIMTPY_HOME=${MINSAR_HOME}/tools/MimtPy
export PLOTDATA_HOME=${MINSAR_HOME}/tools/PlotData
export PRECIP_HOME=${MINSAR_HOME}/tools/Precip
export PRECIP_WEB_HOME=${MINSAR_HOME}/tools/Precip_web/precip_web
export SARVEY_HOME=${MINSAR_HOME}/tools/sarvey
export SOURCEINVERSION_HOME=${MINSAR_HOME}/tools/SourceInversion
export GBIS_HOME=${MINSAR_HOME}/tools/GBIS
export JOBDIR=${WORKDIR}/JOBS
############ FOR MODELLING  ###########
export MODELDATA=${WORKDIR}/MODELDATA
export GEODMOD_INFILES=${WORKDIR}/infiles/${USER_PREFERRED}/GEODMOD_INFILES
export GEODMOD_HOME=${MINSAR_HOME}/tools/geodmod
export GEODMOD_TESTDATA=${WORKDIR}/TESTDATA_GEODMOD
export GBIS_TESTDATA=${WORKDIR}/TESTDATA_GBIS
export GEODMOD_TESTBENCH=${SCRATCHDIR}/GEODMOD_TESTBENCH
export GBIS_INFILES=${WORKDIR}/infiles/${USER_PREFERRED}/GBIS_INFILES

############## Envisat ##############
export VOR_DIR="$WORKDIR/Envisat_DORIS/VOR_DIR"
export INS_DIR="$WORKDIR/ASAR_Auxiliary_Files/ASA_INS_AX"

###########  USEFUL VARIABLES  #########
export SAMPLESDIR=${MINSAR_HOME}/samples
export DEMDIR=${WORKDIR}/DEMDIR
export TEMPLATES=${WORKDIR}/infiles/${USER_PREFERRED}/TEMPLATES
export TE=${TEMPLATES}

############## DASK ##############
export DASK_CONFIG=${MINTPY_HOME}/src/mintpy/defaults/

############## LAUNCHER ##############
export LAUNCHER_DIR=${MINSAR_HOME}/tools/launcher
export LAUNCHER_PLUGIN_DIR=${LAUNCHER_DIR}/plugins
export LAUNCHER_RMI=${JOBSCHEDULER}
export LAUNCHER_SCHED=block   ## could be one of: dynamic, interleaved, block

##############  PYTHON  ##############
# pixi sweets (s.bs): keep pixi prefix for Python/PROJ/GDAL. minsar conda (s.bw2) otherwise.
if [[ "${PIXI_IN_SHELL:-}" == "1" && "${PIXI_PROJECT_NAME:-}" == "sweets" ]]; then
    echo "pixi sweets env detected: PROJ/GDAL from ${CONDA_PREFIX}"
    export PYTHONPATH="${MINSAR_HOME}"
else
    export CONDA_PREFIX=${MINSAR_HOME}/tools/miniforge3/envs/minsar
    export CONDA_ENVS_PATH=${CONDA_PREFIX}/envs
    export PYTHONPATH=${PYTHONPATH-""}
    export PYTHONPATH=${MINTPY_HOME}/mintpy:${PYTHONPATH}       # ensures that pip -e installed MintPy is used
    export PYTHONPATH=${PYTHONPATH}:${MIMTPY_HOME}
    export PYTHONPATH=${PYTHONPATH}:${ISCE_HOME}:${ISCE_HOME}/components
    export PYTHONPATH=${PYTHONPATH}:${ISCE_STACK}
    export PYTHONPATH=${PYTHONPATH}:${MINSAR_HOME}
    export PYTHONPATH=${PYTHONPATH}:${MINSAR_HOME}/tools/PyAPS
    export PYTHONPATH=${PYTHONPATH}:${MINSAR_HOME}/tools/PySolid
    export PYTHONPATH=${PYTHONPATH}:${PLOTDATA_HOME}/src
    export PYTHONPATH=${PYTHONPATH}:${PRECIP_HOME}/src
    export PYTHONPATH=${PYTHONPATH}:${SARVEY_HOME}
    export PYTHONPATH=${PYTHONPATH}:${SARVEY_HOME}/sarvey
    export PYTHONPATH=${SOURCEINVERSION_HOME}/src:${SOURCEINVERSION_HOME}/src/VSM/VSM:$PYTHONPATH
    export PYTHONPATH=${PYTHONPATH}:${MINSAR_HOME}/tools/sarplotter-main
    export PYTHONWARNINGS="ignore"
fi
export PROJ_LIB="${CONDA_PREFIX}/share/proj"
export PROJ_DATA="${CONDA_PREFIX}/share/proj"
export GDAL_DATA="${CONDA_PREFIX}/share/gdal"

#####################################
############  PATH  #################
#####################################
export PATH=${PATH}:${SSARAHOME}
export PATH=${PATH}:${MINSAR_HOME}/minsar/bin
export PATH=${PATH}:${MINSAR_HOME}/minsar/src/minsar/cli
export PATH=${PATH}:${MINSAR_HOME}/minsar
export PATH=${PATH}:${MINSAR_HOME}/minsar/insarmaps_utils
export PATH=${PATH}:${MINSAR_HOME}/minsar/utils
export PATH=${PATH}:${MINSAR_HOME}/minsar/scripts
export PATH=${PATH}:${MINSAR_HOME}/tests
export PATH=${PATH}:${MINTPY_HOME}/src/mintpy/legacy         # for add_attribute.py
export PATH=${PATH}:${MIAPLPY_HOME}/src/miaplpy
export PATH=${PATH}:${SOURCEINVERSION_HOME}/src/cli
export PATH=${PATH}:${PLOTDATA_HOME}/src/plotdata/cli
export PATH=${PATH}:${PLOTDATA_HOME}/scripts
export PATH=${PATH}:${PRECIP_HOME}/src/precip/cli
export PATH=${PATH}:${MIMTPY_HOME}/mimtpy
export PATH=${PATH}:${SARVEY_HOME}/sarvey
export PATH=${PATH}:${MINSAR_HOME}/tools/snaphu-v2.0.7/bin
export PATH=${PATH}:${MINSAR_HOME}/tools/insarmaps_scripts
export PATH=${PATH}:${MINSAR_HOME}/tools/emirhan_insarmaps_utils
export PATH=${PATH}:${MINSAR_HOME}/tools/autoencoder
export PATH=${PATH}:${MINSAR_HOME}/tools/etna-slider/comparison/scripts
export PATH=${PATH}:${MINSAR_HOME}/tools/MakeTemplate/src/maketemplate/cli
export PATH=${PATH}:${MINSAR_HOME}/tools/S4I/viewer4falk
export PATH=${PATH}:~/.pixi/bin
export PATH=${ISCE_HOME}/applications:${ISCE_HOME}/bin:${ISCE_STACK}:${ISCE_STACK}/topsStack:${PATH};
export PATH=${CONDA_PREFIX}/bin:${PATH}
export PATH="${MINSAR_HOME}/tools/sarplotter-main/app:$PATH"
if [ -d /var/www/VolcDef_web ]; then
    export PATH=/var/www/VolcDef_web/volcdef_web:${PATH}
else
    export PATH=${MINSAR_HOME}/tools/VolcDef_web/volcdef_web:${PATH}
fi

export PATH="${PATH}${MATLAB_HOME:+:${MATLAB_HOME}/bin}"

unset LD_LIBRARY_PATH
export LD_RUN_PATH=${CONDA_PREFIX}/lib

########## bash functions #########
source $MINSAR_HOME/minsar/lib/minsarApp_specifics.sh
source $MINSAR_HOME/minsar/lib/common_helpers.sh

if [ -n "${prompt:-}" ]; then
    echo "MINSAR_HOME:" ${MINSAR_HOME}
    echo "CONDA_PREFIX:   " ${CONDA_PREFIX}
    echo "SSARAHOME:      " ${SSARAHOME}
fi
########## Your personal aliasses/functions #########
if [[ -f ~/accounts/remote_hosts.bash ]]; then
    source ~/accounts/remote_hosts.bash
fi
if [[ -f ~/accounts/alias.bash ]]; then
   source ~/accounts/alias.bash
fi
if [[ -f ~/accounts/login_alias.bash ]]; then
   source ~/accounts/login_alias.bash
fi

# Avoid Cursor/VS Code prompt hook error in subshells or SSH.
if [[ -n "${PROMPT_COMMAND:-}" ]] && ! type __vsc_prompt_cmd_original &>/dev/null; then
  unset PROMPT_COMMAND
fi
