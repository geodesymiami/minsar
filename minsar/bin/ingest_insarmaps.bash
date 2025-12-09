#!/usr/bin/env bash
# ingest_insarmaps.bash

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
    $SCRIPT_NAME miaplpy/network_single_reference
    $SCRIPT_NAME S1_IW1_128_20180303_XXXXXXXX__S00878_S00791_W091201_W091113.he5
    $SCRIPT_NAME hvGalapagosSenD128/mintpy -ref-lalo -0.81,-91.190
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy/network_single_reference
  Options:
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
echo "####################################" | tee -a "$LOG_FILE"
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

# If --ref-lalo was provided, update the reference point in the he5 file
if [[ ${#ref_lalo[@]} -gt 0 ]]; then
    echo "####################################"
    echo "Updating reference point in HDFEOS5 file"
    echo "####################################"
    
    # Parse reference point coordinates
    if [[ ${#ref_lalo[@]} -eq 1 ]]; then
        # Comma-separated format
        IFS=',' read -ra COORDS <<< "${ref_lalo[0]}"
        REF_LAT="${COORDS[0]}"
        REF_LON="${COORDS[1]}"
    else
        # Space-separated format
        REF_LAT="${ref_lalo[0]}"
        REF_LON="${ref_lalo[1]}"
    fi
    
    echo "Running: reference_point_hdfeos5.bash $he5_file --ref-lalo $REF_LAT $REF_LON"
    reference_point_hdfeos5.bash "$he5_file" --ref-lalo "$REF_LAT" "$REF_LON"
fi

echo "Processing: $he5_file"

JSON_DIR=$DATA_DIR/JSON
MBTILES_FILE="$JSON_DIR/$(basename "${he5_file%.he5}.mbtiles")"

echo "####################################"
rm -rf "$JSON_DIR"
cmd="hdfeos5_2json_mbtiles.py \"$he5_file\" \"$JSON_DIR\" --num-workers $HDFEOS_NUM_WORKERS"
run_command "$cmd"

for insarmaps_host in "${HOSTS[@]}"; do
    echo "####################################"
    echo "Running json_mbtiles2insarmaps.py..."
    cmd="json_mbtiles2insarmaps.py --num-workers $MBTILES_NUM_WORKERS -u \"$INSARMAPS_USER\" -p \"$INSARMAPS_PASS\" --host \"$insarmaps_host\" -P \"$DB_PASS\" -U \"$DB_USER\" --json_folder \"$JSON_DIR\" --mbtiles_file \"$MBTILES_FILE\""

    run_command "$cmd"

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
# Determine the log directory: use pic/ if it exists, otherwise use DATA_DIR directly
if [[ -d "$WORK_DIR/${DATA_DIR}/pic" ]]; then
    LOG_DIR="$WORK_DIR/${DATA_DIR}/pic"
    rm -f "$LOG_DIR/insarmaps.log"
else
    LOG_DIR="$WORK_DIR/${DATA_DIR}"
fi

for url in "${INSARMAPS_URLS[@]}"; do
    echo "$url"
    # Only write to WORK_DIR/insarmaps.log if it's different from LOG_DIR/insarmaps.log
    # Normalize paths to compare them (handle relative paths like ".")
    if [[ "$(cd "$WORK_DIR" && pwd)" != "$(cd "$LOG_DIR" && pwd)" ]]; then
        echo "$url" >> "$WORK_DIR/insarmaps.log"
    fi
    echo "$url" >> "$LOG_DIR/insarmaps.log"
done
