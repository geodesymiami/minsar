#!/bin/bash 
######### copy credentials to right place ##############

# for ssara 
characterCount=`wc -m ../3rdparty/SSARA/password_config.py`
characterCount=$(echo "${characterCount[0]%% *}")

if [[  $characterCount == 75 ]]; then
      echo "Use default password_config.py for SSARA (because existing file lacks passwords)"
      echo "Copying password_config.py into ../3rdparty/SSARA"
      cp ~/accounts/password_config.py ../3rdparty/SSARA
   else
      echo File password_config.py not empty - kept unchanged
fi

echo "Copying password_config.py into ../minsar/utils/ssara_ASF"
cp ~/accounts/password_config.py ../minsar/utils/ssara_ASF

# for dem.py 
if [[ ! -f ~/.netrc ]]; then
  echo "copying .netrc file for DEM data download into ~/.netrc"
  cp ~/accounts/netrc ~/.netrc
fi

## for pyaps 
#if (! -f 3rdparty/PyAPS/pyaps3/model.cfg) then
#      echo Copying default model.cfg for ECMWF download with PyAPS into ../3rdparty/PyAPS/pyaps3
#      cp ~/accounts/model.cfg ../3rdparty/PyAPS/pyaps3
#   else
#      echo File model.cfg exists already - kept unchanged
#endif

# for pyaps 

python_version=$(echo "python3.$(python --version | cut -d. -f2)")
model_cfg_file=$(echo "../3rdparty/miniconda3/lib/$python_version/site-packages/pyaps3/model.cfg")
if [[ ! -f $model_cfg_file ]]; then
      echo "Copying default model.cfg for ECMWF download with PyAPS into $(dirname $model_cfg_file)"
      cp ~/accounts/model.cfg $model_cfg_file
   else
      echo File model.cfg exists already - kept unchanged
fi

