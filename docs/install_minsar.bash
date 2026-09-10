git clone git@github.com:geodesymiami/minsar.git
cd minsar || exit 1
env -i HOME="$HOME" PATH="$HOME/.pixi/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin" SHELL=/bin/bash SCRATCH="$SCRATCH" USER=circleci bash --noprofile --norc <<'EOF'

set -Eeuo pipefail
trap 'echo
      echo "============================================================"
      echo "ERROR"
      echo "Script : ${BASH_SOURCE[0]}"
      echo "Line   : ${LINENO}"
      echo "Command: ${BASH_COMMAND}"
      echo "Status : $?"
      echo "============================================================"
      ' ERR
run_step () {
    echo "============================================================"
    echo "RUNNING: $1"
    echo "============================================================"
    "$1"
}

run_step ./setup/install_python.bash
run_step ./setup/install_tools.bash
run_step ./setup/install_minsar_env.bash
run_step ./setup/install_additions.bash
run_step ./setup/install_sweets_env.bash
run_step ./setup/install_disp-s1_env.bash
run_step ./setup/install_credential_files.bash
run_step ./setup/setup_orbit_dirs.bash
echo
echo "============================================================"
echo "ALL INSTALLATION STEPS COMPLETED SUCCESSFULLY"
echo "============================================================"
EOF
