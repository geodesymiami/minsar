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

echo "Input file: $INPUT_FILE" | tee -a "$LOG_FILE"
echo "New reference point: lat=$REF_LAT, lon=$REF_LON" | tee -a "$LOG_FILE"

# Determine output filename
if [[ -z "$output_file" ]]; then
    # Create backup and overwrite original
    BACKUP_FILE="${INPUT_FILE}.bak"
    echo "Creating backup: $BACKUP_FILE" | tee -a "$LOG_FILE"
    cp "$INPUT_FILE" "$BACKUP_FILE"
    OUTPUT_FILE="$INPUT_FILE"
else
    # Convert output to absolute path if relative
    if [[ ! "$output_file" =~ ^/ ]]; then
        OUTPUT_FILE="$PWD/$output_file"
    else
        OUTPUT_FILE="$output_file"
    fi
    OUTPUT_DIR=$(dirname "$OUTPUT_FILE")
    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"
fi

OUTPUT_BASENAME=$(basename "$OUTPUT_FILE")
echo "Output file: $OUTPUT_FILE" | tee -a "$LOG_FILE"

# Step 1: Extract HDFEOS5 components
echo "####################################" | tee -a "$LOG_FILE"
echo "Step 1: Extracting HDFEOS5 components" | tee -a "$LOG_FILE"
echo "####################################" | tee -a "$LOG_FILE"

EXTRACT_CMD="extract_hdfeos5.py \"$INPUT_FILE\" --all"
echo "Running: $EXTRACT_CMD" | tee -a "$LOG_FILE"
eval $EXTRACT_CMD

# Determine coordinate system by checking for geo_ prefix
if [[ -f "geo_timeseries.h5" ]]; then
    COORDS="GEO"
    TS_FILE="geo_timeseries.h5"
    MASK_FILE="geo_mask.h5"
    TCOH_FILE="geo_temporalCoherence.h5"
    SCOH_FILE="geo_avgSpatialCoherence.h5"
    GEOM_FILE="geo_geometryRadar.h5"
    SHADOW_FILE="geo_shadowMask.h5"
elif [[ -f "timeseries.h5" ]]; then
    COORDS="RADAR"
    TS_FILE="timeseries.h5"
    MASK_FILE="mask.h5"
    TCOH_FILE="temporalCoherence.h5"
    SCOH_FILE="avgSpatialCoherence.h5"
    GEOM_FILE="geometryRadar.h5"
    SHADOW_FILE="shadowMask.h5"
else
    echo "Error: Could not find extracted timeseries file" | tee -a "$LOG_FILE"
    exit 1
fi

echo "Detected coordinate system: $COORDS" | tee -a "$LOG_FILE"
echo "Timeseries file: $TS_FILE" | tee -a "$LOG_FILE"

# Verify all required files exist
REQUIRED_FILES=("$TS_FILE" "$MASK_FILE" "$TCOH_FILE" "$SCOH_FILE" "$GEOM_FILE")
for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "Error: Required extracted file not found: $file" | tee -a "$LOG_FILE"
        exit 1
    fi
done

# Step 2: Change reference point
echo "####################################" | tee -a "$LOG_FILE"
echo "Step 2: Changing reference point" | tee -a "$LOG_FILE"
echo "####################################" | tee -a "$LOG_FILE"

if [[ "$COORDS" == "RADAR" ]]; then
    # REF_CMD="reference_point.py timeseries.h5 --lookup inputs/geometryRadar.h5 --lat $REF_LAT --lon $REF_LON"
    #REF_CMD="reference_point.py timeseries.h5 --lookup inputs/geometryRadar.h5 --lat $REF_LAT --lon $REF_LON ; add_ref_lalo_to_file timeseries.h5 --ref-lalo $REF_LAT $REF_LON"
    REF_CMD="reference_point.py timeseries.h5 --lookup geometryRadar.h5 --lat $REF_LAT --lon $REF_LON ; add_ref_lalo_to_file timeseries.h5 --ref-lalo $REF_LAT $REF_LON"

