#!/usr/bin/env bash
########################
# Author: Falk Amelung
#######################

set -euo pipefail

############################################################
# Help message
############################################################
show_help() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS] PATTERN

Check Envisat (ASA*) and ERS (SAR*) SLC files for valid ESA SAR data content.
Invalid files (containing HTML instead of SAR data) are written to invalid.txt in URL form.

ARGUMENTS:
    PATTERN         File pattern to check (e.g., "ASA*N1", "SAR*E2", "ASA_IMS_*.N1")
                    Note: Quote the pattern to prevent shell expansion, or let shell expand it

OPTIONS:
    -h, --help      Show this help message and exit
    -o, --output    Output file for invalid URLs (default: invalid.txt)

DESCRIPTION:
    This script checks Envisat (ASA*) and ERS (SAR*) SLC files to determine if they 
    contain valid ESA SAR data or invalid HTML content.
    
    Invalid files are written to the output file in URL format:
    - Envisat: https://esar-ds.eo.esa.int/oads/data/ASA_IMS_1P/[filename]
    - ERS:     https://esar-ds.eo.esa.int/oads/data/SAR_IMS_1P/[filename]

EXAMPLES:
    $(basename "$0") "ASA*N1"                           # Check Envisat data (pattern in quotes)
    $(basename "$0") ASA*N1                             # Let shell expand (recommended)
    $(basename "$0") "SAR*E2"                           # Check ERS data
    $(basename "$0") SAR*E2                             # ERS data with shell expansion
   

OUTPUT:
    Creates a file (default: invalid.txt) containing URLs of invalid files.
    Also prints a summary to stdout.


EOF
}

############################################################
# Default values
############################################################
OUTPUT_FILE="invalid.txt"
SEARCH_DIR="."
DEBUG_MODE=false
BASE_URL_ENVISAT="https://esar-ds.eo.esa.int/oads/data/ASA_IMS_1P"
BASE_URL_ERS="https://esar-ds.eo.esa.int/oads/data/SAR_IMS_1P"

############################################################
# Parse arguments
############################################################
if [[ $# -eq 0 ]]; then
    echo "Error: No file pattern provided"
    echo ""
    show_help
    exit 2
fi

PATTERN=""
FILES_FROM_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -o|--output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        --debug)
            DEBUG_MODE=true
            shift
            ;;
        -*)
            echo "Error: Unknown option: $1"
            echo ""
            show_help
            exit 2
            ;;
        *)
            # Collect all non-option arguments
            if [[ -z "$PATTERN" ]]; then
                PATTERN="$1"
            fi
            # If it's a file, add to FILES_FROM_ARGS
            if [[ -f "$1" ]]; then
                FILES_FROM_ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

if [[ "$DEBUG_MODE" == true ]]; then
    set -x
fi

############################################################
# Main script
############################################################

# Check if pattern is provided
if [[ -z "$PATTERN" ]]; then
    echo "Error: No file pattern provided"
    echo ""
    show_help
    exit 2
fi

# Change to search directory if specified
if [[ "$SEARCH_DIR" != "." ]]; then
    if [[ ! -d "$SEARCH_DIR" ]]; then
        echo "Error: Directory not found: $SEARCH_DIR"
        exit 2
    fi
    cd "$SEARCH_DIR"
fi

# Determine which files to check
if [[ ${#FILES_FROM_ARGS[@]} -gt 0 ]]; then
    # Files were provided as expanded arguments
    FILES=("${FILES_FROM_ARGS[@]}")
    echo "Checking ${#FILES[@]} file(s)..."
else
    # Find files matching the pattern
    mapfile -t FILES < <(find . -maxdepth 1 -name "$PATTERN" -type f | sort)
    
    if [[ ${#FILES[@]} -eq 0 ]]; then
        echo "Error: No files matching pattern '$PATTERN' found in $SEARCH_DIR"
        exit 2
    fi
    echo "Checking ${#FILES[@]} file(s) matching pattern: $PATTERN..."
fi

# Remove old output file if it exists
if [[ -f "$OUTPUT_FILE" ]]; then
    rm "$OUTPUT_FILE"
fi

# Initialize counters
INVALID_COUNT=0
VALID_COUNT=0
INVALID_FILES=()

# Check each file
for FILE in "${FILES[@]}"; do
    # Remove leading ./ from filename
    FILENAME=$(basename "$FILE")
    
    # Determine if this is ERS (SAR*) or Envisat (ASA*) data
    if [[ "$FILENAME" =~ ^SAR ]]; then
        BASE_URL="$BASE_URL_ERS"
    else
        BASE_URL="$BASE_URL_ENVISAT"
    fi
    
    # Check if file is empty
    if [[ ! -s "$FILE" ]]; then
        echo "${BASE_URL}/${FILENAME}" >> "$OUTPUT_FILE"
        INVALID_FILES+=("$FILENAME")
        INVALID_COUNT=$((INVALID_COUNT + 1))
        continue
    fi
    
    # Get first line of file
    FIRST_LINE=$(head -n 1 "$FILE" 2>/dev/null || echo "")
    
    # Check if file starts with HTML DOCTYPE
    if [[ "$FIRST_LINE" =~ ^[[:space:]]*\<\!DOCTYPE[[:space:]]+html ]]; then
        echo "${BASE_URL}/${FILENAME}" >> "$OUTPUT_FILE"
        INVALID_FILES+=("$FILENAME")
        INVALID_COUNT=$((INVALID_COUNT + 1))
    else
        VALID_COUNT=$((VALID_COUNT + 1))
    fi
done

############################################################
# Print summary
############################################################
echo ""
echo "=========================================="
echo "Summary:"
echo "=========================================="
echo "Total files checked: ${#FILES[@]}"
echo "Valid files:         $VALID_COUNT"
echo "Invalid files:       $INVALID_COUNT"
echo ""

if [[ $INVALID_COUNT -gt 0 ]]; then
    echo "Invalid files:"
    echo "${INVALID_FILES[*]}"
    echo ""
    echo "Invalid file URLs written to: $OUTPUT_FILE"
    exit 1
else
    echo "All files are valid!"
    # Remove output file if no invalid files
    if [[ -f "$OUTPUT_FILE" ]]; then
        rm "$OUTPUT_FILE"
    fi
    exit 0
fi

