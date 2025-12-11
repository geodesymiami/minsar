#!/usr/bin/env bash
# reference_point_hdfeos5.bash
# Wrapper script to change reference point in HDFEOS5 file
# Extracts components, updates reference point, and reconstructs HDFEOS5 file

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

echo "sourcing ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh ..."
source ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh
echo "sourcing ${SCRIPT_DIR}/../lib/utils.sh ..."
source ${SCRIPT_DIR}/../lib/utils.sh
echo "sourcing ${SCRIPT_DIR}/../lib/common_helpers.sh ..."
source ${SCRIPT_DIR}/../lib/common_helpers.sh

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Usage:
    $SCRIPT_NAME <input_file.he5> --ref-lalo <lat> <lon> [options]

Examples:
    $SCRIPT_NAME S1_vert_106_128_20180302_20180525.he5 --ref-lalo -0.81 -91.190
    $SCRIPT_NAME S1_vert_106_128_20180302_20180525.he5 --ref-lalo -0.81 -91.190 --output output.he5
    $SCRIPT_NAME S1_vert_106_128_20180302_20180525.he5 --ref-lalo -0.81,-91.190 --keep-extracted

Options:
    --ref-lalo LAT,LON or LAT LON   New reference point in latitude/longitude (required)
    --output FILE                    Output HDFEOS5 filename (default: overwrite input with backup)
    --keep-extracted                 Keep extracted intermediate files (default: remove after processing)
    --help, -h                       Show this help message
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

# Initialize option parsing variables
positional=()
ref_lalo=()
output_file=""
keep_extracted=0

# Parse command line arguments
while [[ $# -gt 0 ]]
do
    key="$1"

    case $key in
        --ref-lalo)
            shift
            ref_lalo=()
            if [[ "$1" == *,* ]]; then
                # Handle comma-separated format: LAT,LON
                ref_lalo=("$1")
            else
                # Handle space-separated format: LAT LON
                ref_lalo=("$1" "$2")
                shift
            fi
            shift
            ;;
        --output)
            output_file="$2"
            shift 2
            ;;
        --keep-extracted)
            keep_extracted=1
            shift
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

set -- "${positional[@]}"

# Check for required arguments
if [[ ${#positional[@]} -lt 1 ]]; then
    echo "Error: Input HDFEOS5 file is required"
    echo "Usage: $SCRIPT_NAME <input_file.he5> --ref-lalo <lat> <lon> [options]"
    echo "Use --help for more information"
    exit 1
fi

if [[ ${#ref_lalo[@]} -eq 0 ]]; then
    echo "Error: --ref-lalo is required"
    echo "Usage: $SCRIPT_NAME <input_file.he5> --ref-lalo <lat> <lon> [options]"
    echo "Use --help for more information"
    exit 1
fi

INPUT_FILE="${positional[0]}"

# Convert to absolute path
INPUT_FILE=$(readlink -f "$INPUT_FILE" 2>/dev/null || realpath "$INPUT_FILE" 2>/dev/null || echo "$INPUT_FILE")
if [[ ! "$INPUT_FILE" =~ ^/ ]]; then
    # If still relative, make it absolute from current directory
    INPUT_FILE="$PWD/$INPUT_FILE"
fi

# Check if input file exists
if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: Input file not found: $INPUT_FILE"
    exit 1
fi

# Get input file directory and basename
INPUT_DIR=$(dirname "$INPUT_FILE")
INPUT_BASENAME=$(basename "$INPUT_FILE")

# update_attr=$(python3 -c "import h5py; f=h5py.File('$INPUT_FILE', 'r'); print(f'{f.attrs.get(\"mintpy.save.hdfEos5.update\", \"no\")}')" 2>/dev/null || echo "no")
# if [[ "$update_attr" == "yes" ]]; then
if  [[ "$INPUT_FILE" == *"XXXXXXXX"* ]] ; then
    UPDATE_MODE="--update"
else
    UPDATE_MODE=""
fi

# checks whether filename contains a SUFFIX (non-11 characters. If 11 don't start with N or S)
SUFFIX=$(echo "$INPUT_BASENAME" | awk -F'[_.]' '{s=$(NF-1); if (length(s)<11) print s; else if (length(s)==11 && s !~ /^[SN]/) print s; else print ""}');
if [[ -n "$SUFFIX" ]]; then
    SUFFIX_FLAG="--suffix ${SUFFIX}"
else
    SUFFIX_FLAG=""
fi

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

echo "Input file: $INPUT_FILE"
echo "New reference point: lat=$REF_LAT, lon=$REF_LON"

OUTPUT_FILE="$INPUT_FILE"

OUTPUT_BASENAME=$(basename "$OUTPUT_FILE")
echo "Output file: $OUTPUT_FILE" 

# Step 1: Extract HDFEOS5 components
echo "####################################"
echo "Step 1: Extracting HDFEOS5 component"

EXTRACT_CMD="extract_hdfeos5.py \"$INPUT_FILE\" --all"
echo "Running: $EXTRACT_CMD"
eval $EXTRACT_CMD

# Determine coordinate system by checking for geo_ prefix
if [[ -f "$INPUT_DIR/geo_timeseries.h5" ]]; then
    COORDS="GEO"
 elif [[ -f "$INPUT_DIR/timeseries.h5" ]]; then
    COORDS="RADAR"
else
    echo "Error: Could not find extracted timeseries file"
    exit 1
fi
echo "Detected coordinate system: $COORDS"

if [[ "$COORDS" == "RADAR" ]]; then
    REF_CMD="reference_point.py timeseries.h5 --lookup geometryRadar.h5 --lat $REF_LAT --lon $REF_LON ; add_ref_lalo_to_file timeseries.h5 --ref-lalo $REF_LAT $REF_LON"
    SAVE_CMD="save_hdfeos5.py timeseries.h5 --tc temporalCoherence.h5 --asc avgSpatialCoherence.h5 -m mask.h5 -g geometryRadar.h5 --subset $UPDATE_MODE $SUFFIX_FLAG"
    EXTRACTED_FILES=("timeseries.h5" "mask.h5" "temporalCoherence.h5" "avgSpatialCoherence.h5" "geometryRadar.h5" "shadowMask.h5")
else
    REF_CMD="reference_point.py geo_timeseries.h5 --lat $REF_LAT --lon $REF_LON"
    SAVE_CMD="save_hdfeos5.py geo_timeseries.h5 --tc geo_temporalCoherence.h5 --asc geo_avgSpatialCoherence.h5 -m geo_mask.h5 -g geo_geometryRadar.h5 --subset $UPDATE_MODE $SUFFIX_FLAG"
    EXTRACTED_FILES=("geo_timeseries.h5" "geo_mask.h5" "geo_temporalCoherence.h5" "geo_avgSpatialCoherence.h5" "geo_geometryRadar.h5" "geo_shadowMask.h5")
fi


echo "Step 2: Changing reference point"
cd $INPUT_DIR
echo "Running: $REF_CMD"
eval $REF_CMD

echo "Step 3: Reconstructing HDFEOS5 file"
echo "Running: $SAVE_CMD"
eval $SAVE_CMD

echo "HDFEOS5 file reconstructed: $OUTPUT_FILE"

# Step 4: Cleanup (if not --keep-extracted)
if [[ $keep_extracted -eq 0 ]]; then
    for file in "${EXTRACTED_FILES[@]}"; do
        if [[ -f "$file" ]]; then
            rm -f "$file"
        fi
    done
fi

echo "####################################"
echo "Done! Output file: $OUTPUT_FILE"
echo "####################################"

