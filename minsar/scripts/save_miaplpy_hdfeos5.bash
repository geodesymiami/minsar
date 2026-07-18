#!/usr/bin/env bash
#
# save_miaplpy_hdfeos5.bash — Export MiaplPy network products to HDF-EOS5
#
# Runs filter/mask (optional), three save_hdfeos5.py jobs in parallel,
# geocode of aux products in parallel, then add_ref_lalo_to_file on HE5s.
#
# Usage:
#   save_miaplpy_hdfeos5.bash [--dir DIR] [-t FILE] [--prefix NAME] [--filter PAR] [--no-filter] [--mask-thresh VAL]
#

set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $SCRIPT_NAME [OPTIONS]"
    echo ""
    echo "Export MiaplPy network timeseries to HDF-EOS5 (PS, DS, filtDS), geocode aux,"
    echo "and add REF_LAT/REF_LON. Runs save_hdfeos5.py and geocode.py in parallel."
    echo ""
    echo "Options:"
    echo "  --dir DIR           Network processing directory (default: .)"
    echo "  -t, --template FILE MintPy template/cfg (default: smallbaselineApp.cfg)"
    echo "  --prefix NAME       HE5 suffix (Del4, Sing, SeqN, Mini, ...); default: from network_* dirname"
    echo "  --filter PAR        Lowpass gaussian filter parameter (default: 0.7)"
    echo "  --no-filter         Skip spatial_filter and filtered HE5/geocode products"
    echo "  --mask-thresh VAL   Threshold for generate_mask.py (default: from template or 0.7)"
    echo "  --help, -h          Show this help"
    echo ""
    echo "Examples:"
    echo "  $SCRIPT_NAME --dir network_delaunay_4 -t smallbaselineApp.cfg --prefix Del4 --filter 0.7"
    echo "  $SCRIPT_NAME --dir . --prefix Sing --mask-thresh 0.75"
    echo "  $SCRIPT_NAME --dir network_single_reference --no-filter"
    exit 0
}

