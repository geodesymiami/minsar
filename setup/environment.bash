echo "sourcing ${BASH_SOURCE[0]#$MINSAR_HOME/} ..."
#####################################
# Setting the environment (don't modify)
# check for required variables
[ -z $MINSAR_HOME ] && echo ERROR: MINSAR_HOME is required variable && return
[ -z $SCRATCHDIR ] && echo ERROR: SCRATCHDIR is required variable && return

# set required variables to standard values if not given
[ -z $JOBSCHEDULER ] && export JOBSCHEDULER=SLURM
[ -z $QUEUENAME ] && export QUEUENAME=normal
[ -z ${WORKDIR} ] && export WORKDIR=$SCRATCHDIR

[ -f ~/accounts/remote_hosts.bash ] && source ~/accounts/remote_hosts.bash

#  set customizable variables to defaults if not given
[ -z ${USER_PREFERRED} ] && export USER_PREFERRED=$USER
[ -z ${NOTIFICATIONEMAIL} ] && export NOTIFICATIONEMAIL=${USER_PREFERRED}@rsmas.miami.edu
[ -z ${JOBSHEDULER_PROJECTNAME} ] && export JOBSHEDULER_PROJECTNAME=insarlab
[ -z ${SENTINEL_ORBITS} ] && export SENTINEL_ORBITS=${WORKDIR}/S1orbits
[ -z ${SENTINEL_AUX} ] && export SENTINEL_AUX=${WORKDIR}/S1aux
[ -z ${WEATHER_DIR} ] && export WEATHER_DIR=${WORKDIR}/WEATHER
[ -z ${PRECIP_DIR} ] && export PRECIP_DIR=${SCRATCHDIR}/gpm_data
[ -z ${PRECIPPRODUCTS_DIR} ] && export PRECIPPRODUCTS_DIR=${SCRATCHDIR}/precip_products
[ -z ${TESTDATA_ISCE} ] && export TESTDATA_ISCE=${WORKDIR}/TESTDATA_ISCE

############ FOR PROCESSING  #########
python_version=$(echo "python3.$(${MINSAR_HOME}/tools/miniforge3/bin/python --version | cut -d. -f2)")        # e.g. python3.10
export SSARAHOME=${MINSAR_HOME}/tools/SSARA
export ISCE_HOME=${MINSAR_HOME}/tools/miniforge3/lib/$python_version/site-packages/isce
export ISCE_STACK=${MINSAR_HOME}/tools/miniforge3/share/isce2
export MINTPY_HOME=${MINSAR_HOME}/tools/MintPy
export MIAPLPY_HOME=${MINSAR_HOME}/tools/MiaplPy
export MIMTPY_HOME=${MINSAR_HOME}/tools/MimtPy
export PLOTDATA_HOME=${MINSAR_HOME}/tools/plotdata
export PRECIP_HOME=${MINSAR_HOME}/tools/Precip
export PRECIP_CRON_HOME=${MINSAR_HOME}/tools/Precip_cron
export SARVEY_HOME=${MINSAR_HOME}/tools/sarvey
export SARDEM_HOME=${MINSAR_HOME}/tools/sardem
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
export PYTHON3DIR=${MINSAR_HOME}/tools/miniforge3
export CONDA_ENVS_PATH=${PYTHON3DIR}/envs
export CONDA_PREFIX=${PYTHON3DIR}
export PROJ_LIB=${PYTHON3DIR}/share/proj:${PYTHON3DIR}/lib/python3.??/site-packages/pyproj/proj_dir/share/proj
export GDAL_DATA=${PYTHON3DIR}/share/gdal

export PYTHONPATH=${PYTHONPATH-""}
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
export PYTHONPATH=${PYTHONPATH}:${SARDEM_HOME}
#export PYTHONPATH=${PYTHONPATH}:${MINSAR_HOME}/tools      # needed for mimt. Need to talk to Sara on how to do this smarter

######### Ignore warnings ############
export PYTHONWARNINGS="ignore"

#####################################
############  PATH  #################
#####################################
export PATH=${PATH}:${SSARAHOME}
export PATH=${PATH}:${MINSAR_HOME}/minsar/cli
export PATH=${PATH}:${MINSAR_HOME}/minsar
export PATH=${PATH}:${MINSAR_HOME}/minsar/utils
export PATH=${PATH}:${MINSAR_HOME}/minsar/bin
export PATH=${PATH}:${MINTPY_HOME}/src/mintpy/cli
export PATH=${PATH}:${PLOTDATA_HOME}/src/plotdata/cli
export PATH=${PATH}:${MIAPLPY_HOME}/src/miaplpy
export PATH=${PATH}:${PRECIP_HOME}/src/precip/cli
export PATH=${PATH}:${PRECIP_CRON_HOME}
export PATH=${PATH}:${MIMTPY_HOME}/mimtpy
export PATH=${PATH}:${SARVEY_HOME}/sarvey
export PATH=${PATH}:${MINSAR_HOME}/tools/snaphu-v2.0.5/bin
export PATH=${PATH}:${MINSAR_HOME}/tools/insarmaps_scripts
export PATH=${PATH}:${MINSAR_HOME}/tools/autoencoder
export PATH=${PATH}:${PROJ_LIB}
export PATH=${PATH}:${DASK_CONFIG}
export PATH=${PATH}:${MINSAR_HOME}/tools/S4I/viewer4falk
export PATH=${ISCE_HOME}/applications:${ISCE_HOME}/bin:${ISCE_STACK}:${PATH}
export PATH=${PYTHON3DIR}/bin:${PATH}
export PATH="${MINSAR_HOME}/tools/sarvey/sarvey:$PATH"
export PATH="${MINSAR_HOME}/tools/sarplotter-main/app:$PATH"

[ "$(uname)" == "Darwin" ] && export PATH="/opt/homebrew/opt/gnu-getopt/bin:$PATH"

[ -n ${MATLAB_HOME} ] && export PATH=${PATH}:${MATLAB_HOME}/bin

unset LD_LIBRARY_PATH
export LD_RUN_PATH=${PYTHON3DIR}/lib

########## bash functions #########
source $MINSAR_HOME/minsar/lib/minsarApp_specifics.sh
source $MINSAR_HOME/minsar/lib/utils.sh
source $MINSAR_HOME/minsar/lib/common_helpers.sh

if [ -n "${prompt}" ]
then
    echo "MINSAR_HOME:" ${MINSAR_HOME}
    echo "PYTHON3DIR:     " ${PYTHON3DIR}
    echo "SSARAHOME:      " ${SSARAHOME}
fi
