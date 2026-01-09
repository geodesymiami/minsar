#!/usr/bin/env bash
set -eo pipefail

### git clone the code   #################
git clone git@github.com:insarlab/MintPy.git tools/MintPy
git clone git@github.com:insarlab/MiaplPy.git tools/MiaplPy
git clone git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts
git clone git@github.com:geodesymiami/insarmaps.git tools/insarmaps
git clone git@github.com:isce-framework/isce2.git tools/isce2
git clone git@github.com:geodesymiami/MimtPy.git tools/MimtPy
git clone git@github.com:geodesymiami/geodmod.git tools/geodmod
git clone https://gitlab.com/earthscope/public/sar/ssara_client.git tools/ssara_client
git clone git@github.com:TACC/launcher.git tools/launcher
git clone git@github.com:geodesymiami/PlotData tools/PlotData
git clone git@github.com:geodesymiami/PlotDataFA tools/PlotDataFA
git clone git@github.com:geodesymiami/precip tools/Precip
git clone git@github.com:geodesymiami/precip_web tools/Precip_web
git clone git@github.com:geodesymiami/precip_cron tools/Precip_cron
git clone git@github.com:scottstanie/sardem tools/sardem
git clone git@github.com:luhipi/sarvey tools/sarvey
git clone git@github.com:falkamelung/sarplotter-main.git tools/sarplotter-main
#git clone git@github.com:geodesymiami/SourceInversion.git tools/SourceInversion
#git clone https://github.com/EliTras/VSM.git tools/SourceInversion/src/VSM
#touch tools/SourceInversion/src/VSM/__init__.py

### Install code into minsar environment  #################
if [[ "$(uname)" == "Darwin" ]]; then
    cp minsar_env.yml minsar_env_macOS.yml
    sed -i '' '/- isce/ s/^/# /' minsar_env_MacOS.yml
    sed -i '' '/gdal$/ s/gdal$/gdal=3.6\*/' minsar_env_MacOS.yml                  # only gdal=3.6 ships with the built-in postgresQL
    sed -i '' '/- pymaxflow/ s/^/# /' minsar_env_MacOS.yml                        # out-comment conda pymaxflow installation
    sed -i '' '/#- pymaxflow/ s/#- pymaxflow/- pymaxflow/' minsar_env_MacOS.yml   # activate pip pymaxflow installation
fi


if [[ "$(uname)" == "Linux" ]]; then
    if [[ -f conda-lock.yml ]]; then
       echo "Lock file conda-lock.yml found. Using it for installation"
       tools/miniforge3/bin/mamba create --prefix tools/miniforge3/envs/minsar --file conda-lock.yml --yes
    else
       tools/miniforge3/bin/mamba --verbose env create -f minsar_env.yml --yes
    fi
elif [[ "$(uname)" == "Darwin" ]]; then    # FA 9/2025 lockfile for macOS did not work as pip failed to build wheels (need to try pixi)
    tools/miniforge3/bin/mamba --verbose env create -f minsar_env_MacOS.yml --yes
fi

source tools/miniforge3/etc/profile.d/conda.sh
set +u         # needed for circleCI
conda activate minsar

pip install -e tools/MintPy
pip install -e tools/MiaplPy
pip install -e tools/sardem
pip install -e tools/sarvey[dev] --no-deps

###  Reduce miniforge3 directory size #################
rm -rf tools/miniforge3/pkgs

###  Install SNAPHU #################
wget --no-check-certificate  https://web.stanford.edu/group/radar/softwareandlinks/sw/snaphu/snaphu-v2.0.5.tar.gz  -P tools
tar -xvf tools/snaphu-v2.0.5.tar.gz -C tools
perl -pi -e 's/\/usr\/local/\$(PWD)\/snaphu-v2.0.5/g' tools/snaphu-v2.0.5/src/Makefile
cc=tools/miniforge3/bin/cc
make -C tools/snaphu-v2.0.5/src

### Adding not-commited MintPy fixes
ln -sf $PWD/additions/mintpy/plot_network.py $PWD/tools/MintPy/src/mintpy
ln -sf $PWD/additions/mintpy/save_hdfeos5.py $PWD/tools/MintPy/src/mintpy
ln -sf $PWD/additions/mintpy/cli/save_hdfeos5.py $PWD/tools/MintPy/src/mintpy/cli
#ln -sf $MINSAR_HOME/additions/mintpy/plot_network.py $MINTPY_HOME/src/mintpy
#ln -sf $MINSAR_HOME/additions/mintpy/save_hdfeos5.py $MINTPY_HOME/src/mintpy
#ln -sf $MINSAR_HOME/additions/mintpy/cli/save_hdfeos5.py $MINTPY_HOME/src/mintpy/cli
#cp -p additions/mintpy/plot_network.py tools/MintPy/src/mintpy
#cp -p additions/mintpy/save_hdfeos5.py tools/MintPy/src/mintpy/
#cp -p additions/mintpy/cli/save_hdfeos5.py tools/MintPy/src/mintpy/cli/

### Adding not-committed MiaplPy fixes (for the first Sara said she will do it; the second is wrongly out-commented isce imports)
cp -p additions/miaplpy/prep_slc_isce.py tools/MiaplPy/src/miaplpy
cp additions/miaplpy/unwrap_ifgram.py tools/MiaplPy/src/miaplpy
cp additions/miaplpy/utils.py tools/MiaplPy/src/miaplpy/objects

### Adding ISCE fixes and copying checked-out ISCE version (the latest) into miniforge directory ###
if [[ "$(uname)" == "Linux" ]]; then
:
##cp -p additions/isce/logging.conf tools/miniforge3/envs/minsar/lib/python3.10/site-packages/isce/defaults/logging
cp -p additions/isce2/contrib/stack/topsStack/FilterAndCoherence.py tools/isce2/contrib/stack/topsStack
cp -p additions/isce2/contrib/stack/stripmapStack/prepRawCSK.py tools/isce2/contrib/stack/stripmapStack
cp -p additions/isce2/contrib/stack/stripmapStack/unpackFrame_TSX.py tools/isce2/contrib/stack/stripmapStack
cp -p additions/isce2/contrib/demUtils/demstitcher/DemStitcher.py tools/isce2/contrib/demUtils/demstitcher
cp -p additions/isce2/components/isceobj/Sensor/TOPS/Sentinel1.py tools/isce2/components/isceobj/Sensor/TOPS

cp -p additions/isce2/components/isceobj/Sensor/TOPS/Sentinel1.py tools/miniforge3/envs/minsar/lib/python3.10/site-packages/isce/components/isceobj/Sensor/TOPS/Sentinel1.py

### Copying ISCE fixes into miniforge directory ###
cp -r tools/isce2/contrib/stack/* tools/miniforge3/envs/minsar/share/isce2
cp -r tools/isce2/components/isceobj/Sensor/TOPS tools/miniforge3/envs/minsar/share/isce2
cp tools/isce2/components/isceobj/Sensor/TOPS/TOPSSwathSLCProduct.py tools/miniforge3/envs/minsar/lib/python3.??/site-packages/isce/components/isceobj/Sensor/TOPS
cp tools/isce2/contrib/demUtils/demstitcher/DemStitcher.py  tools/miniforge3/envs/minsar/lib/python3.??/site-packages/isce/components/contrib/demUtils

#FA 1/2026: this should be done for all modification and remove copying tools/isce2/contrib/stack/* into share/isce2
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/stripmapStack/unpackFrame_ENV_raw.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/stripmapStack
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/stripmapStack/unpackFrame_ENV.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/stripmapStack
fi

echo ""
echo "Running of install_minsar.bash DONE"
echo ""