work_dir="."
template_file="smallbaselineApp.cfg"
prefix=""
filter_par="0.7"
do_filter=1
mask_thresh=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            [[ $# -lt 2 ]] && { echo "Error: --dir requires an argument" >&2; exit 1; }
            work_dir="$2"
            shift 2
            ;;
        -t|--template)
            [[ $# -lt 2 ]] && { echo "Error: $1 requires an argument" >&2; exit 1; }
            template_file="$2"
            shift 2
            ;;
        --prefix)
            [[ $# -lt 2 ]] && { echo "Error: --prefix requires an argument" >&2; exit 1; }
            prefix="$2"
            shift 2
            ;;
        --filter)
            [[ $# -lt 2 ]] && { echo "Error: --filter requires an argument" >&2; exit 1; }
            filter_par="$2"
            do_filter=1
            shift 2
            ;;
        --no-filter)
            do_filter=0
            shift
            ;;
        --mask-thresh)
            [[ $# -lt 2 ]] && { echo "Error: --mask-thresh requires an argument" >&2; exit 1; }
            mask_thresh="$2"
            shift 2
            ;;
        --help|-h)
            usage
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1" >&2
            echo "Use $SCRIPT_NAME --help for available options" >&2
            exit 1
            ;;
        *)
            echo "Error: unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

get_network_prefix() {
    local network_dir_name="$1"
    local network_name
    if [[ "$network_dir_name" != *network_* ]]; then
        echo "Error: cannot derive --prefix from directory name '$network_dir_name' (expected network_*)" >&2
        return 1
    fi
    network_name="${network_dir_name#*network_}"
    if [[ "$network_name" == *delaunay_4* ]]; then
        echo "Del4"
    elif [[ "$network_name" == *single_reference* ]]; then
        echo "Sing"
    elif [[ "$network_name" == *sequential_1* ]]; then
        echo "Seq1"
    elif [[ "$network_name" == *sequential_2* ]]; then
        echo "Seq2"
    elif [[ "$network_name" == *sequential_3* ]]; then
        echo "Seq3"
    elif [[ "$network_name" == *sequential_4* ]]; then
        echo "Seq4"
    elif [[ "$network_name" == *sequential_5* ]]; then
        echo "Seq5"
    elif [[ "$network_name" == *sequential_6* ]]; then
        echo "Seq6"
    elif [[ "$network_name" == *sequential_8* ]]; then
        echo "Seq8"
    elif [[ "$network_name" == *mini_stacks* ]]; then
        echo "Mini"
    else
        echo "Error: network name not recognized: $network_name" >&2
        return 1
    fi
}

wait_pids() {
    local fail=0
    local pid
    for pid in "$@"; do
        if ! wait "$pid"; then
            fail=1
        fi
    done
    [[ $fail -eq 0 ]] || return 1
    return 0
}

cd "$work_dir" || { echo "Error: cannot cd to $work_dir" >&2; exit 1; }
work_dir="$(pwd)"

if [[ -z "$prefix" ]]; then
    prefix="$(get_network_prefix "$(basename "$work_dir")")" || exit 1
fi

if [[ ! -f "$template_file" ]]; then
    echo "Error: template not found: $template_file" >&2
    exit 1
fi

if [[ -z "$mask_thresh" ]]; then
    mask_thresh=$(awk -F= '/^[[:space:]]*mintpy\.networkInversion\.minTempCoh[[:space:]]*=/ {
        gsub(/[[:space:]]/, "", $2); print $2; exit
    }' "$template_file")
    [[ -z "$mask_thresh" ]] && mask_thresh="0.7"
fi

ts_glob=(timeseries_*demErr.h5)
if [[ ! -e "${ts_glob[0]}" ]]; then
    echo "Error: no timeseries_*demErr.h5 in $work_dir" >&2
    exit 1
fi

source "${SCRIPT_DIR}/../lib/common_helpers.sh"

if [[ $do_filter -eq 1 ]]; then
    echo "Running spatial_filter.py ..."
    spatial_filter.py temporalCoherence.h5 -f lowpass_gaussian -p "$filter_par"
    echo "Running generate_mask.py ..."
    generate_mask.py temporalCoherence_lowpass_gaussian.h5 -m "$mask_thresh"
fi

echo "Running save_hdfeos5.py in parallel (prefix=$prefix) ..."
pids=()
save_hdfeos5.py timeseries_*demErr.h5 --tc temporalCoherence.h5 --asc avgSpatialCoh.h5 \
    -m ../maskPS.h5 -g inputs/geometryRadar.h5 --dem-error demErr.h5 \
    -t "$template_file" --suffix "${prefix}PS" &
pids+=($!)
save_hdfeos5.py timeseries_*demErr.h5 --tc temporalCoherence.h5 --asc avgSpatialCoh.h5 \
    -m maskTempCoh.h5 -g inputs/geometryRadar.h5 --dem-error demErr.h5 \
    -t "$template_file" --suffix "${prefix}DS" &
pids+=($!)

if [[ $do_filter -eq 1 ]]; then
    save_hdfeos5.py timeseries_*demErr.h5 --tc temporalCoherence_lowpass_gaussian.h5 \
        --asc avgSpatialCoh.h5 -m maskTempCoh_lowpass_gaussian.h5 --dem-error demErr.h5 \
        -g inputs/geometryRadar.h5 -t "$template_file" --suffix "filt${prefix}DS" &
    pids+=($!)
fi

wait_pids "${pids[@]}" || { echo "Error: one or more save_hdfeos5.py jobs failed" >&2; exit 1; }

echo "Running geocode.py in parallel ..."
pids=()
if [[ $do_filter -eq 1 ]]; then
    geocode.py temporalCoherence_lowpass_gaussian.h5 -t "$template_file" --outdir geo &
    pids+=($!)
    geocode.py maskTempCoh_lowpass_gaussian.h5 -t "$template_file" --outdir geo &
    pids+=($!)
fi
geocode.py ../maskPS.h5 -t "$template_file" --outdir geo &
pids+=($!)

wait_pids "${pids[@]}" || { echo "Error: one or more geocode.py jobs failed" >&2; exit 1; }

echo "Adding REF_LAT/REF_LON to HE5 files ..."
# Match *_${prefix}DS.he5 but not *_filt${prefix}DS.he5
h5file=$(ls ./*_"${prefix}"PS.he5 2>/dev/null | head -1)
[[ -n "$h5file" ]] || { echo "Error: ${prefix}PS.he5 not found" >&2; exit 1; }
add_ref_lalo_to_file "$h5file"

h5file=$(ls ./*_"${prefix}"DS.he5 2>/dev/null | grep -v "_filt${prefix}DS\\.he5\$" | head -1)
[[ -n "$h5file" ]] || { echo "Error: ${prefix}DS.he5 not found" >&2; exit 1; }
add_ref_lalo_to_file "$h5file"

if [[ $do_filter -eq 1 ]]; then
    h5file=$(ls ./*_filt"${prefix}"DS.he5 2>/dev/null | head -1)
    [[ -n "$h5file" ]] || { echo "Error: filt${prefix}DS.he5 not found" >&2; exit 1; }
    add_ref_lalo_to_file "$h5file"
fi

echo "Done: save_miaplpy_hdfeos5.bash (prefix=$prefix)"
