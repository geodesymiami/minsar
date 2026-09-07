#!/usr/bin/env bash
# Clone ISCE3/OPERA repos and install sweets via pixi (idempotent clones).
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"
export MINSAR_HOME="${MINSAR_HOME:-${REPO_ROOT}}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    helptext="
    usage: install_isce3.bash

    Clone COMPASS, disp-s1, OPERA_Applications, dolphin, sweets; pixi install sweets;
    optionally stage the sweets pixi env.

    Examples:
        ./setup/install_isce3.bash
    "
    echo -e "$helptext"
    exit 0
fi

clone_repo() {
    local url="$1"
    local dest="$2"
    if [[ -e "$dest" ]]; then
        echo "skip clone (exists): $dest"
        return 0
    fi
    git clone "$url" "$dest"
}

### Install #########################
clone_repo git@github.com:opera-adt/COMPASS.git tools/COMPASS
clone_repo git@github.com:opera-adt/disp-s1.git tools/disp-s1
clone_repo git@github.com:OPERA-Cal-Val/OPERA_Applications.git tools/OPERA_Applications
clone_repo git@github.com:isce-framework/dolphin.git tools/dolphin

# chttps://github.com/scottstanie/opera-utils.git@develop-scott"
if [[ -e tools/sweets ]]; then
    echo "skip clone (exists): tools/sweets"
else
    git clone https://github.com/isce-framework/sweets.git tools/sweets
fi
(
    cd tools/sweets
    pixi install
    pixi upgrade asf_search
)

echo "sweets installation DONE"

if [[ -f "${MINSAR_HOME}/minsar/scripts/stage_sweets_pixi_env.bash" ]]; then
    "${MINSAR_HOME}/minsar/scripts/stage_sweets_pixi_env.bash"
fi

echo ""
echo "Running of install_isce3.bash DONE"
echo ""
