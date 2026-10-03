#!/usr/bin/env bash
# Batch VLM CSV and geo velocity PNGs for airport comment figures (output in ./pic).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
DISPLAY_VLM="${SCRIPT_DIR}/display_VLM.py"
PIC_DIR="pic"

SUB_LAT0="25.78"
SUB_LAT1="25.81"
SUB_LON0="-80.31"
SUB_LON1="-80.265"
REF_LAT="25.808"
REF_LON="-80.28961"
VLIM0="-0.5"
VLIM1="0.5"
MASK="geo_polygon_mask.h5"
STYLE="scatter"
SCATTER_SIZE="10"
BASEMAP="esri_satellite"
USE_BASEMAP=1
# view.py --fontsize must be an integer (match display_VLM body font)
VIEW_FONT_SIZE="10"
DRY_RUN=0

helptext="
usage: ${SCRIPT_NAME} [OPTIONS] DATASET [DATASET ...]

Plot one PNG per dataset in ./pic (VLM CSV via display_VLM.py; geo *.h5 via view.py velocity).
Always saves with --no-display / --nodisplay. Appends each command to ./log.

options:
  -h, --help              show this help
  --sub-lat LAT_MIN LAT_MAX   [default: ${SUB_LAT0} ${SUB_LAT1}]
  --sub-lon LON_MIN LON_MAX   [default: ${SUB_LON0} ${SUB_LON1}]
  --ref-lalo LAT LON          VLM CSV only [default: ${REF_LAT} ${REF_LON}]
  --vlim VMIN VMAX            [default: ${VLIM0} ${VLIM1}]
  --mask FILE                 [default: ${MASK}]
  --style STYLE               [default: ${STYLE}]
  --scatter-size N            marker size for CSV and geo velocity [default: ${SCATTER_SIZE}]
  --add-basemap [PROVIDER]    [default: ${BASEMAP}]
  --no-basemap                disable web basemap
  --dry-run                   print commands without running
  --                        pass remaining args to display_VLM.py / view.py

Examples:
  ${SCRIPT_NAME} MIA_VLM.csv miaplpy_201509_202101/network_delaunay_4/geo_velocity.h5 miaplpy_201509_202609_075/network_delaunay_4/geo_velocity.h5
  ${SCRIPT_NAME} --vlim -1 1 aoi.csv geo_velocity.h5
  ${SCRIPT_NAME} MIA_VLM.csv geo_velocity.h5 -- --nowhitespace
"

usage() {
    echo -e "${helptext}"
    exit 0
}

log_command() {
    local cmd="$1"
    if python3 - "$cmd" 2>/dev/null <<'PY'
import os, sys
from minsar.objects import message_rsmas
message_rsmas.log(os.getcwd(), sys.argv[1])
PY
    then
        return 0
    fi
    printf '%s + %s\n' "$(date +'%Y%m%d-%H:%M')" "$cmd" | tee -a log
}

clean_plot_title() {
    local t="$1"
    t="${t//network_delaunay_4\/geo_velocity.h5/}"
    t="${t//network_delaunay4\/geo_velocity.h5/}"
    t="${t%/}"
    printf '%s' "$t"
}

png_stem() {
    local f="$1"
    local base ext lower parent abs part
    base=$(basename "$f")
    ext="${base##*.}"
    base="${base%.*}"
    lower=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')
    if [[ "$lower" == "csv" ]]; then
        printf '%s_vlm' "$base"
        return 0
    fi
    abs=$(cd "$(dirname "$f")" && pwd)/$(basename "$f")
    IFS=/ read -ra parts <<< "$abs"
    for part in "${parts[@]}"; do
        if [[ "$part" == miaplpy_* ]]; then
            printf '%s_%s' "$part" "$base"
            return 0
        fi
    done
    parent=$(basename "$(dirname "$f")")
    printf '%s_%s' "$parent" "$base"
}

run_or_dry() {
    local -a cmd=("$@")
    local line=""
    local c
    for c in "${cmd[@]}"; do
        line+="$(printf '%q' "$c") "
    done
    line=${line%% }
    log_command "$line"
    echo "$line"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "${cmd[@]}"
    fi
}

