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
POLYGON_MASK_NAME="geo_polygon_mask.h5"
# MintPy temporal-coherence mask (same order as view.py default for geo_velocity.h5)
TEMPCOH_MASK_NAMES=(geo_maskTempCoh.h5 geo_mask.h5 maskTempCoh.h5)
STYLE="scatter"
SCATTER_SIZE="10"
BASEMAP="esri_satellite"
USE_BASEMAP=1
# view.py --fontsize must be an integer (match display_VLM body font)
VIEW_FONT_SIZE="10"
DRY_RUN=0

helptext="
usage: ${SCRIPT_NAME} [OPTIONS] DATASET [DATASET ...]

Plot PNGs in ./pic (VLM CSV via display_VLM.py; geo *.h5 via view.py velocity).
CSV: polygon + unmasked PNGs. MiaplPy geo_velocity.h5: polygon (_masked) + temporal-coherence mask (_tempcoh).
Other geo *.h5: one polygon-masked PNG. Masks must live in the same directory as each DATASET.
Always saves with --no-display / --nodisplay. Logs this script and each plot command to pic/log.

options:
  -h, --help              show this help
  --sub-lat LAT_MIN LAT_MAX   [default: ${SUB_LAT0} ${SUB_LAT1}]
  --sub-lon LON_MIN LON_MAX   [default: ${SUB_LON0} ${SUB_LON1}]
  --ref-lalo LAT LON          VLM CSV only [default: ${REF_LAT} ${REF_LON}]
  --vlim VMIN VMAX            [default: ${VLIM0} ${VLIM1}]
  --style STYLE               [default: ${STYLE}]
  --scatter-size N            marker size for CSV and geo velocity [default: ${SCATTER_SIZE}]
  --add-basemap [PROVIDER]    [default: ${BASEMAP}]
  --no-basemap                disable web basemap
  --dry-run                   print commands without running
  Figure / axis (forwarded to view.py and display_VLM.py):
  --nowhitespace --noaxis --notick --nocbar --notitle --noverbose
  --fontsize N --fontcolor COLOR --ylabel-rot DEG --figsize W H --dpi N
  -c, --colormap NAME --flip-lr --flip-ud --lalo-label [--lalo-step DEG ...]
  --                        extra args to view.py / display_VLM.py (after the options above)

Examples:
  ${SCRIPT_NAME} ../ShirzaeiComment/MIA_VLM.csv miaplpy_201509_202101/network_delaunay_4/geo_velocity.h5 miaplpy_201509_202609_075/network_delaunay_4/geo_velocity.h5 mintpy_2015-2021/geo_velocity.h5 mintpy_2015-2026/geo_velocity.h5 --scatter-size 0.5 --notick --noaxis
"

usage() {
    echo -e "${helptext}"
    exit 0
}

resolve_plot_python() {
    local py
    for py in python python3; do
        if command -v "$py" >/dev/null 2>&1 && "$py" -c "import matplotlib" 2>/dev/null; then
            command -v "$py"
            return 0
        fi
    done
    echo "Error: Python with matplotlib is required (source MinSAR/MintPy environment, then retry)." >&2
    exit 1
}

log_command() {
    local cmd="$1"
    printf '%s + %s\n' "$(date +'%Y%m%d-%H:%M')" "$cmd" | tee -a "$PIC_LOG"
    if python3 - "$cmd" 2>/dev/null <<'PY'
import os, sys
from minsar.objects import message_rsmas
message_rsmas.log(os.getcwd(), sys.argv[1])
PY
    then
        return 0
    fi
}

log_script_invocation() {
    local line="" part
    for part in "${SCRIPT_INVOCATION[@]}"; do
        line+="$(printf '%q' "$part") "
    done
    line=${line%% }
    printf '%s + %s\n' "$(date +'%Y%m%d-%H:%M')" "$line" | tee -a "$PIC_LOG"
}

clean_plot_title() {
    local t="$1"
    t="${t//network_delaunay_4\/geo_velocity.h5/}"
    t="${t//network_delaunay4\/geo_velocity.h5/}"
    t="${t%/}"
    printf '%s' "$t"
}

polygon_mask_for_dataset() {
    local dataset="$1"
    local dir mask
    dir=$(dirname "$dataset")
    [[ "$dir" != "." ]] || dir="$PWD"
    mask="${dir}/${POLYGON_MASK_NAME}"
    if [[ ! -f "$mask" ]]; then
        echo "Error: ${POLYGON_MASK_NAME} not found in dataset directory: ${dir}" >&2
        echo "  dataset: ${dataset}" >&2
        exit 1
    fi
    printf '%s' "$mask"
}

