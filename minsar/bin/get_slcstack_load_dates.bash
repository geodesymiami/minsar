#!/usr/bin/env bash
# First/last merged/SLC dates MiaplPy would load into slcStack.h5.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

source "${SCRIPT_DIR}/../lib/minsarApp_specifics.sh"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Print the first and last YYYYMMDD dates that MiaplPy would load into slcStack.h5.

Uses merged/SLC (YYYYMMDD dirs only) clipped by miaplpy.load.startDate / endDate
when those are set and not auto (inclusive). auto means no bound on that side.

Examples:
    $SCRIPT_NAME \$TE/GalapagosSenDT128.template
    $SCRIPT_NAME \$TE/GalapagosSenDT128.template --all
    $SCRIPT_NAME \$TE/GalapagosSenDT128.template --date-str
    $SCRIPT_NAME \$TE/GalapagosSenDT128.template --slc-dir /scratch/proj/merged/SLC

Arguments:
    TEMPLATE           MinSAR template (miaplpy.load.startDate / endDate)

Options:
    --slc-dir DIR      SLC directory (default: merged/SLC)
    --all              Print every date that would be loaded, one per line
    --date-str         Print YYYYMM_YYYYMM (same string used in miaplpy_/mintpy_ dir names)
"
    printf "%b" "$helptext"
    exit 0
fi

slc_dir="merged/SLC"
all_flag=0
date_str_flag=0
positional=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --slc-dir)
            [[ $# -lt 2 ]] && { echo "Error: --slc-dir requires a value" >&2; exit 1; }
            slc_dir="$2"
            shift 2
            ;;
        --all)
            all_flag=1
            shift
            ;;
        --date-str)
            date_str_flag=1
            shift
            ;;
        -?*)
            echo "Error: Unknown option: $1" >&2
            exit 1
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

if [[ ${#positional[@]} -lt 1 ]]; then
    echo "Error: TEMPLATE is required" >&2
    echo "Usage: $SCRIPT_NAME TEMPLATE [--slc-dir DIR] [--all|--date-str]" >&2
    exit 1
fi

template_file="${positional[0]}"
if [[ ! -f "$template_file" ]]; then
    echo "Error: template not found: $template_file" >&2
    exit 1
fi

create_template_array "$template_file"

dates=()
mapfile -t dates < <(list_slcstack_load_dates "$slc_dir")
if [[ ${#dates[@]} -eq 0 ]]; then
    echo "Error: no merged/SLC dates in miaplpy.load.startDate/endDate window ($slc_dir)" >&2
    exit 1
fi

if [[ "$all_flag" == "1" ]]; then
    printf '%s\n' "${dates[@]}"
elif [[ "$date_str_flag" == "1" ]]; then
    echo "${dates[0]:0:6}_${dates[-1]:0:6}"
else
    echo "${dates[0]} ${dates[-1]}"
fi
