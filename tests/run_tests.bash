#!/usr/bin/env bash
#
# Test runner for minsar project.
# Runs from project root. Use positional argument to run a specific genre.
#
# Usage: ./run_tests.bash [GENRE] [OPTIONS]
#
# GENRE (positional, first non-option arg):
#   all                  Run all tests (default)
#   python               Python (unittest) tests
#   bash                 Bash workflow tests
#   make_zero_elevation  make_zero_elevation_dem Python tests
#   geoid                Miami geoid height test only (test_miami_geoid_height_sensible)
#
# Options:
#   --help, -h   Show this help and list all available tests
#   --verbose,-v Verbose output
#
# Exit codes: 0 = all passed, 1 = one or more failed
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$SCRIPT_DIR/tests"
CONDA_ENV="${MINSAR_CONDA_ENV:-minsar}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

GENRE="all"
VERBOSE=false

#######################################
# Help
#######################################

show_help() {
    cat << EOF
Usage: ./run_tests.bash [GENRE] [OPTIONS]

Test runner for minsar. Runs from project root: $SCRIPT_DIR

GENRE (positional, first non-option argument):
  all                  Run all tests (default)
  python               Python (unittest) tests
  bash                 Bash workflow tests
  make_zero_elevation  make_zero_elevation_dem module tests
  geoid                Miami geoid height test only (verifies PROJ/EGM96)

Options:
  --help, -h    Show this help
  --verbose, -v Verbose output

Available tests:
  Python:
    - minsar.utils.tests.test_system_utils
    - minsar.utils.tests.test_make_zero_elevation_dem

  Bash:
    - tests/test_run_workflow.bash
    - tests/test_submit_jobs.bash
    - tests/test_sbatch_conditional.bash

Examples:
  ./run_tests.bash                    # Run all tests
  ./run_tests.bash python             # Run Python tests
  ./run_tests.bash bash               # Run Bash tests
  ./run_tests.bash geoid              # Run Miami geoid test only
  ./run_tests.bash make_zero_elevation -v

Exit codes: 0 = passed, 1 = failed
EOF
}

#######################################
# Runners
#######################################

run_all() {
    "$SCRIPT_DIR/run_all_tests.bash" ${VERBOSE:+--verbose}
}

run_python() {
    cd "$SCRIPT_DIR" || exit 1
    local verbosity=""
    $VERBOSE && verbosity="-v"
    conda run -n "$CONDA_ENV" python -m unittest discover -s minsar/utils/tests -p "test_*.py" $verbosity
}

run_bash() {
    bash "$TESTS_DIR/run_bash_tests.bash"
}

run_make_zero_elevation() {
    cd "$SCRIPT_DIR" || exit 1
    local verbosity=""
    $VERBOSE && verbosity="-v"
    conda run -n "$CONDA_ENV" python -m unittest minsar.utils.tests.test_make_zero_elevation_dem $verbosity
}

run_geoid() {
    cd "$SCRIPT_DIR" || exit 1
    local verbosity=""
    $VERBOSE && verbosity="-v"
    conda run -n "$CONDA_ENV" python -m unittest minsar.utils.tests.test_make_zero_elevation_dem.TestCalculateGeoidHeight.test_miami_geoid_height_sensible $verbosity
}

#######################################
# Main
#######################################

# Parse args: collect options, first non-option is GENRE
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            show_help
            exit 0
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        -*)
            echo "Unknown option: $1" >&2
            show_help
            exit 1
            ;;
        *)
            GENRE="$1"
            shift
            break
            ;;
    esac
done

cd "$SCRIPT_DIR" || exit 1

case "$GENRE" in
    all)
        run_all
        ;;
    python)
        run_python
        ;;
    bash)
        run_bash
        ;;
    make_zero_elevation|zero_elevation)
        run_make_zero_elevation
        ;;
    geoid)
        run_geoid
        ;;
    *)
        echo "Unknown genre: $GENRE" >&2
        echo "" >&2
        show_help
        exit 1
        ;;
esac
