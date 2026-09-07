#!/usr/bin/env bash
# Build SNAPHU (if needed) and link MinSAR additions into MintPy/MiaplPy/ISCE2.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"
MINSAR_HOME="${REPO_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    helptext="
    usage: install_additions.bash

    Install SNAPHU under tools/ and symlink additions/ into MintPy, MiaplPy, and ISCE2.

    Examples:
        ./setup/install_additions.bash
    "
    echo -e "$helptext"
    exit 0
fi

###  Install SNAPHU #################
if [[ -x tools/snaphu-v2.0.7/bin/snaphu ]]; then
    echo "skip SNAPHU build (exists): tools/snaphu-v2.0.7/bin/snaphu"
else
    wget --no-check-certificate https://web.stanford.edu/group/radar/softwareandlinks/sw/snaphu/snaphu-v2.0.7.tar.gz -P tools
    tar -xvf tools/snaphu-v2.0.7.tar.gz -C tools
    perl -pi -e 's/\/usr\/local/\$(PWD)\/snaphu-v2.0.7/g' tools/snaphu-v2.0.7/src/Makefile
    if [[ "$(uname)" == "Linux" ]]; then
        perl -pi -e 's/-arch\s+\S+\s+//g' tools/snaphu-v2.0.7/src/Makefile
    fi
    make -C tools/snaphu-v2.0.7/src
fi

### Adding not-commited MintPy fixes
ln -sf $MINSAR_HOME/additions/mintpy/plot_network.py $MINSAR_HOME/tools/MintPy/src/mintpy
ln -sf $MINSAR_HOME/additions/mintpy/save_hdfeos5.py $MINSAR_HOME/tools/MintPy/src/mintpy
ln -sf $MINSAR_HOME/additions/mintpy/cli/save_hdfeos5.py $MINSAR_HOME/tools/MintPy/src/mintpy/cli
ln -sf $MINSAR_HOME/additions/mintpy/geocode_hdfeos5.py $MINSAR_HOME/tools/MintPy/src/mintpy
ln -sf $MINSAR_HOME/additions/mintpy/cli/geocode.py $MINSAR_HOME/tools/MintPy/src/mintpy/cli
ln -sf $MINSAR_HOME/additions/mintpy/cli/geocode_orig.py $MINSAR_HOME/tools/MintPy/src/mintpy/cli
ln -sf $MINSAR_HOME/additions/mintpy/save_explorer.py $MINSAR_HOME/tools/MintPy/src/mintpy
ln -sf $MINSAR_HOME/additions/mintpy/cli/save_explorer.py $MINSAR_HOME/tools/MintPy/src/mintpy/cli
ln -sf $MINSAR_HOME/additions/mintpy/save_qgis.py $MINSAR_HOME/tools/MintPy/src/mintpy
ln -sf $MINSAR_HOME/additions/mintpy/cli/save_qgis.py $MINSAR_HOME/tools/MintPy/src/mintpy/cli

### Adding not-committed MiaplPy fixes (for the first Sara said she will do it; the second is wrongly out-commented isce imports)
ln -sf $MINSAR_HOME/additions/miaplpy/prep_slc_isce.py $MINSAR_HOME/tools/MiaplPy/src/miaplpy/prep_slc_isce.py
ln -sf $MINSAR_HOME/additions/miaplpy/unwrap_ifgram.py $MINSAR_HOME/tools/MiaplPy/src/miaplpy/unwrap_ifgram.py
ln -sf $MINSAR_HOME/additions/miaplpy/utils.py $MINSAR_HOME/tools/MiaplPy/src/miaplpy/objects/utils.py
ln -sf $MINSAR_HOME/additions/miaplpy/miaplpyApp_auto.cfg $MINSAR_HOME/tools/MiaplPy/src/miaplpy/defaults/miaplpyApp_auto.cfg
ln -sf $MINSAR_HOME/additions/miaplpy/miaplpyApp.py $MINSAR_HOME/tools/MiaplPy/src/miaplpy/miaplpyApp.py

### Adding ISCE fixes and copying checked-out ISCE version (the latest) into miniforge directory ###
if [[ "$(uname)" == "Linux" ]]; then
:
python_version="python$(${MINSAR_HOME}/tools/miniforge3/envs/minsar/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
ISCE_HOME="$MINSAR_HOME/tools/miniforge3/envs/minsar/lib/$python_version/site-packages/isce"
##cp -p additions/isce/logging.conf "$ISCE_HOME/defaults/logging"
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/topsStack/FilterAndCoherence.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/topsStack/FilterAndCoherence.py
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/stripmapStack/prepRawCSK.py  $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/stripmapStack/prepRawCSK.py
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/stripmapStack/unpackFrame_TSX.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/stripmapStack/unpackFrame_TSX.py
ln -sf $MINSAR_HOME/additions/isce2/contrib/demUtils/demstitcher/DemStitcher.py "$ISCE_HOME/components/contrib/demUtils/DemStitcher.py"
ln -sf $MINSAR_HOME/additions/isce2/components/isceobj/Sensor/TOPS/Sentinel1.py "$ISCE_HOME/components/isceobj/Sensor/TOPS/Sentinel1.py"
# patches for single burst:
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/topsStack/mergeBursts.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/topsStack/mergeBursts.py
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/topsStack/generateIgram.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/topsStack/generateIgram.py
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/topsStack/overlap_withDEM.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/topsStack/overlap_withDEM.py
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/topsStack/estimateRangeMisreg.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/topsStack/estimateRangeMisreg.py
# TEMPORARY (isce2<2.6.4): Copernicus Data Space fetchOrbit. REMOVE when conda-lock pins isce2>=2.6.4.
ln -sf "$MINSAR_HOME/tools/isce2/contrib/stack/topsStack/fetchOrbit.py" "$MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/topsStack/fetchOrbit.py"

#FA 1/2026: this should be done for all modification and remove copying tools/isce2/contrib/stack/* into share/isce2
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/stripmapStack/unpackFrame_ENV_raw.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/stripmapStack
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/stripmapStack/unpackFrame_ENV.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/stripmapStack
ln -sf $MINSAR_HOME/additions/isce2/contrib/stack/stripmapStack/referenceStackCopy.py $MINSAR_HOME/tools/miniforge3/envs/minsar/share/isce2/stripmapStack
fi

echo ""
echo "Running of install_additions.bash DONE"
echo ""
