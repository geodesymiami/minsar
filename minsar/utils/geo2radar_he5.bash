#!/usr/bin/env bash
# geo2radar_he5.bash
# Converts a geocoded .he5 file to radar coordinates
# Steps: extract_hdfeos5.py → geocode.py --geo2radar (on each file) → save_hdfeos5.py

set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

show_help() {
    cat << EOF
Usage: $SCRIPT_NAME INPUT_HE5_FILE [OUTPUT_HE5_FILE]

Converts a geocoded .he5 file to radar coordinates by:
  1. Extracting component files (extract_hdfeos5.py --all)
  2. Converting each file to radar coordinates (geocode.py --geo2radar)
  3. Packaging back to .he5 (save_hdfeos5.py)

Arguments:
    INPUT_HE5_FILE      Input geocoded .he5 file
    OUTPUT_HE5_FILE     Optional output filename (default: INPUT_radar.he5)

Options:
    -h, --help          Show this help message
    --keep-temp         Keep temporary files (for debugging)

Examples:
    $SCRIPT_NAME ENV_asc_061_mintpy_20030118_XXXXXXXX.he5
    $SCRIPT_NAME ENV_asc_061.he5 ENV_asc_061_radar.he5

Notes:
    - Input file must be in GEO coordinates
    - Requires geometryRadar.h5 lookup table in inputs/ directory
    - Creates temporary directory for intermediate files

EOF
}

# Parse arguments
KEEP_TEMP=0
INPUT_FILE=""
OUTPUT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --keep-temp)
            KEEP_TEMP=1
            shift
            ;;
        *)
            if [[ -z "$INPUT_FILE" ]]; then
                INPUT_FILE="$1"
            elif [[ -z "$OUTPUT_FILE" ]]; then
                OUTPUT_FILE="$1"
            else
                echo "Error: Too many arguments" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$INPUT_FILE" ]]; then
    echo "Error: Input file required" >&2
    echo "Use --help for usage information" >&2
    exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: Input file not found: $INPUT_FILE" >&2
    exit 1
fi

# Set default output filename
if [[ -z "$OUTPUT_FILE" ]]; then
    INPUT_BASE=$(basename "$INPUT_FILE" .he5)
    INPUT_DIR=$(dirname "$INPUT_FILE")
    OUTPUT_FILE="$INPUT_DIR/${INPUT_BASE}_radar.he5"
fi

# Get absolute paths
INPUT_FILE_ABS=$(cd "$(dirname "$INPUT_FILE")" && pwd)/$(basename "$INPUT_FILE")
OUTPUT_FILE_ABS=$(cd "$(dirname "$OUTPUT_FILE")" && pwd)/$(basename "$OUTPUT_FILE")

# Find geometry lookup file
INPUT_DIR=$(dirname "$INPUT_FILE_ABS")
GEOMETRY_FILE=""
for geom_path in \
    "$INPUT_DIR/inputs/geometryRadar.h5" \
    "$INPUT_DIR/../inputs/geometryRadar.h5" \
    "$INPUT_DIR/geometryRadar.h5"; do
    if [[ -f "$geom_path" ]]; then
        GEOMETRY_FILE="$geom_path"
        break
    fi
done

if [[ -z "$GEOMETRY_FILE" ]]; then
    echo "Error: Could not find geometryRadar.h5 lookup file" >&2
    echo "Searched locations:" >&2
    echo "  $INPUT_DIR/inputs/geometryRadar.h5" >&2
    echo "  $INPUT_DIR/../inputs/geometryRadar.h5" >&2
    echo "  $INPUT_DIR/geometryRadar.h5" >&2
    exit 1
fi

GEOMETRY_FILE_ABS=$(cd "$(dirname "$GEOMETRY_FILE")" && pwd)/$(basename "$GEOMETRY_FILE")

echo "Converting geocoded .he5 file to radar coordinates..."
echo "  Input:    $INPUT_FILE_ABS"
echo "  Output:   $OUTPUT_FILE_ABS"
echo "  Geometry: $GEOMETRY_FILE_ABS"

# Skip if output already exists
if [[ -f "$OUTPUT_FILE_ABS" ]]; then
    echo "Output file already exists: $OUTPUT_FILE_ABS"
    exit 0
fi

# Create temporary directory in working dir (use absolute path)
TEMP_DIR="$(cd "$INPUT_DIR" && pwd)/tmp_geo2radar_$$_${RANDOM}"
mkdir -p "$TEMP_DIR"
echo "  Temp dir: $TEMP_DIR"

