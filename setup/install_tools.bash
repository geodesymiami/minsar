#!/usr/bin/env bash
set -eo pipefail

clone_repo() {
    [[ -e "$2" ]] && echo "skip clone (exists): $2" && return 0
    git clone "$1" "$2"
}

### git clone the code   #################
clone_repo git@github.com:insarlab/MintPy.git tools/MintPy
clone_repo git@github.com:insarlab/MiaplPy.git tools/MiaplPy
clone_repo git@github.com:geodesymiami/insarmaps_scripts.git tools/insarmaps_scripts
clone_repo git@github.com:geodesymiami/insarmaps.git tools/insarmaps
clone_repo git@github.com:isce-framework/isce2.git tools/isce2
clone_repo git@github.com:geodesymiami/MimtPy.git tools/MimtPy
clone_repo git@github.com:geodesymiami/geodmod.git tools/geodmod
clone_repo https://gitlab.com/earthscope/public/sar/ssara_client.git tools/ssara_client
clone_repo git@github.com:TACC/launcher.git tools/launcher
clone_repo git@github.com:geodesymiami/PlotData tools/PlotData
clone_repo git@github.com:geodesymiami/PlotDataFA tools/PlotDataFA
clone_repo git@github.com:geodesymiami/precip tools/Precip
clone_repo git@github.com:geodesymiami/Precip_web tools/Precip_web
clone_repo git@github.com:geodesymiami/VolcDef_web tools/VolcDef_web
clone_repo git@github.com:geodesymiami/webconfig tools/webconfig
clone_repo git@github.com:geodesymiami/emirhan_insarmaps_utils.git tools/emirhan_insarmaps_utils
clone_repo git@github.com:scottstanie/sardem tools/sardem
clone_repo git@github.com:luhipi/sarvey tools/sarvey
clone_repo git@github.com:falkamelung/sarplotter-main.git tools/sarplotter-main
clone_repo git@github.com:geodesymiami/notebooks tools/notebooks
#clone_repo https://github.com/JavieraAlvarez/etna-slider tools/etna-slider
#clone_repo git@github.com:geodesymiami/SourceInversion.git tools/SourceInversion

echo "Running of install_tools.bash DONE"
