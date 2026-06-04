#!/usr/bin/env bash
########################################################################
# Run Dolphin PS/DS workflow on Miami CSLC data.
# Expects CSLC files in CSLC_DIR (e.g. after download_miami_cslc.bash and
# unzipping any ASF zips). Creates dolphin_config.yaml and runs dolphin.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Miami subset: [left, bottom, right, top] (lon, lat) for bounds
MIA_BOUNDS="-80.147,25.765,-80.1146,25.98"

# Defaults
CSLC_DIR="${CSLC_DIR:-$(pwd)/CSLC}"
WORK_DIR="${WORK_DIR:-$(pwd)/dolphin_miami}"
CONFIG_NAME="${CONFIG_NAME:-dolphin_config.yaml}"
SLC_LIST_FILE="${WORK_DIR}/cslc_file_list.txt"

usage() {
    echo "Usage: ${0##*/} [OPTIONS]"
    echo ""
    echo "Run Dolphin on Miami CSLC data. Requires: conda activate dolphin-env."
    echo ""
    echo "Options:"
    echo "  --cslc-dir DIR      Directory containing CSLC files (default: ${CSLC_DIR})"
    echo "  --work-dir DIR     Working directory for config and outputs (default: ${WORK_DIR})"
    echo "  --config-only      Only write dolphin_config.yaml, do not run"
    echo "  -h, --help         Show this help"
}

CONFIG_ONLY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cslc-dir)   CSLC_DIR="$2"; shift 2 ;;
        --work-dir)   WORK_DIR="$2"; shift 2 ;;
        --config-only) CONFIG_ONLY="yes"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ ! -d "${CSLC_DIR}" ]]; then
    echo "Error: CSLC directory not found: ${CSLC_DIR}" >&2
    echo "Run download_miami_cslc.bash first and unzip any ASF product zips into this dir." >&2
    exit 1
fi

mkdir -p "${WORK_DIR}"
cd "${WORK_DIR}"

# Build list of CSLC files (.tif, .tiff, .h5, .hdf5, .nc; flat or one level down)
SLC_LIST_FILE="${WORK_DIR}/cslc_file_list.txt"
: > "${SLC_LIST_FILE}"
for ext in tif tiff h5 hdf5 nc; do
    for f in "${CSLC_DIR}"/*."${ext}" "${CSLC_DIR}"/*/*."${ext}" 2>/dev/null; do
        [[ -e "$f" ]] && printf '%s\n' "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" >> "${SLC_LIST_FILE}"
    done
done
# Deduplicate and sort
sort -u "${SLC_LIST_FILE}" -o "${SLC_LIST_FILE}"
N_FILES=$(wc -l < "${SLC_LIST_FILE}" | tr -d ' ')
if [[ "${N_FILES}" -eq 0 ]]; then
    echo "Error: No CSLC files found in ${CSLC_DIR} (*.tif, *.tiff, *.h5, *.hdf5, *.nc)" >&2
    echo "Unzip ASF product zips into ${CSLC_DIR} if needed." >&2
    exit 1
fi
echo "Found ${N_FILES} CSLC files."

# Generate config: slc list from file, Miami bounds, work dir
dolphin config \
    --slc-files "@${SLC_LIST_FILE}" \
    --work-directory "${WORK_DIR}"

CONFIG_PATH="${WORK_DIR}/dolphin_config.yaml"
if [[ ! -f "${CONFIG_PATH}" ]]; then
    CONFIG_PATH="${WORK_DIR}/${CONFIG_NAME}"
fi

# Set Miami bounds in the generated config (bounds: [left, bottom, right, top])
if [[ -f "${CONFIG_PATH}" ]]; then
    if grep -q 'bounds:' "${CONFIG_PATH}"; then
        sed -E 's/^( *bounds: *)\[\]/\1[-80.147, 25.765, -80.1146, 25.98]/; s/^( *bounds: *)null/\1[-80.147, 25.765, -80.1146, 25.98]/' "${CONFIG_PATH}" > "${CONFIG_PATH}.tmp" && mv "${CONFIG_PATH}.tmp" "${CONFIG_PATH}"
    fi
fi

if [[ -n "${CONFIG_ONLY}" ]]; then
    echo "Config written to ${CONFIG_PATH}. Edit and run: dolphin run ${CONFIG_PATH}"
    exit 0
fi

echo "Running Dolphin..."
dolphin run "${CONFIG_PATH}"
echo "Done. Outputs in ${WORK_DIR}"
