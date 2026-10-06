#!/usr/bin/env bash
# Batch VLM CSV and geo velocity PNGs for airport comment figures (output in ./pic).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
DISPLAY_VLM="${SCRIPT_DIR}/display_VLM.py"
PNGS_TO_PPTX="${SCRIPT_DIR}/pngs_to_pptx.py"
PIC_DIR="pic"
PPT_NAME="airport_comment_plots.pptx"

SUB_LAT0="25.78"
SUB_LAT1="25.81"
SUB_LON0="-80.31"
SUB_LON1="-80.265"
REF_LAT="25.808"
REF_LON="-80.28961"
VLIM0="-0.5"
VLIM1="0.5"
STYLE="scatter"
SCATTER_SIZE="10"
BASEMAP="esri_satellite"
USE_BASEMAP=1
# Default --fontsize for title, tick labels, colorbar (view.py int; display_VLM matches)
VIEW_FONT_SIZE="6"
DRY_RUN=0
# Optional layer basename from -m / --mask (e.g. geo_temporalCoherence → geo_* or radar per dataset)
USER_MASK_SPEC=""
# view.py --mask-vmin when masking float layers (e.g. temporalCoherence)
MASK_VMIN="0.7"
PLOT_NOVERBOSE=0
CBAR_DEFAULT_ARGS=(--cbar-ext neither)
RECORD_PLOT_CMD=0
PLOT_CMD_LINES=()
PLOT_FOOTER_LINES=()
PPT_FOOTER_OVERRIDE=""
PPT_MANIFEST="${PIC_DIR}/ppt_manifest.tsv"

helptext="
usage: ${SCRIPT_NAME} [OPTIONS] DATASET [DATASET ...]

Plot PNGs in ./pic (VLM CSV via display_VLM.py; *.h5 velocity via view.py).
If ./pic exists, its contents are removed before plotting (not with --dry-run).
Without -m/--mask, plots are unmasked. With --mask, mask applies to every dataset (VLM CSV and *.h5; see --mask).
Always saves with --no-display / --nodisplay. Writes ${PPT_NAME} in ./pic (one slide per PNG). Logs to pic/log.
Default colorbar: rectangle (--cbar-ext neither); override with --cbar-ext min|max|both on the command line.

options:
  -h, --help              show this help
  --sub-lat LAT_MIN LAT_MAX   [default: ${SUB_LAT0} ${SUB_LAT1}]
  --sub-lon LON_MIN LON_MAX   [default: ${SUB_LON0} ${SUB_LON1}]
  --ref-lalo LAT LON          VLM CSV only [default: ${REF_LAT} ${REF_LON}]
  --vlim VMIN VMAX            [default: ${VLIM0} ${VLIM1}]
  --style STYLE               [default: ${STYLE}]
  --scatter-size N            marker size for CSV and geo velocity [default: ${SCATTER_SIZE}]
  -m, --mask NAME             mask for all datasets (stem or .h5; geo_* or radar name OK)
                              path used as-is if it exists; else geo_STEM.h5 or STEM.h5 per dataset dir
  --mask-vmin VALUE           view.py mask threshold when --mask is set [default: ${MASK_VMIN}]
  --add-basemap [PROVIDER]    web tiles for geo *.h5 and radar scatter (lat/lon); [default: ${BASEMAP}]
  --no-basemap                disable web basemap
  --dry-run                   print commands without running
  --noverbose, --no-verbose   forward to view.py and display_VLM.py (less plotter output; default: verbose)
  Figure / axis (forwarded to view.py and display_VLM.py):
  --fontsize N              title, ticks, colorbar [default: ${VIEW_FONT_SIZE}]
  --noaxis                  hide x/y axes (frame, tick labels, and Longitude/Latitude text)
  --notick                  hide tick numbers (and axis title text on radar scatter plots)
  --nowhitespace            hide axis, title, and colorbar
  --noreference             do not plot MintPy reference pixel
  --ref-size N              reference marker size [view.py default: 6; use ~0.5 with tiny --scatter-size]
  --nocbar --notitle --fontcolor COLOR --ylabel-rot DEG --figsize W H --dpi N
  -c, --colormap NAME --flip-lr --flip-ud --lalo-label [--lalo-step DEG ...]
  --                        extra args to view.py / display_VLM.py (after the options above)

