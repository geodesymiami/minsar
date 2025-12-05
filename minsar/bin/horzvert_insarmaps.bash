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
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.84969 -77.86430
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.84969 -77.86430 --dry-run
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.84969 -77.86430 --intervals 6
    $SCRIPT_NAME hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy_SN_201803_201806/network_single_reference hvGalapagosSenA106/miaplpy_SN_201803_201805/network_single_reference--ref-lalo -0.81 -91.190
    $SCRIPT_NAME FernandinaSenD128/mintpy/ FernandinaSenA106/mintpy/ --ref-lalo -0.453 -91.390
    $SCRIPT_NAME FernandinaSenD128/miaplpy/network_delaunay_4 FernandinaSenA106/miaplpy/network_delaunay_4 --ref-lalo -0.453 -91.390
    $SCRIPT_NAME MaunaLoaSenDT87/mintpy MaunaLoaSenAT124/mintpy --period 20181001:20191031 --ref-lalo 19.50068 -155.55856 --ref-lalo -0.81 -91.190

  Options:
      --mask-thresh FLOAT             Coherence threshold for masking (default: 0.55)
      --ref-lalo LAT,LON or LAT LON   Reference point (lat,lon or lat lon)
      --lat-step FLOAT                Latitude step for geocoding (default: -0.0002)
      --horz-az-angle FLOAT           Horizontal azimuth angle (default: 90)
      --window-size INT               Window size for reference point lookup (default: 3)
      --intervals INT                 Interval block index (default: 2)
      --start-date YYYYMMDD           Start date of limited period
      --end-date YYYYMMDD             End date of limited period
      --period YYYYMMDD:YYYYMMDD      Period of the search
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
        -g|--geom-file)
            geom_file=("$2" "$3")
            shift 3
            ;;
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
        --lat-step)
            lat_step="$2"
            shift 2
            ;;
        --horz-az-angle)
            horz_az_angle="$2"
            shift 2
            ;;
        --window-size)
            window_size="$2"
            shift 2
            ;;
        --intervals)
            intervals="$2"
            shift 2
            ;;
        --start-date)
            start_date="$2"
            shift 2
            ;;
        --end-date)
            stop_date="$2"
            shift 2
            ;;
        --period)
            period="$2"
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
if [[ ${#positional[@]} -lt 2 ]]; then
    echo "Error: Two input files are required"
    echo "Usage: $SCRIPT_NAME <file1> <file2> [options]"
    echo "Use --help for more information"
    exit 1
fi

# Important workflow variables (UPPERCASE)
FILE1="${positional[0]}"
FILE2="${positional[1]}"

# Check for unknown extra positional arguments
if [[ ${#positional[@]} -gt 2 ]]; then
    echo "Warning: Unknown parameters provided: ${positional[@]:2}"
    echo "These will be ignored"
fi

# Enable debug mode if requested
[[ $debug_flag == "1" ]] && set -x

# Build the command for horzvert_timeseries.py (UPPERCASE - important script variable)
CMD="horzvert_timeseries.py \"$FILE1\" \"$FILE2\""

# Add optional arguments with one-liner conditionals
[[ -n "$mask_thresh" ]] && CMD="$CMD --mask-thresh $mask_thresh"
[[ ${#ref_lalo[@]} -gt 0 ]] && CMD="$CMD --ref-lalo ${ref_lalo[@]}"
[[ -n "$lat_step" ]] && CMD="$CMD --lat-step $lat_step"
[[ -n "$horz_az_angle" ]] && CMD="$CMD --horz-az-angle $horz_az_angle"
[[ -n "$window_size" ]] && CMD="$CMD --window-size $window_size"
[[ -n "$intervals" ]] && CMD="$CMD --intervals $intervals"
[[ -n "$start_date" ]] && CMD="$CMD --start-date $start_date"
[[ -n "$stop_date" ]] && CMD="$CMD --end-date $stop_date"
[[ -n "$period" ]] && CMD="$CMD --period $period"

# Execute horzvert_timeseries.py command
echo "Running: $CMD"
eval $CMD

echo "####################################"
echo "Done running horzvert_timeseries.py."
echo "####################################"

# Find the latest (youngest) *vert*.he5 and *horz*.he5 files
PROJECT_DIR=$(get_base_projectname "$FILE1")

VERT_FILE=$(ls -t "$PROJECT_DIR"/*vert*.he5 2>/dev/null | head -1)
HORZ_FILE=$(ls -t "$PROJECT_DIR"/*horz*.he5 2>/dev/null | head -1)

echo "Found vert file: $VERT_FILE"
echo "Found horz file: $HORZ_FILE"

# Get insarmaps hosts and credentials
INSARMAPS_HOSTS=${INSARMAPSHOST:-insarmaps.miami.edu}
IFS=',' read -ra HOSTS <<< "$INSARMAPS_HOSTS"

# Get credentials from password_config (Python)
SSARAHOME=${SSARAHOME:-""}
if [[ -n "$SSARAHOME" ]]; then
    INSARMAPS_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insaruser)" 2>/dev/null || echo "")
    INSARMAPS_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insarpass)" 2>/dev/null || echo "")
    DB_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databaseuser)" 2>/dev/null || echo "")
    DB_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databasepass)" 2>/dev/null || echo "")
fi

HDFEOS_NUM_WORKERS=6
MBTILES_NUM_WORKERS=6

# Process both files (vert and horz)
for he5_file in "$VERT_FILE" "$HORZ_FILE"; do

    echo "Processing: $he5_file"

    JSON_DIR=$PROJECT_DIR/JSON
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

        # json_mbtiles2insarmaps.py --num-workers $MBTILES_NUM_WORKERS -u "$INSARMAPS_USER" -p "$INSARMAPS_PASS" --host "$insarmaps_host" \
        #     -P "$DB_PASS" -U "$DB_USER" --json_folder "$JSON_DIR" --mbtiles_file "$MBTILES_FILE" &
        run_command "$cmd"

        echo "####################################"
        echo "Done running json_mbtiles2insarmaps.py ."
        echo "####################################"
    done
done

wait   # Wait for all ingests to complete (parallel uinsg & is not implemented)

# Generate insarmaps.log with URLs
for he5_file in "$VERT_FILE" "$HORZ_FILE"; do
    # Extract ref_lat/ref_lon from .he5 file
    REF_COORDS=$(python3 -c "import h5py; f=h5py.File('$he5_file', 'r'); print(f'{f.attrs.get(\"REF_LAT\", 0.0)} {f.attrs.get(\"REF_LON\", 0.0)}')" 2>/dev/null || echo "0.0 0.0")
    REF_LAT=$(echo $REF_COORDS | cut -d' ' -f1)
    REF_LON=$(echo $REF_COORDS | cut -d' ' -f2)

    DATASET_NAME=$(basename "${he5_file%.he5}")

    for insarmaps_host in "${HOSTS[@]}"; do
        echo "http://${insarmaps_host}/start/${REF_LAT}/${REF_LON}/11.0?flyToDatasetCenter=true&startDataset=${DATASET_NAME}"
        echo "http://${insarmaps_host}/start/${REF_LAT}/${REF_LON}/11.0?flyToDatasetCenter=true&startDataset=${DATASET_NAME}" >> ${PROJECT_DIR}/insarmaps.log
    done
done

echo "Insarmaps URLs written to ${PROJECT_DIR}/insarmaps.log"
