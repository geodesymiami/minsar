git clone git@github.com:geodesymiami/minsar.git
cd minsar || exit 1
env -i HOME="$HOME" PATH="$HOME/.pixi/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin" SHELL=/bin/bash SCRATCH="$SCRATCH" WORK2="$WORK2" USER=circleci bash --noprofile --norc <<'EOF'

set -Eeuo pipefail
CURRENT_STEP="(before first step)"
# Capture $? first: later echo in the trap would reset it to 0.
# This here-doc runs as bash stdin, so BASH_SOURCE/LINENO are "main"/run_step — print the step name instead.
trap 'status=$?
      echo
      echo "============================================================"
      echo "ERROR: installation failed"
      echo "Failed step: ${CURRENT_STEP}"
      echo "Command    : ${BASH_COMMAND}"
      echo "Status     : ${status}"
      echo "============================================================"
      ' ERR
run_step () {
    CURRENT_STEP="$1"
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