else
    REF_CMD="reference_point.py geo_timeseries.h5 --lat $REF_LAT --lon $REF_LON"
fi

echo "Running: $REF_CMD" | tee -a "$LOG_FILE"
eval $REF_CMD

# Step 3: Reconstruct HDFEOS5 file
echo "####################################" | tee -a "$LOG_FILE"
echo "Step 3: Reconstructing HDFEOS5 file" | tee -a "$LOG_FILE"
echo "####################################" | tee -a "$LOG_FILE"

# Get list of existing .he5 files before running save_hdfeos5.py
EXISTING_HE5_FILES=$(ls -1 *.he5 2>/dev/null | sort || echo "")

SAVE_CMD="save_hdfeos5.py \"$TS_FILE\" --tc \"$TCOH_FILE\" --asc \"$SCOH_FILE\" -m \"$MASK_FILE\" -g \"$GEOM_FILE\""
echo "Running: $SAVE_CMD" | tee -a "$LOG_FILE"
eval $SAVE_CMD

# Find the newly created .he5 file (the one that wasn't there before)
ALL_HE5_FILES=$(ls -1 *.he5 2>/dev/null | sort || echo "")
GENERATED_FILE=""

# Compare lists to find new file
while IFS= read -r file; do
    if ! echo "$EXISTING_HE5_FILES" | grep -q "^${file}$"; then
        GENERATED_FILE="$file"
        break
    fi
done <<< "$ALL_HE5_FILES"

# If we couldn't find it by comparison, use the most recently modified .he5 file
# (excluding the input file and backup)
if [[ -z "$GENERATED_FILE" ]]; then
    GENERATED_FILE=$(ls -t *.he5 2>/dev/null | grep -v "$INPUT_BASENAME" | grep -v ".bak$" | head -1 || echo "")
fi

if [[ -z "$GENERATED_FILE" ]]; then
    echo "Error: Could not determine generated HDFEOS5 file" | tee -a "$LOG_FILE"
    exit 1
fi

echo "Generated file: $GENERATED_FILE" | tee -a "$LOG_FILE"

# Rename to desired output filename if different
if [[ "$GENERATED_FILE" != "$OUTPUT_BASENAME" ]]; then
    echo "Moving $GENERATED_FILE to $OUTPUT_FILE" | tee -a "$LOG_FILE"
    mv "$GENERATED_FILE" "$OUTPUT_FILE"
fi

# Verify output file exists
if [[ ! -f "$OUTPUT_FILE" ]]; then
    echo "Error: Output file was not created: $OUTPUT_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

echo "HDFEOS5 file reconstructed: $OUTPUT_FILE" | tee -a "$LOG_FILE"

# Step 4: Cleanup (if not --keep-extracted)
if [[ $keep_extracted -eq 0 ]]; then
    echo "####################################" | tee -a "$LOG_FILE"
    echo "Step 4: Cleaning up extracted files" | tee -a "$LOG_FILE"
    echo "####################################" | tee -a "$LOG_FILE"

    EXTRACTED_FILES=("$TS_FILE" "$MASK_FILE" "$TCOH_FILE" "$SCOH_FILE" "$GEOM_FILE" "$SHADOW_FILE")
    for file in "${EXTRACTED_FILES[@]}"; do
        if [[ -f "$file" ]]; then
            echo "Removing: $file" | tee -a "$LOG_FILE"
            rm -f "$file"
        fi
    done
    echo "Cleanup complete" | tee -a "$LOG_FILE"
else
    echo "Keeping extracted files (--keep-extracted flag set)" | tee -a "$LOG_FILE"
fi

echo "####################################" | tee -a "$LOG_FILE"
echo "Done! Output file: $OUTPUT_FILE" | tee -a "$LOG_FILE"
echo "####################################" | tee -a "$LOG_FILE"

