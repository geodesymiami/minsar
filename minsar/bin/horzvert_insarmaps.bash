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

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Examples:
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.84969 -77.86430
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.84969 -77.86430 --dry-run
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.84969 -77.86430 --intervals 6
    $SCRIPT_NAME hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190
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

# Find the latest (youngest) *vert*.he5 and *horz*.he5 files
PROJECT_DIR=$(get_base_projectname "$FILE1")

# Store original directory before changing
ORIGINAL_DIR="$PWD"
cd $PROJECT_DIR
rm -f insarmaps.log
VERT_FILE=$(ls -t *vert*.he5 2>/dev/null | head -1)
HORZ_FILE=$(ls -t *horz*.he5 2>/dev/null | head -1)

echo "Found vert file: $VERT_FILE"
echo "Found horz file: $HORZ_FILE"

echo "##############################################"
ingest_insarmaps.bash "$VERT_FILE"

echo "##############################################"
ingest_insarmaps.bash "$HORZ_FILE"

# Ingest original input files (default behavior, skip if --no-ingest-los is set)
# Stay in PROJECT_DIR so all insarmaps.log entries go to the same file
if [[ $ingest_los_flag == "1" ]]; then
    # FILE1 and FILE2 are relative to ORIGINAL_DIR, so from PROJECT_DIR use ../FILE1 and ../FILE2
    echo "##############################################"
    ingest_insarmaps.bash "../$FILE1" --ref-lalo "${ref_lalo[@]}"
    FILE1_HE5=$(ls -t "../$FILE1"/*.he5 2>/dev/null | head -n 1) || FILE1_HE5="../$FILE1"
    flight_direction=$(get_flight_direction.py "$FILE1_HE5")

    echo "##############################################"
    ingest_insarmaps.bash "../$FILE2" --ref-lalo "${ref_lalo[@]}"
    FILE2_HE5=$(ls -t "../$FILE2"/*.he5 2>/dev/null | head -n 1) || FILE2_HE5="../$FILE2"
    flight_direction=$(get_flight_direction.py "$FILE2_HE5")
fi

# Write data_files.txt with all *he5 files used
echo "##############################################"
DATA_FILES_TXT="data_files.txt"
echo "Writing $PROJECT_DIR/$DATA_FILES_TXT with all *he5 files used..."
{
    # Always include vert and horz files (they are in PROJECT_DIR)
    [[ -n "$VERT_FILE" && -f "$VERT_FILE" ]] && get_path_without_scratchdir "$VERT_FILE"
    [[ -n "$HORZ_FILE" && -f "$HORZ_FILE" ]] && get_path_without_scratchdir "$HORZ_FILE"
    # Include FILE1 and FILE2 he5 files if they were ingested (paths are relative to PROJECT_DIR)
    if [[ $ingest_los_flag == "1" ]]; then
        [[ -n "$FILE1_HE5" && -f "$FILE1_HE5" && "$FILE1_HE5" == *.he5 ]] && get_path_without_scratchdir "$FILE1_HE5"
        [[ -n "$FILE2_HE5" && -f "$FILE2_HE5" && "$FILE2_HE5" == *.he5 ]] && get_path_without_scratchdir "$FILE2_HE5"
    fi
} > "$DATA_FILES_TXT"
echo "Created $PROJECT_DIR/$DATA_FILES_TXT with $(wc -l < "$DATA_FILES_TXT" | tr -d ' ') file(s)"

cd "$ORIGINAL_DIR"

# Create insarmaps framepage (using absolute paths since we're back in ORIGINAL_DIR)
echo "##############################################"
create_insarmaps_framepages.py "$PROJECT_DIR/insarmaps.log" --outdir "$PROJECT_DIR"
write_insarmaps_framepage_urls.py "$PROJECT_DIR" --outdir "$PROJECT_DIR"
create_data_download_commands.py "$PROJECT_DIR/data_files.txt"

echo "insarmaps frames created:"
cat "$PROJECT_DIR/frames_urls.log.