temp_coh_mask_for_dataset() {
    local dataset="$1"
    local dir name mask
    dir=$(dirname "$dataset")
    [[ "$dir" != "." ]] || dir="$PWD"
    for name in "${TEMPCOH_MASK_NAMES[@]}"; do
        mask="${dir}/${name}"
        if [[ -f "$mask" ]]; then
            printf '%s' "$mask"
            return 0
        fi
    done
    echo "Error: temporal-coherence mask not found in dataset directory: ${dir}" >&2
    echo "  tried: ${TEMPCOH_MASK_NAMES[*]}" >&2
    echo "  dataset: ${dataset}" >&2
    exit 1
}

is_miaplpy_dataset() {
    local f="$1"
    local abs part
    abs=$(cd "$(dirname "$f")" && pwd)/$(basename "$f")
    IFS=/ read -ra parts <<< "$abs"
    for part in "${parts[@]}"; do
        if [[ "$part" == miaplpy_* ]]; then
            return 0
        fi
    done
    return 1
}

png_stem() {
    local f="$1"
    local suffix="${2:-}"
    local base ext lower parent abs part file_stem
    base=$(basename "$f")
    ext="${base##*.}"
    file_stem="${base%.*}"
    lower=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')
    if [[ "$lower" == "csv" ]]; then
        base="${file_stem}_vlm"
    else
        abs=$(cd "$(dirname "$f")" && pwd)/$(basename "$f")
        IFS=/ read -ra parts <<< "$abs"
        base=""
        for part in "${parts[@]}"; do
            if [[ "$part" == miaplpy_* ]]; then
                base="${part}_${file_stem}"
                break
            fi
        done
        if [[ -z "$base" ]]; then
            parent=$(basename "$(dirname "$f")")
            base="${parent}_${file_stem}"
        fi
    fi
    if [[ -n "$suffix" ]]; then
        base="${base}_${suffix}"
    fi
    printf '%s' "$base"
}

plot_vlm_csv() {
    local dataset="$1" out_png="$2" plot_title="$3" use_mask="$4" mask_file="$5"
    local -a mask_args=()
    if [[ "$use_mask" -eq 1 ]]; then
        mask_args=(--mask "$mask_file")
    else
        mask_args=(--mask no)
    fi
    run_or_dry \
        "$PLOT_PYTHON" "$DISPLAY_VLM" "$dataset" \
        --title "$plot_title" \
        --sub-lat "$SUB_LAT0" "$SUB_LAT1" \
        --sub-lon "$SUB_LON0" "$SUB_LON1" \
        --ref-lalo "$REF_LAT" "$REF_LON" \
        --vlim "$VLIM0" "$VLIM1" \
        --style "$STYLE" \
        --scatter-size "$SCATTER_SIZE" \
        "${mask_args[@]}" \
        --no-display \
        -o "$out_png" \
        "${BASEMAP_ARGS[@]}" \
        "${PASS_ARGS[@]}"
}

