#!/usr/bin/env bash
# harmonize_geocoding.bash
# Harmonizes geocoding of FILE2 to match FILE1
# Original FILE2 is backed up as FILE2.orig; harmonized file replaces original

set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

# Function to read HDF5 attribute using MintPy
read_attribute() {
    local file="$1"
    local attr="$2"
    python -c "from mintpy.utils import readfile; import sys; atr = readfile.read_attribute('$file'); print(atr.get('$attr', ''))" 2>/dev/null || echo ""
}

# Function to determine coordinate system (GEO vs RADAR)
# Fast check using only metadata, not reading data
determine_coordinates() {
    local file="$1"
    python -c "
from mintpy.utils import readfile
try:
    attr = readfile.read_attribute('$file')
    if 'Y_FIRST' in attr:
        print('GEO')
    else:
        print('RADAR')
except Exception:
    print('RADAR')
" 2>/dev/null || echo "RADAR"
}

# Function to find .he5 file from directory or file path
# Excludes *_radar.he5 and *.he5.orig files
find_he5_file() {
    local path="$1"
    
    if [[ -f "$path" && "$path" == *.he5 ]]; then
        # Skip radar and backup files
        if [[ "$path" == *_radar.he5 || "$path" == *.he5.orig ]]; then
            echo ""
        else
            echo "$path"
        fi
    elif [[ -d "$path" ]]; then
        # Find youngest .he5 file in directory, excluding radar and backup files
        local he5_file=$(ls -t "$path"/*.he5 2>/dev/null | grep -v "_radar.he5$" | grep -v ".he5.orig$" | head -1)
        if [[ -n "$he5_file" ]]; then
            echo "$he5_file"
        else
            echo ""
        fi
    else
        echo ""
    fi
}

# Function to find geometry lookup file
find_geometry_file() {
    local he5_file="$1"
    local he5_dir=$(dirname "$he5_file")
    
    # Check common locations
    for geom_path in \
        "$he5_dir/inputs/geometryRadar.h5" \
        "$he5_dir/../inputs/geometryRadar.h5" \
        "$he5_dir/geometryRadar.h5"; do
        if [[ -f "$geom_path" ]]; then
            echo "$geom_path"
            return 0
        fi
    done
    
    echo ""
    return 1
}

# Help text
show_help() {
    cat << EOF
Usage: $SCRIPT_NAME FILE1 FILE2 [OPTIONS]

Harmonizes geocoding between two .he5 files by re-geocoding the second file
to match the spacing (Y_STEP, X_STEP) of the first file if needed.

Arguments:
    FILE1               First .he5 file or directory (reference spacing)
    FILE2               Second .he5 file or directory (to be harmonized)

Options:
    -h, --help          Show this help message
    --force             Force re-geocoding even if backup exists
    --keep-temp         Keep temporary files for debugging

Output:
    Prints the path to use for FILE2 (harmonized file replaces original)
    Original FILE2 is backed up as FILE2.orig
    Returns 0 on success, non-zero on error

Examples:
    $SCRIPT_NAME AlcedoEnvD140/mintpy/ AlcedoEnvA61/mintpy/
    $SCRIPT_NAME ChilesSenD142/mintpy/S1.he5 ChilesSenA120/mintpy/S1.he5

Notes:
    - Only works with geocoded files (coordinates = 'GEO')
    - Exits gracefully if files are in radar coordinates
    - Requires MintPy's geocode.py and geometryRadar.h5 lookup table
    - Uses FILE1's grid (spacing + bounding box) as template for FILE2

EOF
}

# Parse arguments
FORCE_REGEOCODE=0
KEEP_TEMP=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --force)
            FORCE_REGEOCODE=1
            shift
            ;;
        --keep-temp)
            KEEP_TEMP=1
            shift
            ;;
        -*)
            echo "Error: Unknown option: $1" >&2
            echo "Use --help for usage information" >&2
            exit 1
            ;;
        *)
            if [[ -z "$FILE1" ]]; then
                FILE1="$1"
            elif [[ -z "$FILE2" ]]; then
                FILE2="$1"
            else
                echo "Error: Too many arguments" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$FILE1" || -z "$FILE2" ]]; then
    echo "Error: Both FILE1 and FILE2 are required" >&2
    echo "Use --help for usage information" >&2
    exit 1
fi

# Find actual .he5 files
HE5_FILE1=$(find_he5_file "$FILE1")
HE5_FILE2=$(find_he5_file "$FILE2")

if [[ -z "$HE5_FILE1" ]]; then
    echo "Error: No .he5 file found for FILE1: $FILE1" >&2
    exit 1
fi

if [[ -z "$HE5_FILE2" ]]; then
    echo "Error: No .he5 file found for FILE2: $FILE2" >&2
    exit 1
fi

echo "" >&2
echo "Step 1: Checking for radar coordinates file..." >&2
echo "Checking geocoding..." >&2
echo "  File 1: $HE5_FILE1" >&2
echo "  File 2: $HE5_FILE2" >&2

# Check coordinate systems
COORDS1=$(determine_coordinates "$HE5_FILE1")
COORDS2=$(determine_coordinates "$HE5_FILE2")

echo "  Coordinate system File 1: $COORDS1" >&2
echo "  Coordinate system File 2: $COORDS2" >&2

# Exit if either file is in radar coordinates
if [[ "$COORDS1" == "RADAR" || "$COORDS2" == "RADAR" ]]; then
    echo "One or both files are in radar coordinates - no harmonization needed" >&2
    echo "$FILE2"
    exit 0
fi

# Read grid parameters from files
Y_STEP1=$(read_attribute "$HE5_FILE1" "Y_STEP")
X_STEP1=$(read_attribute "$HE5_FILE1" "X_STEP")
Y_FIRST1=$(read_attribute "$HE5_FILE1" "Y_FIRST")
X_FIRST1=$(read_attribute "$HE5_FILE1" "X_FIRST")
LENGTH1=$(read_attribute "$HE5_FILE1" "LENGTH")
WIDTH1=$(read_attribute "$HE5_FILE1" "WIDTH")

Y_STEP2=$(read_attribute "$HE5_FILE2" "Y_STEP")
X_STEP2=$(read_attribute "$HE5_FILE2" "X_STEP")

if [[ -z "$Y_STEP1" || -z "$X_STEP1" || -z "$Y_FIRST1" || -z "$X_FIRST1" || -z "$LENGTH1" || -z "$WIDTH1" ]]; then
    echo "Error: Could not read grid parameters from File 1" >&2
    exit 1
fi

if [[ -z "$Y_STEP2" || -z "$X_STEP2" ]]; then
    echo "Error: Could not read Y_STEP/X_STEP from File 2" >&2
    exit 1
fi

# Calculate FILE1's bounding box (SNWE format for geocode.py)
# Note: Y_STEP is negative for geo coordinates
LAT_NORTH="$Y_FIRST1"
LAT_SOUTH=$(python3 -c "print($Y_FIRST1 + ($LENGTH1) * $Y_STEP1)")
LON_WEST="$X_FIRST1"
LON_EAST=$(python3 -c "print($X_FIRST1 + ($WIDTH1) * $X_STEP1)")
BBOX_SNWE="$LAT_SOUTH $LAT_NORTH $LON_WEST $LON_EAST"

echo "  File 1 spacing: Y_STEP=$Y_STEP1, X_STEP=$X_STEP1" >&2
echo "  File 1 bounds: SNWE=($BBOX_SNWE)" >&2
echo "  File 2 spacing: Y_STEP=$Y_STEP2, X_STEP=$X_STEP2" >&2

# Check if spacing matches
if [[ "$Y_STEP1" == "$Y_STEP2" && "$X_STEP1" == "$X_STEP2" ]]; then
    echo "Files have identical spacing" >&2
    echo "$FILE2"
    exit 0
fi

# Spacing differs - need to regeocode File 2
echo "Files have different spacing - re-geocoding File 2 to match File 1..." >&2

# Setup filenames
HE5_DIR2=$(dirname "$HE5_FILE2")
HE5_BASE2=$(basename "$HE5_FILE2" .he5)
HARMONIZED_FILE="$HE5_FILE2"

# Check if we should skip (backup exists and not forcing)
ORIG_FILE="${HE5_FILE2}.orig"
if [[ -f "$ORIG_FILE" && $FORCE_REGEOCODE -eq 0 ]]; then
    echo "Backup file already exists - using current file" >&2
    echo "$HARMONIZED_FILE"
    exit 0
fi

# Find geometry lookup file
GEOMETRY_FILE=$(find_geometry_file "$HE5_FILE2")
if [[ -z "$GEOMETRY_FILE" ]]; then
    echo "Error: Could not find geometryRadar.h5 lookup file for File 2" >&2
    echo "Searched locations:" >&2
    echo "  $HE5_DIR2/inputs/geometryRadar.h5" >&2
    echo "  $HE5_DIR2/../inputs/geometryRadar.h5" >&2
    echo "  $HE5_DIR2/geometryRadar.h5" >&2
    exit 1
fi

echo "Using geometry lookup file: $GEOMETRY_FILE" >&2

# Get absolute paths
HE5_FILE1_ABS=$(cd "$(dirname "$HE5_FILE1")" && pwd)/$(basename "$HE5_FILE1")
HE5_FILE2_ABS=$(cd "$(dirname "$HE5_FILE2")" && pwd)/$(basename "$HE5_FILE2")
GEOMETRY_FILE_ABS=$(cd "$(dirname "$GEOMETRY_FILE")" && pwd)/$(basename "$GEOMETRY_FILE")
HARMONIZED_FILE_ABS="$HE5_FILE2_ABS"
ORIG_FILE_ABS="${HE5_FILE2_ABS}.orig"

# Create temporary directory in working dir
TEMP_DIR="$(cd "$HE5_DIR2" && pwd)/tmp_harmonize_$$_${RANDOM}"
mkdir -p "$TEMP_DIR"
echo "Created temporary directory: $TEMP_DIR" >&2

# Cleanup on exit
cleanup_temp() {
    if [[ $KEEP_TEMP -eq 1 ]]; then
        echo "Keeping temporary directory: $TEMP_DIR" >&2
    else
        [[ -d "$TEMP_DIR" ]] && rm -rf "$TEMP_DIR"
    fi
}
trap cleanup_temp EXIT INT TERM

# Save current directory
ORIGINAL_DIR=$(pwd)

# Step 1: Extract geo .he5
echo "" >&2
echo "Step 1: Extracting geo .he5..." >&2
cd "$HE5_DIR2"
HE5_BASENAME=$(basename "$HE5_FILE2_ABS")
if ! extract_hdfeos5.py "$HE5_BASENAME" --all >&2; then
    echo "Error: extract_hdfeos5.py failed" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

# Move extracted files to temp dir
for geo_file in geo_*.h5; do
    if [[ -f "$geo_file" ]]; then
        mv "$geo_file" "$TEMP_DIR/"
    fi
done

# Find extracted geo files in temp dir
cd "$TEMP_DIR"
GEO_TIMESERIES=$(ls geo_timeseries.h5 2>/dev/null || echo "")
GEO_MASK=$(ls geo_mask.h5 2>/dev/null || echo "")
GEO_TEMP_COH=$(ls geo_temporalCoherence.h5 2>/dev/null || echo "")
GEO_AVG_COH=$(ls geo_avgSpatialCoherence.h5 2>/dev/null || echo "")
GEO_GEOM=$(ls geo_geometryRadar.h5 2>/dev/null || echo "")

if [[ -z "$GEO_TIMESERIES" ]]; then
    echo "Error: No geo_timeseries.h5 found after extraction" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

echo "Found extracted files in temp dir" >&2

# Step 2: Convert geo files to radar
echo "" >&2
echo "Step 2: Converting to radar coordinates..." >&2

# Convert timeseries
RADAR_TIMESERIES="timeseries.h5"
echo "  Converting timeseries..." >&2
echo "    geocode.py $GEO_TIMESERIES -l $GEOMETRY_FILE_ABS --geo2radar -o $RADAR_TIMESERIES" >&2
if ! geocode.py "$GEO_TIMESERIES" -l "$GEOMETRY_FILE_ABS" --geo2radar -o "$RADAR_TIMESERIES" >&2; then
    echo "Error: Failed to convert timeseries to radar" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

# Convert mask
RADAR_MASK=""
if [[ -n "$GEO_MASK" ]]; then
    RADAR_MASK="mask.h5"
    echo "  Converting mask..." >&2
    echo "    geocode.py $GEO_MASK -l $GEOMETRY_FILE_ABS --geo2radar -o $RADAR_MASK" >&2
    if ! geocode.py "$GEO_MASK" -l "$GEOMETRY_FILE_ABS" --geo2radar -o "$RADAR_MASK" >&2; then
        echo "Warning: Failed to convert mask" >&2
        RADAR_MASK=""
    fi
fi

# Convert temporalCoherence
RADAR_TEMP_COH=""
if [[ -n "$GEO_TEMP_COH" ]]; then
    RADAR_TEMP_COH="temporalCoherence.h5"
    echo "  Converting temporalCoherence..." >&2
    echo "    geocode.py $GEO_TEMP_COH -l $GEOMETRY_FILE_ABS --geo2radar -o $RADAR_TEMP_COH" >&2
    if ! geocode.py "$GEO_TEMP_COH" -l "$GEOMETRY_FILE_ABS" --geo2radar -o "$RADAR_TEMP_COH" >&2; then
        echo "Warning: Failed to convert temporalCoherence" >&2
        RADAR_TEMP_COH=""
    fi
fi

# Convert avgSpatialCoherence
RADAR_AVG_COH=""
if [[ -n "$GEO_AVG_COH" ]]; then
    RADAR_AVG_COH="avgSpatialCoherence.h5"
    echo "  Converting avgSpatialCoherence..." >&2
    echo "    geocode.py $GEO_AVG_COH -l $GEOMETRY_FILE_ABS --geo2radar -o $RADAR_AVG_COH" >&2
    if ! geocode.py "$GEO_AVG_COH" -l "$GEOMETRY_FILE_ABS" --geo2radar -o "$RADAR_AVG_COH" >&2; then
        echo "Warning: Failed to convert avgSpatialCoherence" >&2
        RADAR_AVG_COH=""
    fi
fi

# Convert geometry
RADAR_GEOM=""
if [[ -n "$GEO_GEOM" ]]; then
    RADAR_GEOM="geometryRadar.h5"
    echo "  Converting geometry..." >&2
    echo "    geocode.py $GEO_GEOM -l $GEOMETRY_FILE_ABS --geo2radar -o $RADAR_GEOM" >&2
    if ! geocode.py "$GEO_GEOM" -l "$GEOMETRY_FILE_ABS" --geo2radar -o "$RADAR_GEOM" >&2; then
        echo "Warning: Failed to convert geometry" >&2
        RADAR_GEOM=""
    fi
fi

# Step 3: Re-geocode all files using FILE1's grid (step size + bounding box)
echo "" >&2
echo "Step 3: Re-geocoding with new spacing (Y_STEP=$Y_STEP1, X_STEP=$X_STEP1)..." >&2

# Re-geocode timeseries using FILE1's grid (step size + bounding box)
NEW_TIMESERIES="geo_timeseries.h5"
echo "  Re-geocoding timeseries..." >&2
echo "    geocode.py $RADAR_TIMESERIES --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l $GEOMETRY_FILE_ABS -o $NEW_TIMESERIES" >&2
if ! geocode.py "$RADAR_TIMESERIES" --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l "$GEOMETRY_FILE_ABS" -o "$NEW_TIMESERIES" >&2; then
    echo "Error: geocode.py failed for timeseries" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

NEW_MASK=""
if [[ -n "$RADAR_MASK" ]]; then
    NEW_MASK="geo_mask.h5"
    echo "  Re-geocoding mask..." >&2
    echo "    geocode.py $RADAR_MASK --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l $GEOMETRY_FILE_ABS -o $NEW_MASK" >&2
    if ! geocode.py "$RADAR_MASK" --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l "$GEOMETRY_FILE_ABS" -o "$NEW_MASK" >&2; then
        echo "Warning: Failed to re-geocode mask" >&2
        NEW_MASK=""
    fi
fi

NEW_TEMP_COH=""
if [[ -n "$RADAR_TEMP_COH" ]]; then
    NEW_TEMP_COH="geo_temporalCoherence.h5"
    echo "  Re-geocoding temporalCoherence..." >&2
    echo "    geocode.py $RADAR_TEMP_COH --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l $GEOMETRY_FILE_ABS -o $NEW_TEMP_COH" >&2
    if ! geocode.py "$RADAR_TEMP_COH" --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l "$GEOMETRY_FILE_ABS" -o "$NEW_TEMP_COH" >&2; then
        echo "Warning: Failed to re-geocode temporalCoherence" >&2
        NEW_TEMP_COH=""
    fi
fi

NEW_AVG_COH=""
if [[ -n "$RADAR_AVG_COH" ]]; then
    NEW_AVG_COH="geo_avgSpatialCoherence.h5"
    echo "  Re-geocoding avgSpatialCoherence..." >&2
    echo "    geocode.py $RADAR_AVG_COH --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l $GEOMETRY_FILE_ABS -o $NEW_AVG_COH" >&2
    if ! geocode.py "$RADAR_AVG_COH" --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l "$GEOMETRY_FILE_ABS" -o "$NEW_AVG_COH" >&2; then
        echo "Warning: Failed to re-geocode avgSpatialCoherence" >&2
        NEW_AVG_COH=""
    fi
fi

NEW_GEOM=""
if [[ -n "$RADAR_GEOM" ]]; then
    NEW_GEOM="geo_geometryRadar.h5"
    echo "  Re-geocoding geometry..." >&2
    echo "    geocode.py $RADAR_GEOM --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l $GEOMETRY_FILE_ABS -o $NEW_GEOM" >&2
    if ! geocode.py "$RADAR_GEOM" --lalo-step $Y_STEP1 $X_STEP1 --bbox $BBOX_SNWE -l "$GEOMETRY_FILE_ABS" -o "$NEW_GEOM" >&2; then
        echo "Warning: Failed to re-geocode geometry" >&2
        NEW_GEOM=""
    fi
fi

# Step 4: Package back to .he5
echo "" >&2
echo "Step 4: Packaging to .he5..." >&2

# Build save_hdfeos5.py command
SAVE_CMD="save_hdfeos5.py $NEW_TIMESERIES"
[[ -n "$NEW_TEMP_COH" ]] && SAVE_CMD="$SAVE_CMD --tc $NEW_TEMP_COH"
[[ -n "$NEW_AVG_COH" ]] && SAVE_CMD="$SAVE_CMD --asc $NEW_AVG_COH"
[[ -n "$NEW_MASK" ]] && SAVE_CMD="$SAVE_CMD -m $NEW_MASK"
[[ -n "$NEW_GEOM" ]] && SAVE_CMD="$SAVE_CMD -g $NEW_GEOM"

echo "  $SAVE_CMD" >&2
if ! eval $SAVE_CMD >&2; then
    echo "Error: save_hdfeos5.py failed" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

# Find generated .he5 file
GENERATED_HE5=$(ls *.he5 2>/dev/null | head -1)
if [[ -z "$GENERATED_HE5" || ! -f "$GENERATED_HE5" ]]; then
    echo "Error: Generated .he5 file not found" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

# Backup original and move harmonized file
cd "$ORIGINAL_DIR"
if [[ ! -f "$ORIG_FILE_ABS" ]]; then
    echo "Backing up original file..." >&2
    mv "$HE5_FILE2_ABS" "$ORIG_FILE_ABS"
fi

if ! mv "$TEMP_DIR/$GENERATED_HE5" "$HARMONIZED_FILE_ABS"; then
    echo "Error: Failed to move output file" >&2
    exit 1
fi

# Verify the harmonized file was created
if [[ ! -f "$HARMONIZED_FILE_ABS" ]]; then
    echo "Error: Harmonized file was not created: $HARMONIZED_FILE_ABS" >&2
    exit 1
fi

echo "Created harmonized file: $HARMONIZED_FILE_ABS" >&2
echo "$HARMONIZED_FILE_ABS"
exit 0
