#!/usr/bin/env bash
# horzvert_timeseries.bash
# Wrapper script for horzvert_timeseries.py
# Parses options similar to minsarApp.bash style

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

echo "sourcing ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh ..."
source ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh
echo "sourcing ${SCRIPT_DIR}/../lib/utils.sh ..."
source ${SCRIPT_DIR}/../lib/utils.sh

# Function to get absolute path with SCRATCHDIR removed
# Resolves symlinks to handle OneDrive path variations on Mac
get_path_without_scratchdir() {
    local file_path="$1"
    [[ -z "$file_path" || ! -f "$file_path" ]] && return

    # Get absolute path, resolving symlinks
    local abs_path=$(realpath "$file_path" 2>/dev/null)
    [[ -z "$abs_path" ]] && abs_path=$(cd "$(dirname "$file_path")" && pwd)/$(basename "$file_path")

    # Resolve SCRATCHDIR symlinks and remove prefix if it exists
    if [[ -n "${SCRATCHDIR:-}" ]]; then
        local scratchdir_resolved=$(realpath "$SCRATCHDIR" 2>/dev/null || (cd "$SCRATCHDIR" && pwd))
        [[ "$abs_path" == "$scratchdir_resolved"/* ]] && abs_path="${abs_path#$scratchdir_resolved/}"
    fi

    echo "$abs_path"
}

# Function to normalize coordinates in insarmaps.log using vert coordinates
normalize_insarmaps_coordinates() {
    local log_file="$1"
    
    echo "Normalizing coordinates in insarmaps.log to use vert coordinates..."
    
    # Extract lat/lon from the line containing "vert"
    local vert_lat=$(grep "vert" "$log_file" | head -n 1 | cut -d/ -f5)
    local vert_lon=$(grep "vert" "$log_file" | head -n 1 | cut -d/ -f6)
    
    echo "Using vert coordinates: $vert_lat, $vert_lon"
    
    # Update all lines to use vert coordinates
    sed -i.bak -E "s|(/start/)[^/]+/[^/]+/|\1${vert_lat}/${vert_lon}/|" "$log_file"
    rm -f "${log_file}.bak"
    
    echo "Updated all coordinates in insarmaps.log"
}

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Examples:
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878 --dry-run
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878 --intervals 6
    $SCRIPT_NAME hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190
    $SCRIPT_NAME hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190 --no-insarmaps
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy/network_single_reference hvGalapagosSenA106/miaplpy/network_single_reference --ref-lalo -0.81 -91.190 --no-ingest-los
    $SCRIPT_NAME FernandinaSenD128/mintpy/ FernandinaSenA106/mintpy/ --ref-lalo -0.453 -91.390
    $SCRIPT_NAME FernandinaSenD128/miaplpy/network_delaunay_4 FernandinaSenA106/miaplpy/network_delaunay_4 --ref-lalo -0.415 -91.543
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
      --no-ingest-los                 Skip ingesting both input files (FILE1 and FILE2) with --ref-lalo (default: ingest-los is enabled)
      --no-insarmaps                  Skip running ingest_insarmaps.bash (default: insarmaps ingestion is enabled)
      --debug                         Enable debug mode (set -x)
    "
    printf "$helptext"
    exit 0
fi

# Log file in the directory where script is invoked (current working directory)
WORK_DIR="$PWD"
LOG_FILE="$WORK_DIR/log"

# Log the command line as early as possible (before parsing)
echo "##############################################" | tee -a "$LOG_FILE"
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" | tee -a "$LOG_FILE"

# Initialize option parsing variables (lowercase)
debug_flag=0
ingest_los_flag=1  # Default: ingest-los is enabled
ingest_insarmaps_flag=1  # Default: insarmaps ingestion is enabled
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
        --no-ingest-los)
            ingest_los_flag=0
            shift
            ;;
        --no-insarmaps)
            ingest_insarmaps_flag=0
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
echo "##############################################"
echo "Running: $CMD"
eval $CMD

ORIGINAL_DIR="$PWD"
PROJECT_DIR=$(get_base_projectname "$FILE1")
dir="$([ -f "$FILE1" ] && dirname "$FILE1" || echo "$FILE1")"
processing_method_dir=$(echo "$dir" | tr '/' '\n' | grep -E '^(mintpy|miaplpy)' | head -1 | cut -d'_' -f1)

HORZVERT_DIR="${PROJECT_DIR}/${processing_method_dir}"
mkdir -p "$ORIGINAL_DIR/$HORZVERT_DIR"
DATA_FILES_TXT="$ORIGINAL_DIR/$HORZVERT_DIR/data_files.txt"
rm -f $DATA_FILES_TXT ; touch $DATA_FILES_TXT

# Find the latest (youngest) *vert*.he5 and *horz*.he5 files
cd "$HORZVERT_DIR"
rm -f insarmaps.log
VERT_FILE=$(ls -t *vert*.he5 2>/dev/null | head -1)
HORZ_FILE=$(ls -t *horz*.he5 2>/dev/null | head -1)

echo "Found vert file: $VERT_FILE"
echo "Found horz file: $HORZ_FILE"

# Update data_footprint to match vert file for consistent map overlay (commented out for testing)
copy_data_footprint.py "$VERT_FILE" "$HORZ_FILE" "$ORIGINAL_DIR/$FILE1" "$ORIGINAL_DIR/$FILE2"

if [[ $ingest_insarmaps_flag == "0" ]]; then
    exit 0
fi

echo "##############################################"
ingest_insarmaps.bash "$VERT_FILE"
echo "$ORIGINAL_DIR/$HORZVERT_DIR/$VERT_FILE" >> $DATA_FILES_TXT

echo "##############################################"
ingest_insarmaps.bash "$HORZ_FILE"
echo "$ORIGINAL_DIR/$HORZVERT_DIR$HORZ_FILE" >> $DATA_FILES_TXT

# Ingest original input files, stay in HORZVERT_DIR so all entries go to the same insarmaps.log
if [[ $ingest_los_flag == "1" ]]; then
    # FILE1 and FILE2 are relative to ORIGINAL_DIR
    cd "$ORIGINAL_DIR/$HORZVERT_DIR"
    echo "##############################################"
    ingest_insarmaps.bash "$ORIGINAL_DIR/$FILE1" --ref-lalo "${ref_lalo[@]}"
    FILE1_HE5=$(ls -t "$ORIGINAL_DIR/$FILE1"/*.he5 2>/dev/null | head -n 1) || FILE1_HE5="$ORIGINAL_DIR/$FILE1"
    echo "$FILE1_HE5" >> $DATA_FILES_TXT

    echo "##############################################"
    ingest_insarmaps.bash "$ORIGINAL_DIR/$FILE2" --ref-lalo "${ref_lalo[@]}"
    FILE2_HE5=$(ls -t "$ORIGINAL_DIR/$FILE2"/*.he5 2>/dev/null | head -n 1) || FILE2_HE5="$ORIGINAL_DIR/$FILE2"
    echo "$FILE2_HE5" >> $DATA_FILES_TXT

    # Normalize coordinates in insarmaps.log to use vert coordinates (we're already in HORZVERT_DIR)
    normalize_insarmaps_coordinates "insarmaps.log"

    # Create insarmaps framepage (using absolute paths since we're back in ORIGINAL_DIR)
    echo "##############################################"
    cd "$ORIGINAL_DIR"
    create_insarmaps_framepages.py "$HORZVERT_DIR/insarmaps.log" --outdir "$HORZVERT_DIR"
    write_insarmaps_framepage_urls.py "$HORZVERT_DIR" --outdir "$HORZVERT_DIR"
    create_data_download_commands.py "$DATA_FILES_TXT"

    echo "insarmaps frames created:"
    cat "$HORZVERT_DIR/frames_urls.log"
fi

