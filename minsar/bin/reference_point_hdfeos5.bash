#!/usr/bin/env bash
# Thin wrapper: change reference point in an HDFEOS5 file via reference_point_hdfeos5.py
# (in-memory date-by-date; no extract/save_hdfeos5 round-trip).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    cat << EOF
Usage:
    $SCRIPT_NAME <input_file.he5> --ref-lalo <lat> <lon> [options]

Examples:
    $SCRIPT_NAME S1_vert_106_128_20180302_20180525.he5 --ref-lalo -0.81 -91.190
    $SCRIPT_NAME S1_vert_106_128_20180302_20180525.he5 --ref-lalo -0.81 -91.190 --output output.he5
    $SCRIPT_NAME S1_....he5 --ref-lalo -0.81,-91.190 --lookup geometryRadar.h5

Options:
    --ref-lalo LAT,LON or LAT LON   New reference point (required)
    --output FILE                   Output HDFEOS5 path (default: update input in place)
    --lookup FILE                   geometryRadar.h5 for RADAR files (optional)
    --force                         Re-reference even if REF_Y/REF_X already match
    --help, -h                      Show this help message
EOF
    exit 0
fi

WORK_DIR="$PWD"
LOG_FILE="$WORK_DIR/log"
echo "#############################################################################################" | tee -a "$LOG_FILE"
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" | tee -a "$LOG_FILE"

positional=()
ref_lalo=()
output_file=""
lookup_file=""
force_flag=0

while [[ $# -gt 0 ]]; do
    case "$1" in
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
        --output)
            output_file="$2"
            shift 2
            ;;
        --lookup)
            lookup_file="$2"
            shift 2
            ;;
        --force)
            force_flag=1
            shift
            ;;
        --keep-extracted)
            # Deprecated (no extract step); accepted for backward compatibility
            shift
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1" >&2
            echo "Use $SCRIPT_NAME --help for available options" >&2
            exit 1
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

if [[ ${#positional[@]} -lt 1 ]]; then
    echo "Error: Input HDFEOS5 file is required" >&2
    exit 1
fi
if [[ ${#ref_lalo[@]} -eq 0 ]]; then
    echo "Error: --ref-lalo is required" >&2
    exit 1
fi

INPUT_FILE="${positional[0]}"
if [[ ! "$INPUT_FILE" =~ ^/ ]]; then
    INPUT_FILE="$PWD/$INPUT_FILE"
fi
if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: Input file not found: $INPUT_FILE" >&2
    exit 1
fi

py_args=("$INPUT_FILE" --ref-lalo "${ref_lalo[@]}")
[[ -n "$output_file" ]] && py_args+=(--output "$output_file")
[[ -n "$lookup_file" ]] && py_args+=(--lookup "$lookup_file")
[[ $force_flag -eq 1 ]] && py_args+=(--force)

echo "Running: reference_point_hdfeos5.py ${py_args[*]}"
reference_point_hdfeos5.py "${py_args[@]}"
