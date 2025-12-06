#!/usr/bin/env bash
# horzvert_2_insarmaps.bash
# Wrapper script for horzvert_timeseries.py
# Parses options similar to minsarApp.bash style

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

echo "sourcing ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh ..."
source ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh
echo "sourcing ${SCRIPT_DIR}/../lib/utils.sh ..."
source ${SCRIPT_DIR}/../lib/utils.sh

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Examples:
    $SCRIPT_NAME mintpy
    $SCRIPT_NAME miaplpy_SN_201803_201806/network_single_reference
    $SCRIPT_NAME S1_IW1_128_20180303_XXXXXXXX__S00878_S00791_W091201_W091113.he5
    $SCRIPT_NAME hvGalapagosSenD128/mintpy -ref-lalo -0.81,-91.190 
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy_SN_201803_201806/network_single_reference
  Options:
      --mask-thresh FLOAT             Coherence threshold for masking (default: 0.55)
      --ref-lalo LAT,LON or LAT LON   Reference point (lat,lon or lat lon)
      --debug                         Enable debug mode (set -x)
    "
    printf "$helptext"
    exit 0
fi

# Log file in the directory where script is invoked (current working directory)
WORK_DIR="$PWD"
LOG_FILE="$WORK_DIR/log"

# Log the command line as early as possible (before parsing)
echo "#############################################################################################" | tee -a "$LOG_FILE"
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" | tee -a "$LOG_FILE"

# Initialize option parsing variables (lowercase)
debug_flag=0
positional=()

# Default values for options (lowercase - local/temporary variables)
geom_file=()
mask_thresh=""
ref_lalo=()
lat_step=""
horz_az_angle=""
window_size=""
intervals=""
start_date=""
stop_date=""
period=""

# Parse command line arguments
while [[ $# -gt 0 ]]
do
    key="$1"

    case $key in
        --mask-thresh)
            mask_thresh="$2"
            shift 2
            ;;
        --ref-lalo)
            shift
            ref_lalo=()
            if [[ "$1" == *,* ]]; then
                ref_lalo=("$1")
            else
                ref_lalo=("$1" "$2")
                shift
            fi
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
    echo "Error: One input file or directory is required"
    echo "Usage: $SCRIPT_NAME <directory_or_file.he5> [options]"
    echo "Use --help for more information"
    exit 1
fi

# Enable debug mode if requested
[[ $debug_flag == "1" ]] && set -x

# Important workflow variables (UPPERCASE)
INPUT_PATH="${positional[0]}"

# Check if input is a file or directory
if [[ -f "$INPUT_PATH" ]]; then
    # Input is a file - use it directly
    he5_file="$INPUT_PATH"
    # DATA_DIR is the directory containing the file
    DATA_DIR=$(dirname "$INPUT_PATH")
elif [[ -d "$INPUT_PATH" ]]; then
    # Input is a directory - find the latest .he5 file
    DATA_DIR="$INPUT_PATH"
    he5_file=$(ls -t "$DATA_DIR"/*.he5 2>/dev/null | head -n 1)
    if [[ -z "$he5_file" ]]; then
        echo "Error: No .he5 files found in directory: $DATA_DIR"
        exit 1
    fi
else
    echo "Error: Input path does not exist or is not a file or directory: $INPUT_PATH"
    exit 1
fi

INSARMAPS_HOSTS=${INSARMAPSHOST:-insarmaps.miami.edu}
IFS=',' read -ra HOSTS <<< "$INSARMAPS_HOSTS"

SSARAHOME=${SSARAHOME:-""}
if [[ -n "$SSARAHOME" ]]; then
    INSARMAPS_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insaruser)" 2>/dev/null || echo "")
    INSARMAPS_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insarpass)" 2>/dev/null || echo "")
    DB_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databaseuser)" 2>/dev/null || echo "")
    DB_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databasepass)" 2>/dev/null || echo "")
fi

HDFEOS_NUM_WORKERS=6
MBTILES_NUM_WORKERS=6

echo "Processing: $he5_file"

JSON_DIR=$DATA_DIR/JSON
MBTILES_FILE="$JSON_DIR/$(basename "${he5_file%.he5}.mbtiles")"

rm -rf "$JSON_DIR"
cmd="hdfeos5_2json_mbtiles.py \"$he5_file\" \"$JSON_DIR\" --num-workers $HDFEOS_NUM_WORKERS"
run_command "$cmd"

echo "####################################"
echo "Done running hdfeos5_2json_mbtiles.py."
echo "####################################"

for insarmaps_host in "${HOSTS[@]}"; do
    echo "Running json_mbtiles2insarmaps.py..."
    cmd="json_mbtiles2insarmaps.py --num-workers $MBTILES_NUM_WORKERS -u \"$INSARMAPS_USER\" -p \"$INSARMAPS_PASS\" --host \"$insarmaps_host\" -P \"$DB_PASS\" -U \"$DB_USER\" --json_folder \"$JSON_DIR\" --mbtiles_file \"$MBTILES_FILE\""

    run_command "$cmd"

    echo "####################################"
    echo "Done running json_mbtiles2insarmaps.py ."
    echo "####################################"
done

wait   # Wait for all ingests to complete (parallel uinsg & is not implemented)

# Extract ref_lat/ref_lon from .he5 file
REF_COORDS=$(python3 -c "import h5py; f=h5py.File('$he5_file', 'r'); print(f'{f.attrs.get(\"REF_LAT\", 0.0)} {f.attrs.get(\"REF_LON\", 0.0)}')" 2>/dev/null || echo "0.0 0.0")
REF_LAT=$(echo $REF_COORDS | cut -d' ' -f1)
REF_LON=$(echo $REF_COORDS | cut -d' ' -f2)

DATASET_NAME=$(basename "${he5_file%.he5}")

# Generate insarmaps URLs and store in array
INSARMAPS_URLS=()
for insarmaps_host in "${HOSTS[@]}"; do
    url="http://${insarmaps_host}/start/${REF_LAT}/${REF_LON}/11.0?flyToDatasetCenter=true&startDataset=${DATASET_NAME}"
    INSARMAPS_URLS+=("$url")
done

# Write URLs to log files
echo "Creating insarmaps.log files"
rm -f "$WORK_DIR/${DATA_DIR}/pic/insarmaps.log"
for url in "${INSARMAPS_URLS[@]}"; do
    echo "$url"
    echo "$url" >> "$WORK_DIR/insarmaps.log"
    echo "$url" >> "$WORK_DIR/${DATA_DIR}/pic/insarmaps.log"
done

# Select URL for iframe: prefer one containing REMOTEHOST_INSARMAPS1 (insarmaps.miami.edu), otherwise use first
url=$(printf '%s\n' "${INSARMAPS_URLS[@]}" | grep -m1 "${REMOTEHOST_INSARMAPS1:-.}" || echo "${INSARMAPS_URLS[0]}")
write_insarmaps_iframe "$url" "$WORK_DIR/${DATA_DIR}/pic/iframe.html"