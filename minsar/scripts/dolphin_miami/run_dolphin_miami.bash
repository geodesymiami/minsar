#!/usr/bin/env bash
########################################################################
# Run Dolphin PS/DS workflow on Miami CSLC data.
#
# Prerequisites:
#   1. Run install_dolphin.bash
#   2. Run download_cslc_miami.bash to populate CSLC/ (or set --data-dir)
#
# Usage: bash run_dolphin_miami.bash [OPTIONS]
#   --data-dir PATH    Directory containing CSLC files (default: $SCRATCHDIR/dolphin_test/CSLC or <process-dir>/CSLC)
#   --process-dir PATH Directory for Dolphin run (config + outputs) (default: $SCRATCHDIR/dolphin_test)
#   Optional env: DOLPHIN_ENV=dolphin-env (conda env name)
########################################################################
set -euo pipefail

PROCESS_DIR=""
DATA_DIR=""
DOLPHIN_ENV="${DOLPHIN_ENV:-dolphin-env}"

# Parse --data-dir and --process-dir
while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-dir)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --data-dir requires PATH" >&2
                exit 1
            fi
            DATA_DIR="$2"
            shift 2
            ;;
        --process-dir)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --process-dir requires PATH" >&2
                exit 1
            fi
            PROCESS_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--data-dir PATH] [--process-dir PATH]" >&2
            exit 1
            ;;
    esac
done

# Default process dir to $SCRATCHDIR/dolphin_test if not set
if [[ -z "${PROCESS_DIR}" ]]; then
    PROCESS_DIR="${SCRATCHDIR:?SCRATCHDIR must be set (or use --process-dir)}/dolphin_test"
fi
# Default data dir to <process-dir>/CSLC if not set
if [[ -z "${DATA_DIR}" ]]; then
    DATA_DIR="${PROCESS_DIR}/CSLC"
fi

WORKDIR="${PROCESS_DIR}"
CSLC_DIR="${DATA_DIR}"
CONFIG_FILE="${WORKDIR}/dolphin_config.yaml"

if [[ ! -d "${CSLC_DIR}" ]]; then
    echo "Error: CSLC directory not found: ${CSLC_DIR}" >&2
    echo "Run download_cslc_miami.bash first." >&2
    exit 1
fi

# Find CSLC files (ASF CSLC products are often .h5 or .nc)
shopt -s nullglob
CSLC_FILES=("${CSLC_DIR}"/*.h5 "${CSLC_DIR}"/*.nc "${CSLC_DIR}"/*.hdf5)
if [[ ${#CSLC_FILES[@]} -eq 0 ]]; then
    # Try any file in subdirs (e.g. unpacked granules)
    CSLC_FILES=("${CSLC_DIR}"/*/*.h5 "${CSLC_DIR}"/*/*.nc "${CSLC_DIR}"/*/*.hdf5)
fi
if [[ ${#CSLC_FILES[@]} -eq 0 ]]; then
    echo "Error: No CSLC files (.h5, .nc, .hdf5) found in ${CSLC_DIR}" >&2
    exit 1
fi

echo "Found ${#CSLC_FILES[@]} CSLC file(s)"
cd "${WORKDIR}"

# Pass each CSLC path as --slc-files so Dolphin sees real filenames (needed for date parsing).
# OPERA CSLC-S1 filenames contain dates like 20250303T140103Z; Dolphin matches %Y%m%d substring.
SLC_ARGS=()
for f in "${CSLC_FILES[@]}"; do
    SLC_ARGS+=(--slc-files "$f")
done

# Generate config (full extent; add bounds in YAML if needed)
# Miami subset reference: 25.765:25.98, -80.147:-80.1146 -> [left, bottom, right, top]
conda run -n "${DOLPHIN_ENV}" dolphin config \
    "${SLC_ARGS[@]}" \
    --work-directory "${WORKDIR}" \
    --outfile "${CONFIG_FILE}"

echo "Running Dolphin with ${CONFIG_FILE}"
conda run -n "${DOLPHIN_ENV}" dolphin run "${CONFIG_FILE}"

echo "Done. Outputs are in ${WORKDIR}"