Examples:
  ${SCRIPT_NAME} ../ShirzaeiComment/MIA_VLM.csv miaplpy_201509_202101/network_delaunay_4/geo_velocity.h5 miaplpy_201509_202609_075/network_delaunay_4/geo_velocity.h5 mintpy_2015-2021/geo_velocity.h5 mintpy_2015-2026/geo_velocity.h5 --scatter-size 0.5 --notick --noaxis
  ${SCRIPT_NAME} ../ShirzaeiComment/MIA_VLM.csv miaplpy_201509_202609/network_delaunay_4/velocity.h5 --notick --mask geo_temporalCoherence --mask-vmin 0.8 --scatter-size 1 --no-verbose
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

log_plot_command() {
    local cmd="$1"
    printf '%s + %s\n' "$(date +'%Y%m%d-%H:%M')" "$cmd" >> "$PIC_LOG"
}

log_script_invocation() {
    local line="" part
    for part in "${SCRIPT_INVOCATION[@]}"; do
        line+="$(printf '%q' "$part") "
    done
    line=${line%% }
    printf '%s\n' '#########################################################################################' >> "$PIC_LOG"
    printf '%s + %s\n' "$(date +'%Y%m%d-%H:%M')" "$line" >> "$PIC_LOG"
}

clean_plot_title() {
    local dataset="$1"
    local base lower abs part run="" parent fname
    base=$(basename "$dataset")
    lower=$(printf '%s' "${base##*.}" | tr '[:upper:]' '[:lower:]')
    if [[ "$lower" == "csv" ]]; then
        printf '%s' "$base"
        return 0
    fi
    fname="$base"
    abs=$(cd "$(dirname "$dataset")" && pwd)/$(basename "$dataset")
    IFS=/ read -ra parts <<< "$abs"
    for part in "${parts[@]}"; do
        if [[ "$part" == miaplpy_* || "$part" == mintpy_* ]]; then
            run="$part"
            break
        fi
    done
    if [[ -n "$run" ]]; then
        printf '%s %s' "$run" "$fname"
        return 0
    fi
    parent=$(basename "$(dirname "$dataset")")
    if [[ "$parent" == network_* ]]; then
        parent=$(basename "$(dirname "$(dirname "$dataset")")")
    fi
    printf '%s %s' "$parent" "$fname"
}

normalize_mask_stem() {
    local s="$1"
    s="$(basename "$s")"
    s="${s%.h5}"
    if [[ "$s" == geo_* ]]; then
        s="${s#geo_}"
    fi
    printf '%s' "$s"
}

# Candidate mask basenames for one velocity dataset (geocoded vs radar).
mask_names_for_dataset() {
    local dataset="$1"
    local stem spec_bn lower_ext
    local -a names=()
    stem="$(normalize_mask_stem "$USER_MASK_SPEC")"
    spec_bn="$(basename "$USER_MASK_SPEC")"
    [[ "$spec_bn" == *.[hH]5 ]] || spec_bn="${spec_bn}.h5"
    lower_ext=$(printf '%s' "${dataset##*.}" | tr '[:upper:]' '[:lower:]')
    if [[ "$lower_ext" == "csv" ]] || dataset_is_geocoded "$dataset"; then
        names+=( "geo_${stem}.h5" )
        if [[ "$spec_bn" == geo_* ]]; then
            names+=( "$spec_bn" )
        fi
    else
        names+=( "${stem}.h5" "$spec_bn" )
    fi
    printf '%s\n' "${names[@]}" | awk '!seen[$0]++'
}

dataset_is_geocoded() {
    local dataset="$1"
    "$PLOT_PYTHON" -c "
from mintpy.utils import readfile
import sys
atr = readfile.read_attribute(sys.argv[1])
raise SystemExit(0 if 'Y_FIRST' in atr else 1)
" "$dataset"
}

miaplpy_dir_from_path() {
    local f="$1" abs part
    abs=$(cd "$(dirname "$f")" 2>/dev/null && pwd)/$(basename "$f") || abs="$f"
    IFS=/ read -ra parts <<< "$abs"
    for part in "${parts[@]}"; do
        if [[ "$part" == miaplpy_* ]]; then
            printf '%s' "$part"
            return 0
        fi
    done
    return 1
}

