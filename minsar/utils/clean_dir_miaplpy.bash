#!/usr/bin/env bash
# clean_dir_miaplpy.bash
# Clean miaplpy processing directories to allow restarting from specific steps

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

echo "sourcing ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh ..."
source ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh
echo "sourcing ${SCRIPT_DIR}/../lib/utils.sh ..."
source ${SCRIPT_DIR}/../lib/utils.sh

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Clean miaplpy processing directory to allow restarting from specific steps.

Note: Cleaning a step also removes files from all subsequent steps.
      --step 6 removes files from steps 6, 7, 8, and 9
      --step 7 removes files from steps 7, 8, and 9
      --step 8 removes files from steps 8 and 9
      --step 9 removes files from step 9 only

Examples:
    $SCRIPT_NAME miaplpy_SN_201606_201608/network_single_reference --step 6
    $SCRIPT_NAME miaplpy_SN_201606_201608/network_single_reference --step 7
    $SCRIPT_NAME miaplpy_SN_201606_201608/network_single_reference --step 8
    $SCRIPT_NAME miaplpy_SN_201606_201608/network_single_reference --step 9
    $SCRIPT_NAME GalapagosSenD128/miaplpy/network_single_reference --step 9

Options:
    --step {6,7,8,9}    Miaplpy step number to clean files for
    --dry-run           Show what would be removed without actually removing
    --debug             Enable debug mode (set -x)
    "
    printf "$helptext"
    exit 0
fi

# Log file in the directory where script is invoked (current working directory)
WORK_DIR="$PWD"
LOG_FILE="$WORK_DIR/log"

# Log the command line as early as possible (before parsing)
echo "####################################" | tee -a "$LOG_FILE"
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" | tee -a "$LOG_FILE"

# Initialize option parsing variables (lowercase)
debug_flag=0
dry_run_flag=0
positional=()

# Default values for options (lowercase - local/temporary variables)
step=""

# Parse command line arguments
while [[ $# -gt 0 ]]
do
    key="$1"

    case $key in
        --step)
            step="$2"
            shift 2
            ;;
        --dry-run)
            dry_run_flag=1
            shift
            ;;
        --debug)
            debug_flag=1
            shift
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

set -- "${positional[@]}"

# Check for required positional arguments
if [[ ${#positional[@]} -lt 1 ]]; then
    echo "Error: One miaplpy directory is required"
    echo "Usage: $SCRIPT_NAME <miaplpy_directory> --step <step_number> [options]"
    echo "Use --help for more information"
    exit 1
fi

# Check for required --step option
if [[ -z "$step" ]]; then
    echo "Error: --step option is required"
    echo "Usage: $SCRIPT_NAME <miaplpy_directory> --step <step_number> [options]"
    echo "Use --help for more information"
    exit 1
fi

# Validate step number
if [[ ! "$step" =~ ^[6-9]$ ]]; then
    echo "Error: --step must be 6, 7, 8, or 9"
    exit 1
fi

# Enable debug mode if requested
[[ $debug_flag == "1" ]] && set -x

# Important workflow variables (UPPERCASE)
MIAPLPY_DIR="${positional[0]}"

# Check if directory exists
if [[ ! -d "$MIAPLPY_DIR" ]]; then
    echo "Error: Directory does not exist: $MIAPLPY_DIR"
    exit 1
fi

# Function to execute or show removal command
execute_removal() {
    local cmd="$1"
    
    if [[ $dry_run_flag == "1" ]]; then
        echo "[DRY-RUN] Would execute: $cmd"
    else
        echo "Executing: $cmd"
        eval "$cmd"
    fi
}

echo "####################################"
echo "Cleaning miaplpy directory: $MIAPLPY_DIR"
echo "Step: $step"
if [[ $dry_run_flag == "1" ]]; then
    echo "Mode: DRY-RUN (no files will be removed)"
fi
echo "####################################"

# Change to the miaplpy directory
cd "$MIAPLPY_DIR"

# Define cleanup functions for each step
clean_step_6() {
    echo "Cleaning files for step 6..."
    echo "Removing directory: inputs"
    execute_removal "rm -rf inputs"
}

clean_step_7() {
    echo "Cleaning files for step 7..."
    echo "Removing: avgPhaseVelocity.h5 avgSpatialCoh.h5 coherenceSpatialAvg.txt maskConnComp.h5"
    execute_removal "rm -f avgPhaseVelocity.h5 avgSpatialCoh.h5 coherenceSpatialAvg.txt maskConnComp.h5"
    
    echo "Removing directory: pic"
    execute_removal "rm -rf pic"
}

clean_step_8() {
    echo "Cleaning files for step 8..."
    echo "Removing: maskTempCoh.h5 numInvIfgram.h5 temporalCoherence.h5 temporalCoherence_mintpy.h5 timeseries.h5"
    execute_removal "rm -f maskTempCoh.h5 numInvIfgram.h5 temporalCoherence.h5 temporalCoherence_mintpy.h5 timeseries.h5"
}

clean_step_9() {
    echo "Cleaning files for step 9..."
    echo "Removing: demErr.h5 reference_date.txt rms_timeseriesResidual_ramp.txt *lowpass*.h5 timeseries*.h5 velocity.h5 *.he5"
    execute_removal "rm -f demErr.h5 reference_date.txt rms_timeseriesResidual_ramp.txt *lowpass*.h5 timeseries_*.h5 timeseriesR*.h5 velocity.h5 *.he5"
    
    echo "Removing directories: geo JSON*"
    execute_removal "rm -rf geo JSON*"
}

# Execute cleanup for selected step and all subsequent steps
case "$step" in
    6)
        clean_step_6
        clean_step_7
        clean_step_8
        clean_step_9
        ;;
    7)
        clean_step_7
        clean_step_8
        clean_step_9
        ;;
    8)
        clean_step_8
        clean_step_9
        ;;
    9)
        clean_step_9
        ;;
    *)
        echo "Error: Unknown step: $step"
        exit 1
        ;;
esac


# Return to original directory
cd "$WORK_DIR"


