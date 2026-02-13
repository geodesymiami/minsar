#!/usr/bin/env bash
# horzvert_timeseries.bash
# Wrapper script for horzvert_timeseries.py
# Parses options similar to minsarApp.bash style

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

# echo "sourcing ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh ..."
# source ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh
# echo "sourcing ${SCRIPT_DIR}/../lib/utils.sh ..."
source ${SCRIPT_DIR}/../lib/utils.sh

# Dependencies: utils.sh [get_base_projectname], horzvert_timeseries.py (external),
#   write_insarmaps_framepage_urls.py, create_data_download_commands.py, ingest_insarmaps.bash.
# Output (project/mintpy or project/miaplpy): data_files.txt, *vert*.he5, *horz*.he5, maskTempCoh.h5, image_pairs.txt, geometryRadar.h5 in Sen*.
#   overlay.html, index.html (copy of overlay), matrix.html, insarmaps.log, urls.log, download_commands.txt. Overwritten/recreated; no backups.

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

    # Set flyToDatasetCenter=false to prevent auto-recentering when data loads
    sed -i.bak -E "s|flyToDatasetCenter=true|flyToDatasetCenter=false|g" "$log_file"

    rm -f "${log_file}.bak"

    echo "Updated all coordinates in insarmaps.log and disabled flyToDatasetCenter"
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
      --no-ingest-los                 Skip ingesting both input files with --ref-lalo (default: ingest-los is enabled)
      --no-insarmaps                  Skip running ingest_insarmaps.bash (default: insarmaps ingestion is enabled)
      --debug                         Enable debug mode (set -x)

  Output: data_files.txt, *vert*.he5, *horz*.he5, maskTempCoh.h5, image_pairs.txt, geometryRadar.h5 (in Sen*).
  Other: overlay.html, index.html (copy of overlay), matrix.html, insarmaps.log, urls.log, download_commands.txt. Overwritten/recreated; no backups.
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
        -?*|--*)
            echo "Error: Unknown option: $1"
            echo "Use $SCRIPT_NAME --help for available options"
            exit 1
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

set -- "${positional[@]}"