# CSV mask: same network_* folder under miaplpy_* as a non-CSV dataset on the command line.
find_geo_mask_for_csv() {
    local base="$1"
    local ds net try tag mpart line
    local -a candidates=() exact=() related=() uniq=()
    for ds in "${DATASETS[@]}"; do
        [[ "$(printf '%s' "${ds##*.}" | tr '[:upper:]' '[:lower:]')" == "csv" ]] && continue
        net=$(basename "$(dirname "$ds")")
        [[ "$net" == network_* ]] || continue
        for try in "$PWD"/miaplpy_*/"${net}/${base}"; do
            [[ -f "$try" ]] || continue
            candidates+=("$try")
        done
    done
    if [[ ${#candidates[@]} -eq 0 ]]; then
        printf ''
        return 0
    fi
    while IFS= read -r line; do uniq+=("$line"); done < <(printf '%s\n' "${candidates[@]}" | sort -u)
    if [[ ${#uniq[@]} -eq 1 ]]; then
        printf '%s' "${uniq[0]}"
        return 0
    fi
    for ds in "${DATASETS[@]}"; do
        [[ "$(printf '%s' "${ds##*.}" | tr '[:upper:]' '[:lower:]')" == "csv" ]] && continue
        tag="$(miaplpy_dir_from_path "$ds")" || continue
        exact=()
        related=()
        for try in "${uniq[@]}"; do
            mpart=$(miaplpy_dir_from_path "$try") || continue
            if [[ "$mpart" == "$tag" ]]; then
                exact+=("$try")
            elif [[ "$mpart" == "${tag}_"* ]]; then
                related+=("$try")
            fi
        done
        if [[ ${#exact[@]} -eq 1 ]]; then
            printf '%s' "${exact[0]}"
            return 0
        fi
        if [[ ${#exact[@]} -gt 1 ]]; then
            echo "Error: multiple ${base} under ${tag}; narrow datasets on the command line" >&2
            exit 1
        fi
        if [[ ${#related[@]} -ge 1 ]]; then
            IFS=$'\n' related=($(printf '%s\n' "${related[@]}" | sort -u))
            printf '%s' "${related[0]}"
            return 0
        fi
    done
    echo "Error: multiple ${base} under miaplpy_*/network_*/; add a geocoded dataset from the intended run" >&2
    exit 1
}

# Resolve -m / --mask to a co-located .h5 (geo prefix vs radar from dataset coordinates).
layer_mask_for_dataset() {
    local dataset="$1"
    local dir mask try_dir lower_ext base tried="" name
    dir=$(dirname "$dataset")
    [[ "$dir" != "." ]] || dir="$PWD"
    lower_ext=$(printf '%s' "${dataset##*.}" | tr '[:upper:]' '[:lower:]')

    if [[ -f "$USER_MASK_SPEC" ]]; then
        printf '%s' "$(cd "$(dirname "$USER_MASK_SPEC")" && pwd)/$(basename "$USER_MASK_SPEC")"
        return 0
    fi

    while IFS= read -r base; do
        [[ -n "$base" ]] || continue
        tried+="${dir}/${base} "
        mask="${dir}/${base}"
        if [[ -f "$mask" ]]; then
            printf '%s' "$mask"
            return 0
        fi
        if [[ ${#MASK_FALLBACK_DIRS[@]} -gt 0 ]]; then
            for try_dir in "${MASK_FALLBACK_DIRS[@]}"; do
                mask="${try_dir}/${base}"
                tried+="${mask} "
                if [[ -f "$mask" ]]; then
                    printf '%s' "$mask"
                    return 0
                fi
            done
        fi
        if [[ "$lower_ext" == "csv" ]]; then
            mask="$(find_geo_mask_for_csv "$base")"
            if [[ -n "$mask" && -f "$mask" ]]; then
                printf '%s' "$mask"
                return 0
            fi
            tried+="${mask} "
        fi
    done < <(mask_names_for_dataset "$dataset")

    echo "Error: mask not found for dataset: ${dataset}" >&2
    echo "  (--mask ${USER_MASK_SPEC}; tried: ${tried})" >&2
    exit 1
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
    local -a mask_args=() geo_grid_args=() cmd=() footer="" c
    local j
    if [[ "$use_mask" -eq 1 ]]; then
        mask_args=(--mask "$mask_file" --mask-vmin "$MASK_VMIN")
    fi
    if [[ -n "$GEO_GRID_FILE" ]]; then
        geo_grid_args=(--geo-grid "$GEO_GRID_FILE")
    fi
    cmd=(
        "$PLOT_PYTHON" "$DISPLAY_VLM" "$dataset"
        --title "$plot_title"
        "${geo_grid_args[@]}"
        --sub-lat "$SUB_LAT0" "$SUB_LAT1"
        --sub-lon "$SUB_LON0" "$SUB_LON1"
        --ref-lalo "$REF_LAT" "$REF_LON"
        --vlim "$VLIM0" "$VLIM1"
        --style "$STYLE"
        --scatter-size "$SCATTER_SIZE"
        "${mask_args[@]}"
        --no-display
        -o "$out_png"
        "${BASEMAP_ARGS[@]}"
        "${PASS_ARGS[@]}"
    )
    footer="display_VLM.py"
    for ((j = 2; j < ${#cmd[@]}; j++)); do
        footer+=" $(printf '%q' "${cmd[j]}")"
    done
    PPT_FOOTER_OVERRIDE="$footer"
    RECORD_PLOT_CMD=1
    run_or_dry "${cmd[@]}"
    PPT_FOOTER_OVERRIDE=""
    RECORD_PLOT_CMD=0
}

plot_velocity_h5() {
    local dataset="$1" out_png="$2" plot_title="$3" use_mask="$4" mask_file="$5"
    local -a mask_args=() geo_args=()
    if [[ "$use_mask" -eq 1 ]]; then
        mask_args=(--mask "$mask_file" --mask-vmin "$MASK_VMIN")
    fi
    geo_args=(--sub-lat "$SUB_LAT0" "$SUB_LAT1" --sub-lon "$SUB_LON0" "$SUB_LON1")
    RECORD_PLOT_CMD=1
    run_or_dry \
        view.py "$dataset" velocity \
        --title "$plot_title" \
        --style "$STYLE" \
        --scatter-size "$SCATTER_SIZE" \
        "${geo_args[@]}" \
        "${mask_args[@]}" \
        --vlim "$VLIM0" "$VLIM1" \
        --nodisplay \
        -o "$out_png" \
        "${BASEMAP_ARGS[@]}" \
        "${PASS_ARGS[@]}"
    RECORD_PLOT_CMD=0
}

run_or_dry() {
    local -a cmd=("$@")
    local line="" c
    for c in "${cmd[@]}"; do
        line+="$(printf '%q' "$c") "
    done
    line=${line%% }
    log_plot_command "$line"
    if [[ "$RECORD_PLOT_CMD" -eq 1 ]]; then
        PLOT_CMD_LINES+=("$line")
        if [[ -n "${PPT_FOOTER_OVERRIDE:-}" ]]; then
            PLOT_FOOTER_LINES+=("$PPT_FOOTER_OVERRIDE")
        else
            PLOT_FOOTER_LINES+=("$line")
        fi
    fi
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "${cmd[@]}"
    fi
    if [[ "$PLOT_NOVERBOSE" -eq 1 ]]; then
        echo ""
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
        -m|--mask)
            [[ $# -ge 2 ]] || { echo "Error: --mask requires a mask stem or .h5 name" >&2; exit 1; }
            USER_MASK_SPEC="$2"
            shift 2
            ;;
        --mask-vmin)
            [[ $# -ge 2 ]] || { echo "Error: --mask-vmin requires a numeric value" >&2; exit 1; }
            [[ "$2" =~ ^[+-]?([0-9]*\.?[0-9]+|[0-9]+\.?)$ ]] || { echo "Error: --mask-vmin must be numeric (got: $2)" >&2; exit 1; }
            MASK_VMIN="$2"
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
        --no-verbose|--noverbose)
            PLOT_NOVERBOSE=1
            VIEW_FIG_ARGS+=(--noverbose)
            shift
            ;;
        --nowhitespace|--noaxis|--notick|--nocbar|--nocolorbar|--notitle|--title-in|--title4sen|--title4sentinel1|--lalo-label|--flip-lr|--flip-ud|--noflip|--noreference)
            VIEW_FIG_ARGS+=("$1")
            shift
            ;;
        --ref-size|--ref-marker)
            [[ $# -ge 2 ]] || { echo "Error: $1 requires a value" >&2; exit 1; }
            VIEW_FIG_ARGS+=("$1" "$2")
            shift 2
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

FIG_FONT_ARGS=()
_has_fontsize=0
for _a in "${VIEW_FIG_ARGS[@]}" "${EXTRA[@]}"; do
    [[ "$_a" == --fontsize ]] && _has_fontsize=1
done
if [[ "$_has_fontsize" -eq 0 ]]; then
    FIG_FONT_ARGS=(--fontsize "$VIEW_FONT_SIZE")
fi
PASS_ARGS=("${FIG_FONT_ARGS[@]}" "${CBAR_DEFAULT_ARGS[@]}" "${VIEW_FIG_ARGS[@]}" "${EXTRA[@]}")

if [[ ${#DATASETS[@]} -eq 0 ]]; then
    echo "Error: at least one DATASET path is required" >&2
    exit 1
fi

if [[ ! -f "$DISPLAY_VLM" ]]; then
    echo "Error: display_VLM.py not found: ${DISPLAY_VLM}" >&2
    exit 1
fi

PLOT_PYTHON="$(resolve_plot_python)"

if ! command -v view.py >/dev/null 2>&1; then
    echo "Error: view.py not found in PATH (source MinSAR/MintPy environment, then retry)." >&2
    exit 1
fi

if [[ -d "$PIC_DIR" && "$DRY_RUN" -eq 0 ]]; then
    find "$PIC_DIR" -mindepth 1 -delete
fi
mkdir -p "$PIC_DIR"
log_script_invocation

MASK_FALLBACK_DIRS=()
if [[ -n "$USER_MASK_SPEC" ]]; then
    _seen_dirs=""
    for _ds in "${DATASETS[@]}"; do
        _ext=$(printf '%s' "${_ds##*.}" | tr '[:upper:]' '[:lower:]')
        [[ "$_ext" == "csv" ]] && continue
        _dd=$(dirname "$_ds")
        [[ "$_dd" != "." ]] || _dd="$PWD"
        case "$_seen_dirs" in
            *"|${_dd}|"*) continue ;;
        esac
        MASK_FALLBACK_DIRS+=("$_dd")
        _seen_dirs="${_seen_dirs}|${_dd}|"
    done
fi

BASEMAP_ARGS=()
if [[ "$USE_BASEMAP" -eq 1 ]]; then
    BASEMAP_ARGS=(--add-basemap)
    if [[ "$BASEMAP" != "esri_satellite" ]]; then
        BASEMAP_ARGS+=( "$BASEMAP" )
    fi
fi

GEO_GRID_FILE=""
for _ds in "${DATASETS[@]}"; do
    _ext=$(printf '%s' "${_ds##*.}" | tr '[:upper:]' '[:lower:]')
    [[ "$_ext" == "csv" ]] && continue
    if dataset_is_geocoded "$_ds"; then
        GEO_GRID_FILE="$_ds"
        break
    fi
done

OUT_PNGS=()
for dataset in "${DATASETS[@]}"; do
    if [[ ! -f "$dataset" ]]; then
        echo "Error: dataset not found: ${dataset}" >&2
        exit 1
    fi
    plot_title="$(clean_plot_title "$dataset")"
    ext="${dataset##*.}"
    lower=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')
    out_png="${PIC_DIR}/$(png_stem "$dataset").png"
    OUT_PNGS+=("$out_png")
    if [[ -n "$USER_MASK_SPEC" ]]; then
        mask_file="$(layer_mask_for_dataset "$dataset")"
    fi
    if [[ "$lower" == "csv" ]]; then
        if [[ -n "$USER_MASK_SPEC" ]]; then
            plot_vlm_csv "$dataset" "$out_png" "$plot_title" 1 "$mask_file"
        else
            plot_vlm_csv "$dataset" "$out_png" "$plot_title" 0 ""
        fi
    elif [[ -n "$USER_MASK_SPEC" ]]; then
        plot_velocity_h5 "$dataset" "$out_png" "$plot_title" 1 "$mask_file"
    else
        plot_velocity_h5 "$dataset" "$out_png" "$plot_title" 0 ""
    fi
done

if [[ "$DRY_RUN" -eq 0 && ${#OUT_PNGS[@]} -gt 0 ]]; then
    ppt_out="${PIC_DIR}/${PPT_NAME}"
    manifest_path="${PPT_MANIFEST}"
    : > "$manifest_path"
    for i in "${!OUT_PNGS[@]}"; do
        if [[ -n "${PLOT_FOOTER_LINES[$i]:-}" ]]; then
            printf '%s\t%s\n' "${OUT_PNGS[$i]}" "${PLOT_FOOTER_LINES[$i]}"
        elif [[ -n "${PLOT_CMD_LINES[$i]:-}" ]]; then
            printf '%s\t%s\n' "${OUT_PNGS[$i]}" "${PLOT_CMD_LINES[$i]}"
        else
            printf '%s\t\n' "${OUT_PNGS[$i]}"
        fi
    done > "$manifest_path"
    invocation_line=""
    for part in "${SCRIPT_INVOCATION[@]}"; do
        invocation_line+="$(printf '%q' "$part") "
    done
    invocation_line=${invocation_line%% }
    ppt_cmd=(
        "$PLOT_PYTHON" "$PNGS_TO_PPTX" -o "$ppt_out"
        --manifest "$manifest_path"
        --footer-font-size 8
        --run-dir "$(pwd)"
        --invocation "$invocation_line"
    )
    for png in "${OUT_PNGS[@]}"; do
        ppt_cmd+=("$png")
    done
    RECORD_PLOT_CMD=0
    run_or_dry "${ppt_cmd[@]}"
fi
