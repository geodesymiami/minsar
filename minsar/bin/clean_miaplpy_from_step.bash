#!/usr/bin/env bash
# Remove MiaplPy products from step N onward so --miaplpy-start N re-runs without update skip.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Remove MiaplPy outputs from the given step through step 10 (HE5 / ingest artifacts).

Cleaning step N also removes products from all later steps (e.g. --step 8 removes 8–10).

Examples:
    $SCRIPT_NAME miaplpy_Hverfjall_202005_202606/network_delaunay_4 --step 1
    $SCRIPT_NAME miaplpy_Hverfjall_202005_202606/network_delaunay_4 --step 8
    $SCRIPT_NAME miaplpy_SN_201606_201608/network_single_reference --step 6 --dry-run

Arguments:
    NETWORK_DIR    MiaplPy network directory (network_* under miaplpy_*)

Options:
    --step {1..10}   First MiaplPy step to clean (required)
    --dry-run        Print removals without deleting
    --debug          Enable bash trace (set -x)
"
    printf "%b" "$helptext"
    exit 0
fi

debug_flag=0
dry_run_flag=0
step=""
positional=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --step)
            [[ $# -lt 2 ]] && { echo "Error: --step requires a value" >&2; exit 1; }
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
        -?*)
            echo "Error: Unknown option: $1" >&2
            exit 1
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

if [[ ${#positional[@]} -lt 1 ]]; then
    echo "Error: NETWORK_DIR is required" >&2
    echo "Usage: $SCRIPT_NAME NETWORK_DIR --step N" >&2
    exit 1
fi

if [[ -z "$step" ]]; then
    echo "Error: --step is required" >&2
    exit 1
fi

if [[ ! "$step" =~ ^([1-9]|10)$ ]]; then
    echo "Error: --step must be 1–10 (got '$step')" >&2
    exit 1
fi

[[ $debug_flag == 1 ]] && set -x

NETWORK_DIR="${positional[0]}"
MIAPLPY_DIR="$(dirname "$NETWORK_DIR")"
network_missing=0
miaplpy_missing=0

[[ -d "$NETWORK_DIR" ]] || network_missing=1
[[ -d "$MIAPLPY_DIR" ]] || miaplpy_missing=1

if [[ "$network_missing" == "1" && "$miaplpy_missing" == "1" ]]; then
    echo "Note: nothing to clean (miaplpy dir not found: $MIAPLPY_DIR)"
    exit 0
fi

if [[ "$network_missing" == "1" ]]; then
    if [[ "$step" -le 5 ]]; then
        echo "Note: network dir missing ($NETWORK_DIR); cleaning miaplpy dir steps 1–5 only"
    else
        echo "Error: network directory required for --step $step but not found: $NETWORK_DIR" >&2
        exit 1
    fi
fi

WORK_DIR="$PWD"
LOG_FILE="$WORK_DIR/log"
echo "####################################" | tee -a "$LOG_FILE"
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" | tee -a "$LOG_FILE"

execute_removal() {
    local cmd="$1"
    if [[ $dry_run_flag == 1 ]]; then
        echo "[DRY-RUN] $cmd"
    else
        echo "$cmd"
        eval "$cmd"
    fi
}

clean_run_logs() {
    local n="$1"
    [[ -d "$NETWORK_DIR/run_files" ]] || return 0
    execute_removal "rm -f '${NETWORK_DIR}/run_files/run_$(printf '%02d' "$n")_'*.{o,e}"
}

echo "Cleaning MiaplPy from step $step (miaplpy: $MIAPLPY_DIR, network: $NETWORK_DIR)"
[[ $dry_run_flag == 1 ]] && echo "Mode: dry-run"

clean_step_1() {
    echo "--- step 1 (load_data) ---"
    execute_removal "rm -f '${MIAPLPY_DIR}/inputs/slcStack.h5' '${MIAPLPY_DIR}/inputs/geometryRadar.h5'"
    clean_run_logs 1
}

clean_step_2() {
    echo "--- step 2 (phase_linking) ---"
    execute_removal "rm -rf '${MIAPLPY_DIR}/inverted'"
    clean_run_logs 2
}

clean_step_3() {
    echo "--- step 3 (concatenate_patches) ---"
    execute_removal "rm -rf '${MIAPLPY_DIR}/inverted'"
    clean_run_logs 3
}

clean_step_4() {
    echo "--- step 4 (generate_ifgram) ---"
    execute_removal "rm -rf ${MIAPLPY_DIR}/inverted/interferograms*"
    execute_removal "rm -f '${NETWORK_DIR}/interferograms_list.txt'"
    clean_run_logs 4
}

clean_step_5() {
    echo "--- step 5 (unwrap_ifgram) ---"
    execute_removal "find ${MIAPLPY_DIR}/inverted/interferograms* -name '*.unw' -delete 2>/dev/null || true"
    clean_run_logs 5
}

clean_step_6() {
    echo "--- step 6 (load_ifgram) ---"
    [[ -d "$NETWORK_DIR" ]] || return 0
    execute_removal "rm -rf '${NETWORK_DIR}/inputs'"
    execute_removal "rm -f '${NETWORK_DIR}/smallbaselineApp.cfg'"
    clean_run_logs 6
}

clean_step_7() {
    echo "--- step 7 (ifgram_correction) ---"
    [[ -d "$NETWORK_DIR" ]] || return 0
    execute_removal "rm -f '${NETWORK_DIR}/avgPhaseVelocity.h5' '${NETWORK_DIR}/avgSpatialCoh.h5' '${NETWORK_DIR}/coherenceSpatialAvg.txt' '${NETWORK_DIR}/maskConnComp.h5'"
    execute_removal "rm -rf '${NETWORK_DIR}/pic'"
    clean_run_logs 7
}

clean_step_8() {
    echo "--- step 8 (invert_network) ---"
    [[ -d "$NETWORK_DIR" ]] || return 0
    execute_removal "rm -f '${NETWORK_DIR}/maskTempCoh.h5' '${NETWORK_DIR}/numInvIfgram.h5' '${NETWORK_DIR}/temporalCoherence.h5' '${NETWORK_DIR}/temporalCoherence_mintpy.h5' '${NETWORK_DIR}/timeseries.h5'"
    clean_run_logs 8
}

clean_step_9() {
    echo "--- step 9 (timeseries_correction) ---"
    [[ -d "$NETWORK_DIR" ]] || return 0
    execute_removal "rm -f '${NETWORK_DIR}/demErr.h5' '${NETWORK_DIR}/reference_date.txt' '${NETWORK_DIR}/rms_timeseriesResidual_ramp.txt'"
    execute_removal "rm -f '${NETWORK_DIR}'/*lowpass*.h5 '${NETWORK_DIR}/timeseries_'*.h5 '${NETWORK_DIR}/timeseriesR'*.h5 '${NETWORK_DIR}/velocity.h5'"
    clean_run_logs 9
}

clean_step_10() {
    echo "--- step 10 (HE5 export / ingest artifacts) ---"
    [[ -d "$NETWORK_DIR" ]] || return 0
    execute_removal "rm -f '${NETWORK_DIR}'/*.he5"
    execute_removal "rm -rf '${NETWORK_DIR}/geo' '${NETWORK_DIR}/JSON' '${NETWORK_DIR}/JSON_PS' '${NETWORK_DIR}/JSON_DS' '${NETWORK_DIR}/JSON_filtDS'"
    execute_removal "rm -f '${NETWORK_DIR}/run_files/run_10_save_hdfeos5_radar'*.o '${NETWORK_DIR}/run_files/run_10_save_hdfeos5_radar'*.e"
}

for s in $(seq "$step" 10); do
    "clean_step_${s}"
done

echo "Done: cleaned MiaplPy outputs from step $step through 10"