if [[ $# -eq 0 ]] || [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    usage
fi

EXTRA=()
ARGS=("$@")
for ((i = 0; i < ${#ARGS[@]}; i++)); do
    if [[ "${ARGS[i]}" == "--" ]]; then
        EXTRA=("${ARGS[@]:i+1}")
        ARGS=("${ARGS[@]:0:i}")
        break
    fi
done

DATASETS=()
set -- "${ARGS[@]}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sub-lat)
            [[ $# -ge 3 ]] || { echo "Error: --sub-lat requires two values" >&2; exit 1; }
            SUB_LAT0="$2"
            SUB_LAT1="$3"
            shift 3
            ;;
        --sub-lon)
            [[ $# -ge 3 ]] || { echo "Error: --sub-lon requires two values" >&2; exit 1; }
            SUB_LON0="$2"
            SUB_LON1="$3"
            shift 3
            ;;
        --ref-lalo)
            [[ $# -ge 3 ]] || { echo "Error: --ref-lalo requires two values" >&2; exit 1; }
            REF_LAT="$2"
            REF_LON="$3"
            shift 3
            ;;
        --vlim)
            [[ $# -ge 3 ]] || { echo "Error: --vlim requires two values" >&2; exit 1; }
            VLIM0="$2"
            VLIM1="$3"
            shift 3
            ;;
        --mask)
            [[ $# -ge 2 ]] || { echo "Error: --mask requires a file" >&2; exit 1; }
            MASK="$2"
            shift 2
            ;;
        --style)
            [[ $# -ge 2 ]] || { echo "Error: --style requires a value" >&2; exit 1; }
            STYLE="$2"
            shift 2
            ;;
        --scatter-size)
            [[ $# -ge 2 ]] || { echo "Error: --scatter-size requires a value" >&2; exit 1; }
            SCATTER_SIZE="$2"
            shift 2
            ;;
        --add-basemap)
            USE_BASEMAP=1
            shift
            if [[ $# -gt 0 && "$1" != -* ]]; then
                BASEMAP="$1"
                shift
            else
                BASEMAP="esri_satellite"
            fi
            ;;
        --no-basemap)
            USE_BASEMAP=0
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1" >&2
            echo "Use ${SCRIPT_NAME} --help for available options" >&2
            exit 1
            ;;
        *)
            DATASETS+=("$1")
            shift
            ;;
    esac
done

if [[ ${#DATASETS[@]} -eq 0 ]]; then
    echo "Error: at least one DATASET path is required" >&2
    exit 1
fi

if [[ ! -f "$DISPLAY_VLM" ]]; then
    echo "Error: display_VLM.py not found: ${DISPLAY_VLM}" >&2
    exit 1
fi

mkdir -p "$PIC_DIR"

BASEMAP_ARGS=()
if [[ "$USE_BASEMAP" -eq 1 ]]; then
    BASEMAP_ARGS=(--add-basemap)
    if [[ "$BASEMAP" != "esri_satellite" ]]; then
        BASEMAP_ARGS+=( "$BASEMAP" )
    fi
fi

for dataset in "${DATASETS[@]}"; do
    if [[ ! -f "$dataset" ]]; then
        echo "Error: dataset not found: ${dataset}" >&2
        exit 1
    fi
    out_png="${PIC_DIR}/$(png_stem "$dataset").png"
    plot_title="$(clean_plot_title "$dataset")"
    ext="${dataset##*.}"
    lower=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')

    if [[ "$lower" == "csv" ]]; then
        run_or_dry \
            python3 "$DISPLAY_VLM" "$dataset" \
            --title "$plot_title" \
            --sub-lat "$SUB_LAT0" "$SUB_LAT1" \
            --sub-lon "$SUB_LON0" "$SUB_LON1" \
            --ref-lalo "$REF_LAT" "$REF_LON" \
            --vlim "$VLIM0" "$VLIM1" \
            --style "$STYLE" \
            --scatter-size "$SCATTER_SIZE" \
            --mask "$MASK" \
            --no-display \
            -o "$out_png" \
            "${BASEMAP_ARGS[@]}" \
            "${EXTRA[@]}"
    else
        run_or_dry \
            view.py "$dataset" velocity \
            --title "$plot_title" \
            --fontsize "$VIEW_FONT_SIZE" \
            --style "$STYLE" \
            --scatter-size "$SCATTER_SIZE" \
            --sub-lat "$SUB_LAT0" "$SUB_LAT1" \
            --sub-lon "$SUB_LON0" "$SUB_LON1" \
            --mask "$MASK" \
            --vlim "$VLIM0" "$VLIM1" \
            --nodisplay \
            -o "$out_png" \
            "${BASEMAP_ARGS[@]}" \
            "${EXTRA[@]}"
    fi
done
