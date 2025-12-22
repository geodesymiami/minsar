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
    $SCRIPT_NAME miaplpy/network_single_reference --dataset geo
    $SCRIPT_NAME miaplpy/network_single_reference --dataset PS
    $SCRIPT_NAME miaplpy/network_single_reference --dataset filt*DS
    $SCRIPT_NAME miaplpy/network_single_reference --dataset PS,DS
    $SCRIPT_NAME miaplpy/network_single_reference --dataset PS,DS,filt*DS

  Options:
      --ref-lalo LAT,LON or LAT LON   Reference point (lat,lon or lat lon)
      --dataset {PS,DS,filtDS,filt*DS,geo} or comma-separated {PS,DS,filt*DS}  Dataset to upload (default: geo)
                                          Use comma-separated values to ingest multiple types: --dataset PS,DS or --dataset PS,DS,filt*DS
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
dataset="geo"
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
        --dataset)
            dataset="$2"
            shift 2
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

# Function to check if a file matches a dataset type
file_matches_dataset() {
    local file="$1"
    local ds_type="$2"
    
    case "$ds_type" in
        "geo")
            [[ "$file" != *"DS"* && "$file" != *"PS"* ]]
            ;;
        "PS")
            [[ "$file" == *"PS"* ]]
            ;;
        "DS")
            [[ "$file" == *"DS"* && "$file" != *"filt"* ]]
            ;;
        "filtDS"|"filt*DS")
            [[ "$file" == *"DS"* && "$file" == *"filt"* ]]
            ;;
        *)
            return 1
            ;;
    esac
}

# Check if input is a file or directory
if [[ -f "$INPUT_PATH" ]]; then
    # Input is a file - use it directly
    DATA_DIR=$(dirname "$INPUT_PATH")
    he5_files=("$INPUT_PATH")
elif [[ -d "$INPUT_PATH" ]]; then
    # Input is a directory - find .he5 files based on dataset option(s)
    DATA_DIR="$INPUT_PATH"
    all_he5_files=($(ls -t "$DATA_DIR"/*.he5 2>/dev/null))
    
    if [[ ${#all_he5_files[@]} -eq 0 ]]; then
        echo "Error: No .he5 files found in directory: $DATA_DIR"
        exit 1
    fi
    
    # Parse comma-separated dataset types
    IFS=',' read -ra DATASET_TYPES <<< "$dataset"
    
    # Find all matching files based on dataset option(s)
    # Use associative array to avoid duplicates while preserving order from ls -t
    declare -A matched_files  # Use associative array to track which files match
    for ds_type in "${DATASET_TYPES[@]}"; do
        ds_type=$(echo "$ds_type" | xargs)  # Trim whitespace
        for file in "${all_he5_files[@]}"; do
            if file_matches_dataset "$file" "$ds_type"; then
                matched_files["$file"]=1
            fi
        done
    done
    
    # Convert to regular array, preserving order from all_he5_files (newest first)
    he5_files=()
    for file in "${all_he5_files[@]}"; do
        if [[ -n "${matched_files[$file]}" ]]; then
            he5_files+=("$file")
        fi
    done
    
    if [[ ${#he5_files[@]} -eq 0 ]]; then
        echo "Error: No .he5 files found matching dataset option(s) '$dataset' in directory: $DATA_DIR"
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

# Process each he5 file
for he5_file in "${he5_files[@]}"; do
    echo "####################################"
    echo "Processing: $he5_file"
    
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
    
    # Determine JSON directory suffix based on file pattern
    JSON_SUFFIX=""
    if [[ "$he5_file" == *"PS"* ]]; then
        JSON_SUFFIX="_PS"
    elif [[ "$he5_file" == *"filt"* && "$he5_file" == *"DS"* ]]; then
        JSON_SUFFIX="_filtDS"
    elif [[ "$he5_file" == *"DS"* ]]; then
        JSON_SUFFIX="_DS"
    fi
    
    JSON_DIR=$DATA_DIR/JSON${JSON_SUFFIX}
    
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
    
    # Format lat/lon to 4 decimal places for insarmaps.log
    REF_LAT_FORMATTED=$(printf "%.4f" "$REF_LAT")
    REF_LON_FORMATTED=$(printf "%.4f" "$REF_LON")
    
    DATASET_NAME=$(basename "${he5_file%.he5}")
    
    # Generate insarmaps URLs and store in array
    INSARMAPS_URLS=()
    for insarmaps_host in "${HOSTS[@]}"; do
        # Use https for insarmaps.miami.edu, http for others
        if [[ "$insarmaps_host" == *"insarmaps.miami.edu"* ]]; then
            protocol="https"
        else
            protocol="http"
        fi
        url="${protocol}://${insarmaps_host}/start/${REF_LAT_FORMATTED}/${REF_LON_FORMATTED}/11.0?flyToDatasetCenter=true&startDataset=${DATASET_NAME}"
        INSARMAPS_URLS+=("$url")
    done
    
    # Write URLs to log files
    echo "Appending to insarmaps.log file"
    # Determine the log directory: use pic/ if it exists, otherwise use DATA_DIR directly
    if [[ -d "${DATA_DIR}/pic" ]]; then
        LOG_DIR="$DATA_DIR/pic"
    else
        LOG_DIR="$WORK_DIR"
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
done
