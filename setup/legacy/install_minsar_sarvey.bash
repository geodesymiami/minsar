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
git clone git@github.com:geodesymiami/SSARA.git tools/SSARA
git clone git@github.com:TACC/launcher.git tools/launcher
git clone git@github.com:geodesymiami/PlotData tools/PlotData
git clone git@github.com:geodesymiami/PlotDataFA tools/PlotDataFA
git clone git@github.com:geodesymiami/precip tools/Precip
git clone git@github.com:geodesymiami/precip_web tools/Precip_web
git clone git@github.com:geodesymiami/precip_cron tools/Precip_cron
git clone git@github.com:scottstanie/sardem tools/sardem
[[ -d tools/sarvey ]] || \
  git clone git@github.com:luhipi/sarvey tools/sarvey
[[ -d tools/sarplotter-main ]] || \
   git clone git@github.com:falkamelung/sarplotter-main.git tools/sarplotter-main

#git clone git@github.com:geodesymiami/SourceInversion.git tools/SourceInversion

### Install code into minsar environment  #################
if [[ "$(uname)" == "Darwin" ]]; then sed -i '' '/isce/ s/^/# /' minsar_sarvey.yml; fi
if [[ "$(uname)" == "Darwin" ]]; then sed -i '' '/gdal$/ s/gdal$/gdal=3.6\*/' minsar_sarvey.yml; fi

tools/miniforge3/bin/mamba --verbose env create -f minsar_sarvey.yml --yes

source tools/miniforge3/etc/profile.d/conda.sh
set +u         # needed for circleCI
conda activate minsar_sarvey

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
cp -p additions/mintpy/save_hdfeos5.py tools/MintPy/src/mintpy/
cp -p additions/mintpy/cli/save_hdfeos5.py tools/MintPy/src/mintpy/cli/

### Adding not-committed MiaplPy fixes (for the first Sara said she will do it; the second is wrongly out-commented isce imports)
cp -p additions/miaplpy/prep_slc_isce.py tools/MiaplPy/src/miaplpy
cp additions/miaplpy/unwrap_ifgram.py tools/MiaplPy/src/miaplpy
cp additions/miaplpy/utils.py tools/MiaplPy/src/miaplpy/objects

### Adding ISCE fixes and copying checked-out ISCE version (the latest) into miniforge directory ###
if [[ "$(uname)" == "Linux" ]]; then
:
##cp -p additions/isce/logging.conf tools/miniforge3/envs/minsar/lib/python3.10/site-packages/isce/defaults/logging
#cp -p additions/isce2/contrib/stack/topsStack/FilterAndCoherence.py tools/isce2/contrib/stack/topsStack
#cp -p additions/isce2/contrib/stack/stripmapStack/prepRawCSK.py tools/isce2/contrib/stack/stripmapStack
#cp -p additions/isce2/contrib/stack/stripmapStack/unpackFrame_TSX.py tools/isce2/contrib/stack/stripmapStack
#cp -p additions/isce2/contrib/demUtils/demstitcher/DemStitcher.py tools/isce2/contrib/demUtils/demstitcher
#cp -p additions/isce2/components/isceobj/Sensor/TOPS/Sentinel1.py tools/isce2/components/isceobj/Sensor/TOPS

### Copying ISCE fixes into miniforge directory ###
#cp -r tools/isce2/contrib/stack/* tools/miniforge3/envs/minsar/share/isce2
#cp -r tools/isce2/components/isceobj/Sensor/TOPS tools/miniforge3/envs/minsar/share/isce2
#cp tools/isce2/components/isceobj/Sensor/TOPS/TOPSSwathSLCProduct.py tools/miniforge3/envs/minsar/lib/python3.??/site-packages/isce/components/isceobj/Sensor/TOPS
#cp tools/isce2/contrib/demUtils/demstitcher/DemStitcher.py  tools/miniforge3/envs/minsar/lib/python3.??/site-packages/isce/components/contrib/demUtils
fi

echo ""
echo "Running of install_minsar.bash DONE"
echo ""