# Validate --ref-lalo type if provided
validate_ref_lalo() {
    local arr=("$@")
    [[ ${#arr[@]} -eq 0 ]] && return 0
    local lat lon
    if [[ ${#arr[@]} -eq 1 ]]; then
        [[ "${arr[0]}" != *","* ]] && { echo "Error: --ref-lalo must be LAT,LON or LAT LON (e.g. --ref-lalo 36.87,25.94)"; exit 1; }
        IFS=',' read -ra parts <<< "${arr[0]}"
        [[ ${#parts[@]} -ne 2 ]] && { echo "Error: --ref-lalo must be LAT,LON or LAT LON"; exit 1; }
        lat="${parts[0]}" lon="${parts[1]}"
    else
        lat="${arr[0]}" lon="${arr[1]}"
    fi
    if ! [[ "$lat" =~ ^-?[0-9]+\.?[0-9]*$ ]] || ! [[ "$lon" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
        echo "Error: --ref-lalo requires numeric lat,lon (e.g. --ref-lalo 36.87 25.94)"
        exit 1
    fi
}
validate_ref_lalo "${ref_lalo[@]}"

# Check for required positional arguments
if [[ ${#positional[@]} -lt 2 ]]; then
    echo "Error: Two input files are required"
    echo "Usage: $SCRIPT_NAME <dir_or_file1> <dir_or_file2> [options]"
    echo "Use --help for more information"
    exit 1
fi

# Important workflow variables (UPPERCASE)
DIR_OR_FILE1="${positional[0]}"
DIR_OR_FILE2="${positional[1]}"

# Check for unknown extra positional arguments
if [[ ${#positional[@]} -gt 2 ]]; then
    echo "Warning: Unknown parameters provided: ${positional[@]:2}"
    echo "These will be ignored"
fi

# Enable debug mode if requested
[[ $debug_flag == "1" ]] && set -x

# Build the command for horzvert_timeseries.py (UPPERCASE - important script variable)
CMD="horzvert_timeseries.py \"$DIR_OR_FILE1\" \"$DIR_OR_FILE2\""

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
PROJECT_DIR=$(get_base_projectname "$DIR_OR_FILE1")
dir="$([ -f "$DIR_OR_FILE1" ] && dirname "$DIR_OR_FILE1" || echo "$DIR_OR_FILE1")"
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

# Skip insarmaps ingestion for --no-insarmaps
if [[ $ingest_insarmaps_flag == "0" ]]; then
    exit 0
fi

# Update data_footprint to match vert file for consistent map overlay (commented out for testing)
# copy_data_footprint.py "$VERT_FILE" "$HORZ_FILE" "$ORIGINAL_DIR/$DIR_OR_FILE1" "$ORIGINAL_DIR/$DIR_OR_FILE2"

echo "##############################################"
echo "ingest_insarmaps.bash $VERT_FILE"
ingest_insarmaps.bash "$VERT_FILE"
echo "$ORIGINAL_DIR/$HORZVERT_DIR/$VERT_FILE" >> $DATA_FILES_TXT

echo "##############################################"
echo "ingest_insarmaps.bash $HORZ_FILE"
ingest_insarmaps.bash "$HORZ_FILE"
echo "$ORIGINAL_DIR/$HORZVERT_DIR$HORZ_FILE" >> $DATA_FILES_TXT

# Ingest original input files, stay in HORZVERT_DIR so all entries go to the same insarmaps.log
# Infer --dataset from *.he5 filename: PS, DS, or filt*DS (use filt*DS with * for codebase consistency)
get_ingest_dataset_opt() {
    local path="$1"
    local abs_path="$ORIGINAL_DIR/$path"
    local he5_basename=""
    if [[ -f "$abs_path" && "$abs_path" == *.he5 ]]; then
        he5_basename=$(basename "$abs_path")
    elif [[ -d "$abs_path" ]]; then
        he5_basename=$(basename "$(ls -t "$abs_path"/*.he5 2>/dev/null | head -n 1)")
    fi
    [[ -z "$he5_basename" ]] && return
    if [[ "$he5_basename" == *"PS"* ]]; then
        echo "PS"
    elif [[ "$he5_basename" == *"filt"* && "$he5_basename" == *"DS"* ]]; then
        echo "filt*DS"
    elif [[ "$he5_basename" == *"DS"* ]]; then
        echo "DS"
    fi
}
if [[ $ingest_los_flag == "1" ]]; then
    # DIR_OR_FILE1 and DIR_OR_FILE2 are relative to ORIGINAL_DIR
    cd "$ORIGINAL_DIR/$HORZVERT_DIR"
    echo "##############################################"
    ingest_dataset_opt1=$(get_ingest_dataset_opt "$DIR_OR_FILE1")
    if [[ -n "$ingest_dataset_opt1" ]]; then
        echo "ingest_insarmaps.bash $ORIGINAL_DIR/$DIR_OR_FILE1 --ref-lalo ${ref_lalo[*]} --dataset $ingest_dataset_opt1"
        ingest_insarmaps.bash "$ORIGINAL_DIR/$DIR_OR_FILE1" --ref-lalo "${ref_lalo[@]}" --dataset "$ingest_dataset_opt1"
    else
        echo "ingest_insarmaps.bash $ORIGINAL_DIR/$DIR_OR_FILE1 --ref-lalo ${ref_lalo[*]}"
        ingest_insarmaps.bash "$ORIGINAL_DIR/$DIR_OR_FILE1" --ref-lalo "${ref_lalo[@]}"
    fi
    FILE1_HE5=$(ls -t "$ORIGINAL_DIR/$DIR_OR_FILE1"/*.he5 2>/dev/null | head -n 1) || FILE1_HE5="$ORIGINAL_DIR/$DIR_OR_FILE1"
    echo "$FILE1_HE5" >> $DATA_FILES_TXT

    echo "##############################################"
    ingest_dataset_opt2=$(get_ingest_dataset_opt "$DIR_OR_FILE2")
    if [[ -n "$ingest_dataset_opt2" ]]; then
        echo "ingest_insarmaps.bash $ORIGINAL_DIR/$DIR_OR_FILE2 --ref-lalo ${ref_lalo[*]} --dataset $ingest_dataset_opt2"
        ingest_insarmaps.bash "$ORIGINAL_DIR/$DIR_OR_FILE2" --ref-lalo "${ref_lalo[@]}" --dataset "$ingest_dataset_opt2"
    else
        echo "ingest_insarmaps.bash $ORIGINAL_DIR/$DIR_OR_FILE2 --ref-lalo ${ref_lalo[*]}"
        ingest_insarmaps.bash "$ORIGINAL_DIR/$DIR_OR_FILE2" --ref-lalo "${ref_lalo[@]}"
    fi
    FILE2_HE5=$(ls -t "$ORIGINAL_DIR/$DIR_OR_FILE2"/*.he5 2>/dev/null | head -n 1) || FILE2_HE5="$ORIGINAL_DIR/$DIR_OR_FILE2"
    echo "$FILE2_HE5" >> $DATA_FILES_TXT

    # Normalize coordinates in insarmaps.log to use vert coordinates (we're already in HORZVERT_DIR)
    normalize_insarmaps_coordinates "insarmaps.log"

    # Copy HTML templates and create framepage URLs
    echo "##############################################"
    cd "$ORIGINAL_DIR"
    HTML_SOURCE="${SCRIPT_DIR}/../html"
    cp "$HTML_SOURCE"/*.html "$ORIGINAL_DIR/$HORZVERT_DIR/"
    cp "$ORIGINAL_DIR/$HORZVERT_DIR/overlay.html" "$ORIGINAL_DIR/$HORZVERT_DIR/index.html"
    write_insarmaps_framepage_urls.py "$HORZVERT_DIR" --outdir "$HORZVERT_DIR"
    create_data_download_commands.py "$DATA_FILES_TXT"

    echo "insarmaps frames created:"
    cat "$HORZVERT_DIR/urls.log"
fi