plot_geo_velocity() {
    local dataset="$1" out_png="$2" plot_title="$3" use_mask="$4" mask_file="$5"
    local -a mask_args=()
    if [[ "$use_mask" -eq 1 ]]; then
        mask_args=(--mask "$mask_file")
    fi
    run_or_dry \
        view.py "$dataset" velocity \
        --title "$plot_title" \
        --fontsize "$VIEW_FONT_SIZE" \
        --style "$STYLE" \
        --scatter-size "$SCATTER_SIZE" \
        --sub-lat "$SUB_LAT0" "$SUB_LAT1" \
        --sub-lon "$SUB_LON0" "$SUB_LON1" \
        "${mask_args[@]}" \
        --vlim "$VLIM0" "$VLIM1" \
        --nodisplay \
        -o "$out_png" \
        "${BASEMAP_ARGS[@]}" \
        "${PASS_ARGS[@]}"
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

SCRIPT_INVOCATION=("$0" "$@")
PIC_LOG="${PIC_DIR}/log"

EXTRA=()
VIEW_FIG_ARGS=()
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
        --nowhitespace|--noaxis|--notick|--nocbar|--nocolorbar|--notitle|--title-in|--title4sen|--title4sentinel1|--noverbose|--lalo-label|--flip-lr|--flip-ud|--noflip)
            VIEW_FIG_ARGS+=("$1")
            shift
            ;;
        --fontsize)
            [[ $# -ge 2 ]] || { echo "Error: --fontsize requires a value" >&2; exit 1; }
            VIEW_FONT_SIZE="$2"
            VIEW_FIG_ARGS+=(--fontsize "$2")
            shift 2
            ;;
        --fontcolor|--ylabel-rot|--dpi|--colormap|--cbar-ext|--cbar-label|--cbar-loc|--cbar-size|--cbar-nbins|--lalo-step|--lalo-max-num|--lalo-fs|--cm-lut|--cmap-lut|--alpha|--interpolation|--interp)
            [[ $# -ge 2 ]] || { echo "Error: $1 requires a value" >&2; exit 1; }
            VIEW_FIG_ARGS+=("$1" "$2")
            shift 2
            ;;
        -c)
            [[ $# -ge 2 ]] || { echo "Error: -c requires a colormap name" >&2; exit 1; }
            VIEW_FIG_ARGS+=(-c "$2")
            shift 2
            ;;
        --figsize|--lalo-off|--lalo-offset|--cm-vlist|--cmap-vlist)
            [[ $# -ge 3 ]] || { echo "Error: $1 requires two values" >&2; exit 1; }
            VIEW_FIG_ARGS+=("$1" "$2" "$3")
            shift 3
            ;;
        --lalo-loc)
            [[ $# -ge 5 ]] || { echo "Error: --lalo-loc requires four values" >&2; exit 1; }
            VIEW_FIG_ARGS+=("$1" "$2" "$3" "$4" "$5")
            shift 5
            ;;
        --cbar-ticks)
            VIEW_FIG_ARGS+=("--cbar-ticks")
            shift
            while [[ $# -gt 0 && "$1" != -* ]]; do
                VIEW_FIG_ARGS+=("$1")
                shift
            done
            ;;
        --title|--fig-title|--figtitle)
            [[ $# -ge 2 ]] || { echo "Error: $1 requires a value" >&2; exit 1; }
            VIEW_FIG_ARGS+=("$1" "$2")
            shift 2
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

PASS_ARGS=("${VIEW_FIG_ARGS[@]}" "${EXTRA[@]}")

if [[ ${#DATASETS[@]} -eq 0 ]]; then
    echo "Error: at least one DATASET path is required" >&2
    exit 1
fi

if [[ ! -f "$DISPLAY_VLM" ]]; then
    echo "Error: display_VLM.py not found: ${DISPLAY_VLM}" >&2
    exit 1
fi

if ! command -v view.py >/dev/null 2>&1; then
    echo "Error: view.py not found in PATH (source MinSAR/MintPy environment, then retry)." >&2
    exit 1
fi

PLOT_PYTHON="$(resolve_plot_python)"

mkdir -p "$PIC_DIR"
log_script_invocation

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
    plot_title="$(clean_plot_title "$dataset")"
    ext="${dataset##*.}"
    lower=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')
    dual_plots=0
    if [[ "$lower" == "csv" ]] || is_miaplpy_dataset "$dataset"; then
        dual_plots=1
    fi

    if [[ "$dual_plots" -eq 1 ]]; then
        mask_file="$(polygon_mask_for_dataset "$dataset")"
        if [[ "$lower" == "csv" ]]; then
            plot_vlm_csv "$dataset" "${PIC_DIR}/$(png_stem "$dataset" masked).png" "$plot_title" 1 "$mask_file"
            plot_vlm_csv "$dataset" "${PIC_DIR}/$(png_stem "$dataset" unmasked).png" "$plot_title" 0 "$mask_file"
        else
            tcoh_mask="$(temp_coh_mask_for_dataset "$dataset")"
            plot_geo_velocity "$dataset" "${PIC_DIR}/$(png_stem "$dataset" masked).png" "$plot_title" 1 "$mask_file"
            plot_geo_velocity "$dataset" "${PIC_DIR}/$(png_stem "$dataset" tempcoh).png" "$plot_title" 1 "$tcoh_mask"
        fi
    else
        mask_file="$(polygon_mask_for_dataset "$dataset")"
        plot_geo_velocity "$dataset" "${PIC_DIR}/$(png_stem "$dataset").png" "$plot_title" 1 "$mask_file"
    fi
done