# Cleanup function
cleanup_temp() {
    if [[ "$KEEP_TEMP" == "1" ]]; then
        echo "Keeping temporary directory: $TEMP_DIR"
    elif [[ -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup_temp EXIT INT TERM

ORIGINAL_DIR=$(pwd)

# Step 1: Extract .he5 file to component files (extracts to input file directory)
echo ""
echo "Step 1: Extracting component files..."
cd "$INPUT_DIR"
if ! extract_hdfeos5.py "$INPUT_FILE_ABS" --all; then
    echo "Error: extract_hdfeos5.py failed" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

# Find extracted geo_*.h5 files
GEO_FILES=(geo_*.h5)
if [[ ${#GEO_FILES[@]} -eq 0 || ! -f "${GEO_FILES[0]}" ]]; then
    echo "Error: No geo_*.h5 files found after extraction in $INPUT_DIR" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

echo "  Found ${#GEO_FILES[@]} files"
for geo_file in "${GEO_FILES[@]}"; do
    mv "$geo_file" "$TEMP_DIR/"
done

cd "$TEMP_DIR"
# Re-find files in temp dir
GEO_FILES=(geo_*.h5)

# Step 2: Convert each file to radar coordinates
echo ""
echo "Step 2: Converting files to radar coordinates..."
RADAR_FILES=()
RADAR_TIMESERIES=""
RADAR_MASK=""
RADAR_TEMP_COH=""
RADAR_AVG_COH=""
RADAR_GEOM=""

for geo_file in "${GEO_FILES[@]}"; do
    # Skip if already radar (shouldn't happen, but just in case)
    if [[ "$geo_file" != geo_* ]]; then
        continue
    fi
    
    # Generate radar filename
    radar_file="${geo_file#geo_}"
    
    echo "  Converting $geo_file → $radar_file"
    
    if ! geocode.py "$geo_file" -l "$GEOMETRY_FILE_ABS" --geo2radar -o "$radar_file"; then
        echo "Error: geocode.py --geo2radar failed for $geo_file" >&2
        cd "$ORIGINAL_DIR"
        exit 1
    fi
    
    RADAR_FILES+=("$radar_file")
    
    # Track specific files for save_hdfeos5.py
    case "$radar_file" in
        timeseries*.h5)
            RADAR_TIMESERIES="$radar_file"
            ;;
        mask*.h5)
            RADAR_MASK="$radar_file"
            ;;
        temporalCoherence*.h5)
            RADAR_TEMP_COH="$radar_file"
            ;;
        avgSpatialCoherence*.h5)
            RADAR_AVG_COH="$radar_file"
            ;;
        geometryRadar*.h5)
            RADAR_GEOM="$radar_file"
            ;;
    esac
done

echo ""
echo "Converted files:"
echo "  Timeseries: $RADAR_TIMESERIES"
echo "  Mask: ${RADAR_MASK:-not found}"
echo "  Temporal Coherence: ${RADAR_TEMP_COH:-not found}"
echo "  Avg Spatial Coherence: ${RADAR_AVG_COH:-not found}"
echo "  Geometry: ${RADAR_GEOM:-not found}"

if [[ -z "$RADAR_TIMESERIES" ]]; then
    echo "Error: Could not find radar timeseries file" >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

# Step 3: Package back to .he5 file
echo ""
echo "Step 3: Packaging back to .he5 file..."
cd "$TEMP_DIR"

# Build save_hdfeos5.py command with all available files
SAVE_CMD="save_hdfeos5.py $RADAR_TIMESERIES"
[[ -n "$RADAR_MASK" ]] && SAVE_CMD="$SAVE_CMD -m $RADAR_MASK"
[[ -n "$RADAR_TEMP_COH" ]] && SAVE_CMD="$SAVE_CMD --tc $RADAR_TEMP_COH"
[[ -n "$RADAR_AVG_COH" ]] && SAVE_CMD="$SAVE_CMD --asc $RADAR_AVG_COH"
[[ -n "$RADAR_GEOM" ]] && SAVE_CMD="$SAVE_CMD -g $RADAR_GEOM"

echo "Running: $SAVE_CMD"

# save_hdfeos5.py auto-generates output filename
if ! eval $SAVE_CMD; then
    echo "Error: save_hdfeos5.py failed" >&2
    echo "Files in temp dir:" >&2
    ls -la >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

# Find the generated .he5 file (should be newest .he5 file in temp dir)
GENERATED_HE5=$(ls -t *.he5 2>/dev/null | head -1)
if [[ -z "$GENERATED_HE5" || ! -f "$GENERATED_HE5" ]]; then
    echo "Error: Could not find generated .he5 file in $TEMP_DIR" >&2
    echo "Files in temp dir:" >&2
    ls -la >&2
    cd "$ORIGINAL_DIR"
    exit 1
fi

echo "  Generated .he5 file: $GENERATED_HE5"

# Move to desired output location
cd "$ORIGINAL_DIR"
if ! mv "$TEMP_DIR/$GENERATED_HE5" "$OUTPUT_FILE_ABS"; then
    echo "Error: Failed to move output file to $OUTPUT_FILE_ABS" >&2
    exit 1
fi

# Verify output file was created successfully before cleanup
if [[ ! -f "$OUTPUT_FILE_ABS" ]]; then
    echo "Error: Output file was not created: $OUTPUT_FILE_ABS" >&2
    exit 1
fi

echo ""
echo "Created: $OUTPUT_FILE_ABS"
exit 0
