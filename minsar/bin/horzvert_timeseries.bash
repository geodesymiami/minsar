#!/usr/bin/env bash
# horzvert_timeseries.bash
# Resolves paths, writes script-style run_horzvert2timeseries, optionally executes it.
#
# Flow:
#   Step 0: Parse options and resolve file paths (dirs -> radar S1*.he5)
#   Step 0b: Cache check (skip compute steps in run file when fresh)
#   Write: <site>/<mintpy|miaplpy[_YYYYMM_YYYYMM]>/run_horzvert2timeseries
#          (longer of the two input periods; ref & wait; geocode & wait;
#          horzvert_timeseries.py; wait; ingest). Default stops here.
#   --submit: bash run file (Mac/Jetstream/in-job) or create_slurm_jobfile --from-file
#             + run_workflow.bash --jobfile (HPC login). Then HTML/urls.
#
# Run file may contain & / wait — not for LAUNCHER (script-style, like smallbaseline_wrapper.job).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

source ${SCRIPT_DIR}/../lib/utils.sh
source ${SCRIPT_DIR}/../lib/horzvert_timeseries_utils.sh

# Dependencies: utils.sh, horzvert_timeseries_utils.sh, reference_point_hdfeos5.bash,
#   geocode.py, horzvert_timeseries.py, ingest_insarmaps.bash, create_slurm_jobfile.sh,
#   run_workflow.bash, write_insarmaps_framepage_urls.py, create_data_download_commands.py.

normalize_insarmaps_coordinates() {
    local log_file="$1"

    echo "Normalizing coordinates in insarmaps.log to use vert coordinates..."

    local vert_lat=$(grep "vert" "$log_file" | head -n 1 | cut -d/ -f5)
    local vert_lon=$(grep "vert" "$log_file" | head -n 1 | cut -d/ -f6)

    echo "Using vert coordinates: $vert_lat, $vert_lon"

    sed -i.bak -E "s|(/start/)[^/]+/[^/]+/|\1${vert_lat}/${vert_lon}/|" "$log_file"
    sed -i.bak -E "s|flyToDatasetCenter=true|flyToDatasetCenter=false|g" "$log_file"

    rm -f "${log_file}.bak"

    echo "Updated all coordinates in insarmaps.log and disabled flyToDatasetCenter"
}

# Resolve a path to a specific .he5 file.
# If path is a file, return it. If a directory, use PlotData's get_eos5_file
# (selects newest .he5 by mtime; globs path/*.he5 if path contains mintpy or network,
# otherwise path/mintpy/*.he5).
# get_eos5_file prints "HDF5EOS file used: ..." then the path; use only the last line.
# TODO: copy get_eos5_file into minsar to remove PlotData dependency.
resolve_he5() {
    local path="$1"
    if [[ -f "$path" ]]; then
        echo "$path"
    else
        python3 -c "from plotdata.helper_functions import get_eos5_file; print(get_eos5_file('$path'))" | tail -1
    fi
}

# Return 0 if the basename of file matches dataset type (PS, DS, filtDS, filt*DS, geo). Same logic as ingest_insarmaps.bash.
file_matches_dataset() {
    local file="$1"
    local ds_type="$2"
    local base
    base=$(basename "$file")
    case "$ds_type" in
        geo)
            [[ "$base" != *"DS"* && "$base" != *"PS"* ]]
            ;;
        PS)
            [[ "$base" == *"PS"* ]]
            ;;
        DS)
            [[ "$base" == *"DS"* && "$base" != *"filt"* ]]
            ;;
        filtDS|filt*DS)
            [[ "$base" == *"DS"* && "$base" == *"filt"* ]]
            ;;
        *)
            return 1
            ;;
    esac
}

# Resolve one path to a .he5 file: if --dataset is set and path is a directory, pick the youngest .he5 matching that type; otherwise use resolve_he5.
resolve_he5_or_dataset() {
    local path="$1"
    local ds="$2"
    if [[ -f "$path" ]]; then
        echo "$path"
        return
    fi
    if [[ -n "$ds" && -d "$path" ]]; then
        local ds_type
        ds_type=$(echo "$ds" | cut -d',' -f1 | xargs)
        local all_he5
        all_he5=($(ls -t "$path"/*.he5 2>/dev/null))
        if [[ ${#all_he5[@]} -eq 0 ]]; then
            echo "Error: No .he5 files found in directory: $path" >&2
            exit 1
        fi
        local f
        for f in "${all_he5[@]}"; do
            if file_matches_dataset "$f" "$ds_type"; then
                echo "$f"
                return
            fi
        done
        echo "Error: No .he5 file matching --dataset '$ds_type' in directory: $path" >&2
        exit 1
    fi
    resolve_he5 "$path"
}

# Check whether a .he5 file is geocoded (has Y_FIRST in metadata).
# Returns 0 (true) if geocoded, 1 (false) if radar-coded.
is_geocoded() {
    python3 -c "from mintpy.utils import readfile; atr=readfile.read_attribute('$1'); exit(0 if 'Y_FIRST' in atr else 1)"
}

# Compute LON_STEP from LAT_STEP and reference latitude.
# Same formula as horzvert_timeseries.py geocode_timeseries():
#   lon_step = abs(round(lat_step / cos(radians(ref_lat)), 5))
# TODO: copy find_longitude_degree into minsar to remove PlotData dependency.
compute_lon_step() {
    local ref_lat="$1"
    local lat_step="$2"
    python3 -c "from plotdata.helper_functions import find_longitude_degree; print(find_longitude_degree($ref_lat, $lat_step))"
}

# First path segment that matches a sensor token (e.g. SantoriniSenA29 from SantoriniSenA29/miaplpy/.../).
hv_mother_sensor_dir() {
    local file_path="$1"
    local patterns=("Alos2A" "Alos2D" "SenA" "SenD" "CskA" "CskD" "TsxA" "TsxD" "AlosA" "AlosD")
    local segment
    while IFS= read -r -d '/' segment; do
        [[ -z "$segment" ]] && continue
        for pattern in "${patterns[@]}"; do
            if [[ "$segment" == *"$pattern"* ]]; then
                echo "$segment"
                return 0
            fi
        done
    done <<< "${file_path}/"
    local stripped="${file_path#/}"
    stripped="${stripped%/}"
    [[ -n "$stripped" ]] && echo "${stripped%%/*}"
}

# Absolute path to dataset "mother" directory (WORK_DIR-relative or existing dir).
hv_resolve_mother_abs() {
    local name="$1"
    [[ -z "$name" ]] && return 1
    if [[ -d "$name" ]]; then
        (cd "$name" && pwd)
        return 0
    fi
    if [[ -n "${WORK_DIR:-}" && -d "$WORK_DIR/$name" ]]; then
        (cd "$WORK_DIR/$name" && pwd)
        return 0
    fi
    realpath "$name" 2>/dev/null || echo "${WORK_DIR:-.}/$name"
}

# True if string looks like a sensor dataset dir (SantoriniSenA29, ChilesSenD142, ...).
hv_mother_name_is_plausible() {
    local n="$1"
    [[ -z "$n" || "$n" == *"/"* ]] && return 1
    [[ "$n" == *"SenA"* || "$n" == *"SenD"* || "$n" == *"Alos"* || "$n" == *"Csk"* || "$n" == *"Tsx"* ]]
}

# Mother project name for an .he5 used with geocode (path text, resolved file path, file's directory, or PWD).
hv_resolve_mother_name_for_he5_path() {
    local f="$1"
    local m dir_here abs_f d
    [[ -z "$f" ]] && return 1

    m=$(hv_mother_sensor_dir "$f")
    if hv_mother_name_is_plausible "$m"; then
        echo "$m"
        return 0
    fi

    abs_f=$(realpath "$f" 2>/dev/null)
    if [[ -n "$abs_f" ]]; then
        m=$(hv_mother_sensor_dir "$abs_f")
        if hv_mother_name_is_plausible "$m"; then
            echo "$m"
            return 0
        fi
    fi

    d=$(dirname "$f")
    if [[ -d "$d" ]]; then
        dir_here=$(cd "$d" && pwd)
        m=$(hv_mother_sensor_dir "$dir_here")
        if hv_mother_name_is_plausible "$m"; then
            echo "$m"
            return 0
        fi
    fi
    if [[ -n "${WORK_DIR:-}" && "$d" != "." && -d "$WORK_DIR/$d" ]]; then
        dir_here=$(cd "$WORK_DIR/$d" && pwd)
        m=$(hv_mother_sensor_dir "$dir_here")
        if hv_mother_name_is_plausible "$m"; then
            echo "$m"
            return 0
        fi
    fi

    m=$(hv_mother_sensor_dir "$PWD")
    if hv_mother_name_is_plausible "$m"; then
        echo "$m"
        return 0
    fi
    echo ""
}

# Append geocode.py log line only to the project dir that owns this .he5 path.
append_hv_geocode_log_for_file() {
    local file_path="$1"
    local line="$2"
    local mother_name mother_abs
    [[ -z "$line" ]] && return 0
    mother_name=$(hv_resolve_mother_name_for_he5_path "$file_path")
    [[ -z "$mother_name" ]] && return 0
    mother_abs=$(hv_resolve_mother_abs "$mother_name")
    [[ -n "$mother_abs" && -d "$mother_abs" ]] && echo "$line" >> "${mother_abs}/log"
}

# Append one line to each input dataset log (same style as run_workflow.bash: date + script ...).
append_hv_to_project_logs() {
    local line="$1"
    [[ -z "$line" ]] && return 0
    [[ -n "${HV_MOTHER1_ABS:-}" && -d "$HV_MOTHER1_ABS" ]] && echo "$line" >> "${HV_MOTHER1_ABS}/log"
    if [[ -n "${HV_MOTHER2_ABS:-}" && -d "$HV_MOTHER2_ABS" && "$HV_MOTHER2_ABS" != "$HV_MOTHER1_ABS" ]]; then
        echo "$line" >> "${HV_MOTHER2_ABS}/log"
    fi
}

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Usage: $SCRIPT_NAME <file_or_dir1> <file_or_dir2> --ref-lalo LAT LON [options]

Examples:
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878
    $SCRIPT_NAME hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190 --no-insarmaps
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy/network_single_reference hvGalapagosSenA106/miaplpy/network_single_reference --ref-lalo -0.81 -91.190 --no-ingest-los
    $SCRIPT_NAME FernandinaSenD128/miaplpy/network_delaunay_4 FernandinaSenA106/miaplpy/network_delaunay_4 --ref-lalo -0.415 -91.543 --submit

Options:
      --dataset TYPE                  Select .he5 type in a directory: PS, DS, filtDS, filt*DS, geo
      -g, --geom-file FILE1 FILE2     Geometry files for horzvert_timeseries.py
      --mask-thresh FLOAT             Coherence mask threshold (default: 0.55)
      --ref-lalo LAT LON              Reference point (required); also LAT,LON or --ref-lalo=LAT,LON
      --lat-step FLOAT                Latitude step for geocoding
      --lalo-step LAT LON             Lat and lon step for geocoding
      --horz-az-angle FLOAT           Horizontal azimuth angle (default: 90)
      --window-size INT               Reference-point window (default: 3)
      --intervals INT                 Interval block index (default: 2)
      --start-date YYYYMMDD           Start date
      --end-date YYYYMMDD             End date
      --period YYYYMMDD:YYYYMMDD      Date period
      --force                         Recompute even if cached horz/vert are up to date
      --clean                         Remove cached *vert*/*horz*.he5 and .hvparams
      --no-ingest-los                 Skip ingesting radar LOS .he5 files
      --no-insarmaps                  Skip ingest_insarmaps.bash
      --ingest-parallel               Run ingest lines in parallel (& / wait)
      --submit                        Execute run_horzvert2timeseries (default: write run file only)
      --sleep SECS                    Sleep SECS seconds before running
      --num-workers N                 ingest_insarmaps hdfeos5_2json workers (default: 1)
      --mbtiles-num-workers N         ingest_insarmaps mbtiles workers (default: 6)
      --debug                         set -x
    "
    printf "$helptext"
    exit 0
fi

# Log file in the directory where script is invoked (current working directory)
WORK_DIR="$PWD"
LOG_FILE="$WORK_DIR/log"
# Full command line before option parsing (for dataset log files under each sensor dir)
HV_INVOCATION_CMDLINE="$*"

echo "##############################################" | tee -a "$LOG_FILE"
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" | tee -a "$LOG_FILE"

# Initialize option parsing variables (lowercase)
debug_flag=0
force_flag=0
clean_flag=0
ingest_los_flag=1
ingest_insarmaps_flag=1
ingest_parallel_flag=0
submit_flag=0
positional=()

# Default values for options (lowercase - local/temporary variables)
geom_file=()
mask_thresh=""
ref_lalo=()
dataset=""
lat_step=""
lalo_step=()
horz_az_angle=""
window_size=""
intervals=""
start_date=""
stop_date=""
period=""
num_workers=1
mbtiles_num_workers=6
sleep_time=""

# Parse command line arguments
while [[ $# -gt 0 ]]
do
    key="$1"

    case $key in
        -g|--geom-file)
            geom_file=("$2" "$3")
            shift 3
            ;;
        --mask-thresh)
            mask_thresh="$2"
            shift 2
            ;;
        --ref-lalo=*)
            ref_lalo=("${key#*=}")
            shift
            ;;
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
        --dataset)
            dataset="$2"
            shift 2
            ;;
        --lat-step)
            lat_step="$2"
            shift 2
            ;;
        --lalo-step)
            lalo_step=("$2" "$3")
            shift 3
            ;;
        --horz-az-angle)
            horz_az_angle="$2"
            shift 2
            ;;
        --window-size)
            window_size="$2"
            shift 2
            ;;
        --intervals)
            intervals="$2"
            shift 2
            ;;
        --start-date)
            start_date="$2"
            shift 2
            ;;
        --end-date)
            stop_date="$2"
            shift 2
            ;;
        --period)
            period="$2"
            shift 2
            ;;
        --force)
            force_flag=1
            shift
            ;;
        --clean)
            clean_flag=1
            shift
            ;;
        --no-ingest-los)
            ingest_los_flag=0
            shift
            ;;
        --no-insarmaps)
            ingest_insarmaps_flag=0
            shift
            ;;
        --ingest-parallel)
            ingest_parallel_flag=1
            shift
            ;;
        --submit|-s)
            submit_flag=1
            shift
            ;;
        --sleep=*)
            sleep_time="${key#--sleep=}"
            shift
            ;;
        --sleep)
            [[ $# -lt 2 ]] && { echo "Error: --sleep requires a non-negative integer (seconds)" >&2; exit 1; }
            sleep_time="$2"
            shift 2
            ;;
        --num-workers=*)
            num_workers="${key#--num-workers=}"
            shift
            ;;
        --num-workers)
            [[ $# -lt 2 ]] && { echo "Error: --num-workers requires a positive integer" >&2; exit 1; }
            num_workers="$2"
            shift 2
            ;;
        --mbtiles-num-workers=*)
            mbtiles_num_workers="${key#--mbtiles-num-workers=}"
            shift
            ;;
        --mbtiles-num-workers)
            [[ $# -lt 2 ]] && { echo "Error: --mbtiles-num-workers requires a positive integer" >&2; exit 1; }
            mbtiles_num_workers="$2"
            shift 2
            ;;
        --debug)
            debug_flag=1
            shift
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1"
            echo "Use $SCRIPT_NAME --help for available options"
            exit 1
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

set -- "${positional[@]}"

_validate_positive_int_opt() {
    local opt_name="$1" val="$2"
    [[ "$val" =~ ^[1-9][0-9]*$ ]] || {
        echo "Error: $opt_name must be a positive integer (got '$val')" >&2
        exit 1
    }
}
_validate_nonneg_int_opt() {
    local opt_name="$1" val="$2"
    [[ "$val" =~ ^[0-9]+$ ]] || {
        echo "Error: $opt_name must be a non-negative integer (got '$val')" >&2
        exit 1
    }
}
_validate_positive_int_opt "--num-workers" "$num_workers"
_validate_positive_int_opt "--mbtiles-num-workers" "$mbtiles_num_workers"
[[ -n "$sleep_time" ]] && _validate_nonneg_int_opt "--sleep" "$sleep_time"
ingest_workers_opts=(--num-workers "$num_workers" --mbtiles-num-workers "$mbtiles_num_workers")

if [[ -n "$sleep_time" ]]; then
    echo "sleeping $sleep_time secs before starting ..."
    sleep "$sleep_time"
fi

# Validate --ref-lalo type if provided
validate_ref_lalo() {
    local arr=("$@")
    [[ ${#arr[@]} -eq 0 ]] && return 0
    local lat lon
    if [[ ${#arr[@]} -eq 1 ]]; then
        [[ "${arr[0]}" != *","* ]] && { echo "Error: --ref-lalo must be LAT,LON or LAT LON (e.g. --ref-lalo 36.87,25.94)"; exit 1; }
        IFS=',' read -ra parts <<< "${arr[0]}"
        [[ ${#parts[@]} -ne 2 ]] && { echo "Error: --ref-lalo must be LAT,LON or LAT LON"; exit 1; }
        lat=$(echo "${parts[0]}" | xargs)
        lon=$(echo "${parts[1]}" | xargs)
    else
        lat=$(echo "${arr[0]}" | xargs)
        lon=$(echo "${arr[1]}" | xargs)
    fi
    if ! [[ "$lat" =~ ^-?[0-9]+\.?[0-9]*$ ]] || ! [[ "$lon" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
        echo "Error: --ref-lalo requires numeric lat,lon (e.g. --ref-lalo 36.87 25.94)"
        exit 1
    fi
}
validate_ref_lalo "${ref_lalo[@]}"

if [[ ${#ref_lalo[@]} -eq 0 ]]; then
    echo "Error: --ref-lalo is required. Use LAT,LON or LAT LON (see $SCRIPT_NAME --help)"
    exit 1
fi

# Validate --dataset if provided (same allowed values as ingest_insarmaps.bash)
validate_dataset() {
    local ds="$1"
    [[ -z "$ds" ]] && return 0
    IFS=',' read -ra tokens <<< "$ds"
    for t in "${tokens[@]}"; do
        t=$(echo "$t" | xargs)
        [[ -z "$t" ]] && continue
        case "$t" in
            PS|DS|geo) ;;
            filtDS|filt*DS) ;;
            *)
                echo "Error: --dataset '$t' not valid. Allowed: PS, DS, filtDS, filt*DS, geo"
                exit 1
                ;;
        esac
    done
}
[[ -n "$dataset" ]] && validate_dataset "$dataset"

# Check for required positional arguments
if [[ ${#positional[@]} -lt 2 ]]; then
    echo "Error: Two input files are required"
    echo "Usage: $SCRIPT_NAME <dir_or_file1> <dir_or_file2> [options]"
    echo "Use --help for more information"
    exit 1
fi

DIR_OR_FILE1="${positional[0]}"
DIR_OR_FILE2="${positional[1]}"

HV_MOTHER1_NAME=$(hv_mother_sensor_dir "$DIR_OR_FILE1")
HV_MOTHER2_NAME=$(hv_mother_sensor_dir "$DIR_OR_FILE2")
HV_MOTHER1_ABS=$(hv_resolve_mother_abs "$HV_MOTHER1_NAME")
HV_MOTHER2_ABS=$(hv_resolve_mother_abs "$HV_MOTHER2_NAME")
_ts_proj="$(date +"%Y%m%d:%H-%M")"
append_hv_to_project_logs "${_ts_proj} + horzvert_timeseries.bash ${HV_INVOCATION_CMDLINE}"

if [[ ${#positional[@]} -gt 2 ]]; then
    echo "Warning: Unknown parameters provided: ${positional[@]:2}"
    echo "These will be ignored"
fi

[[ $debug_flag == "1" ]] && set -x

# Parse ref_lalo into separate lat/lon variables
REF_LAT=""
REF_LON=""
if [[ ${#ref_lalo[@]} -eq 1 ]]; then
    IFS=',' read -ra _parts <<< "${ref_lalo[0]}"
    REF_LAT="${_parts[0]}"
    REF_LON="${_parts[1]}"
elif [[ ${#ref_lalo[@]} -eq 2 ]]; then
    REF_LAT="${ref_lalo[0]}"
    REF_LON="${ref_lalo[1]}"
fi

###############################################################################
# Step 0: Resolve file paths
###############################################################################
echo ""
echo "##############################################"
echo "Step 0: Resolve file paths"

FILE1=$(resolve_he5_or_dataset "$DIR_OR_FILE1" "$dataset")
FILE2=$(resolve_he5_or_dataset "$DIR_OR_FILE2" "$dataset")

echo "FILE1 (resolved): $FILE1"
echo "FILE2 (resolved): $FILE2"

# Use sibling radar S1*.he5 when resolution returned geo_*.he5 (re-ref + geocode are radar-first).
if ! FILE1=$(hv_he5_radar_los_path "$FILE1"); then exit 1; fi
if ! FILE2=$(hv_he5_radar_los_path "$FILE2"); then exit 1; fi
echo "FILE1 (radar LOS for pipeline): $FILE1"
echo "FILE2 (radar LOS for pipeline): $FILE2"

# Output directory (used for --clean, cache check, and Step 3).
# Keep the mintpy/miaplpy dir covering the longer period, e.g.
#   EtnaSenA44/.../miaplpy_202001_202412 + EtnaSenD124/.../miaplpy_202001_202410
#   → Etna/miaplpy_202001_202412
ORIGINAL_DIR="$PWD"
PROJECT_DIR=$(get_base_projectname "$DIR_OR_FILE1")
processing_method_dir=$(hv_longest_processing_method_dir "$DIR_OR_FILE1" "$DIR_OR_FILE2")
HORZVERT_DIR="${PROJECT_DIR}/${processing_method_dir}"
mkdir -p "$ORIGINAL_DIR/$HORZVERT_DIR"

hv_clean_cached_products() {
    local outdir="$1"
    [[ -d "$outdir" ]] || return 0
    echo "Removing cached horz/vert products in: $outdir"
    rm -f "$outdir"/*vert*.he5 "$outdir"/*horz*.he5 "$outdir"/*.hvparams 2>/dev/null || true
}

hv_python_option_suffix() {
    local suffix=""
    [[ -n "$mask_thresh" ]] && suffix="$suffix --mask-thresh $mask_thresh"
    [[ -n "$REF_LAT" && -n "$REF_LON" ]] && suffix="$suffix --ref-lalo $REF_LAT $REF_LON"
    [[ -n "$lat_step" ]] && suffix="$suffix --lat-step $lat_step"
    [[ -n "$horz_az_angle" ]] && suffix="$suffix --horz-az-angle $horz_az_angle"
    [[ -n "$window_size" ]] && suffix="$suffix --window-size $window_size"
    [[ -n "$intervals" ]] && suffix="$suffix --intervals $intervals"
    [[ -n "$start_date" ]] && suffix="$suffix --start-date $start_date"
    [[ -n "$stop_date" ]] && suffix="$suffix --end-date $stop_date"
    [[ -n "$period" ]] && suffix="$suffix --period $period"
    [[ $force_flag == "1" ]] && suffix="$suffix --force"
    echo "$suffix"
}

if [[ $clean_flag == "1" ]]; then
    hv_clean_cached_products "$ORIGINAL_DIR/$HORZVERT_DIR"
fi

CACHE_HIT=0
if [[ $force_flag == "0" ]]; then
    echo ""
    echo "##############################################"
    echo "Step 0b: Check cached horz/vert products"
    FILE1_ABS=$(realpath "$FILE1")
    FILE2_ABS=$(realpath "$FILE2")
    CACHE_CMD="horzvert_timeseries.py --check-cache-only \"$FILE1_ABS\" \"$FILE2_ABS\"$(hv_python_option_suffix)"
    hv_announce_command "$ORIGINAL_DIR/$HORZVERT_DIR" "$CACHE_CMD"
    if eval "$CACHE_CMD"; then
        # Require products under this run's HORZVERT_DIR (not a legacy bare miaplpy/ only).
        if compgen -G "$ORIGINAL_DIR/$HORZVERT_DIR"/*vert*.he5 > /dev/null \
            && compgen -G "$ORIGINAL_DIR/$HORZVERT_DIR"/*horz*.he5 > /dev/null; then
            CACHE_HIT=1
            echo "Cached horz/vert products are up to date; skipping re-reference, geocode, and compute in run file."
        else
            echo "Python cache reported a hit, but no *vert*/*horz*.he5 under $HORZVERT_DIR; will recompute there."
        fi
    fi
fi

###############################################################################
# Build geocode args and write run_horzvert2timeseries
###############################################################################
DEFAULT_LAT_STEP="0.00014"
GEOCODE_LALO_ARGS=""
if [[ ${#lalo_step[@]} -eq 2 ]]; then
    GEOCODE_LALO_ARGS="--lalo-step ${lalo_step[0]} ${lalo_step[1]}"
elif [[ -n "$lat_step" ]]; then
    LON_STEP=$(compute_lon_step "${REF_LAT:-0}" "$lat_step")
    GEOCODE_LALO_ARGS="--lalo-step $lat_step $LON_STEP"
else
    LON_STEP=$(compute_lon_step "${REF_LAT:-0}" "$DEFAULT_LAT_STEP")
    GEOCODE_LALO_ARGS="--lalo-step $DEFAULT_LAT_STEP $LON_STEP"
fi

get_ingest_dataset_opt() {
    local path="$1"
    local abs_path he5_basename=""
    if [[ "$path" == /* ]]; then
        abs_path="$path"
    else
        abs_path="$ORIGINAL_DIR/$path"
    fi
    if [[ -f "$abs_path" && "$abs_path" == *.he5 ]]; then
        he5_basename=$(basename "$abs_path")
    elif [[ -d "$abs_path" ]]; then
        he5_basename=$(basename "$(ls -t "$abs_path"/*.he5 2>/dev/null | head -n 1)")
    fi
    [[ -z "$he5_basename" ]] && return
    if [[ "$he5_basename" == *"PS"* ]]; then
        echo "PS"
    elif [[ "$he5_basename" == *"filt"* && "$he5_basename" == *"DS"* ]]; then
        echo "filt*DS"
    elif [[ "$he5_basename" == *"DS"* ]]; then
        echo "DS"
    fi
}

HV_RUN_DIR="$ORIGINAL_DIR/$HORZVERT_DIR"
HV_RUN_FILE="$HV_RUN_DIR/run_horzvert2timeseries"
mkdir -p "$HV_RUN_DIR"

# Canonicalize short vs corner-suffix HE5 names before writing literal paths into the run file.
if ! FILE1=$(hv_promote_short_he5_to_corner_filename "$(realpath "$FILE1")"); then exit 1; fi
if ! FILE2=$(hv_promote_short_he5_to_corner_filename "$(realpath "$FILE2")"); then exit 1; fi
FILE1=$(realpath "$FILE1")
FILE2=$(realpath "$FILE2")

GEOM_FILE_ARGS=""
if [[ ${#geom_file[@]} -eq 2 ]]; then
    GEOM_FILE_ARGS=" --geom-file $(printf '%q' "${geom_file[0]}") $(printf '%q' "${geom_file[1]}")"
fi

HV_RUN_FILE="$HV_RUN_FILE" \
HV_RADAR1="$FILE1" \
HV_RADAR2="$FILE2" \
HV_REF_LAT="$REF_LAT" \
HV_REF_LON="$REF_LON" \
HV_OUTDIR="$ORIGINAL_DIR/$HORZVERT_DIR" \
HV_CACHE_HIT="$CACHE_HIT" \
HV_GEOCODE_ARGS="$GEOCODE_LALO_ARGS" \
HV_PY_SUFFIX="$(hv_python_option_suffix)" \
HV_INGEST_PARALLEL="$ingest_parallel_flag" \
HV_INGEST_INSARMAPS="$ingest_insarmaps_flag" \
HV_INGEST_LOS="$ingest_los_flag" \
HV_INGEST_WORKERS_OPTS="${ingest_workers_opts[*]}" \
HV_GEOM_FILE_ARGS="$GEOM_FILE_ARGS" \
HV_DATASET_OPT1="$(get_ingest_dataset_opt "$FILE1")" \
HV_DATASET_OPT2="$(get_ingest_dataset_opt "$FILE2")" \
hv_write_run_horzvert2timeseries

# On HPC login, always materialize the .job envelope (even without --submit).
if hv_should_use_slurm_jobfile; then
    (
        cd "$HV_RUN_DIR"
        create_slurm_jobfile.sh --job-name horzvert2timeseries --from-file run_horzvert2timeseries || true
    )
fi

if [[ $submit_flag == "0" ]]; then
    echo ""
    echo "Wrote $HV_RUN_FILE"
    echo ""
    echo "Re-run with --submit to execute."
    exit 0
fi

echo ""
echo "##############################################"
echo "Executing run_horzvert2timeseries (--submit)"
append_hv_to_project_logs "$(date +'%Y%m%d:%H-%M') + bash/run_workflow run_horzvert2timeseries"
hv_run_or_submit_script "$HV_RUN_FILE" "horzvert2timeseries"

# After successful run: promote paths for HTML bookkeeping, locate outputs, write HTML/urls
if ! FILE1=$(hv_promote_short_he5_to_corner_filename "$(realpath "$FILE1")"); then exit 1; fi
if ! FILE2=$(hv_promote_short_he5_to_corner_filename "$(realpath "$FILE2")"); then exit 1; fi
ORIGINAL_RESOLVED_FILE1="$(realpath "$FILE1")"
ORIGINAL_RESOLVED_FILE2="$(realpath "$FILE2")"

DATA_FILES_TXT="$ORIGINAL_DIR/$HORZVERT_DIR/data_files.txt"
rm -f "$DATA_FILES_TXT"
touch "$DATA_FILES_TXT"

VERT_FILE=$(ls -t "$ORIGINAL_DIR/$HORZVERT_DIR"/*vert*.he5 2>/dev/null | head -1 || true)
HORZ_FILE=$(ls -t "$ORIGINAL_DIR/$HORZVERT_DIR"/*horz*.he5 2>/dev/null | head -1 || true)
if [[ -z "$VERT_FILE" || -z "$HORZ_FILE" ]]; then
    echo "Error: missing *vert*/*horz*.he5 under $ORIGINAL_DIR/$HORZVERT_DIR after run" >&2
    exit 1
fi
echo "$VERT_FILE" >> "$DATA_FILES_TXT"
echo "$HORZ_FILE" >> "$DATA_FILES_TXT"
[[ $ingest_los_flag == "1" ]] && {
    echo "$ORIGINAL_RESOLVED_FILE1" >> "$DATA_FILES_TXT"
    echo "$ORIGINAL_RESOLVED_FILE2" >> "$DATA_FILES_TXT"
}

if [[ $ingest_insarmaps_flag == "0" ]]; then
    exit 0
fi

# Normalize log / write HTML (always after ingest when --submit, including --no-ingest-los)
if [[ -f "$ORIGINAL_DIR/$HORZVERT_DIR/insarmaps.log" ]]; then
    normalize_insarmaps_coordinates "$ORIGINAL_DIR/$HORZVERT_DIR/insarmaps.log"
fi

echo ""
echo "##############################################"
echo "Write InsarMaps HTML / urls / download commands"
HTML_SOURCE="${SCRIPT_DIR}/../html"
cp "$HTML_SOURCE/overlay.html" "$HTML_SOURCE/matrix.html" "$ORIGINAL_DIR/$HORZVERT_DIR/"
cp "$ORIGINAL_DIR/$HORZVERT_DIR/overlay.html" "$ORIGINAL_DIR/$HORZVERT_DIR/index.html"
write_insarmaps_framepage_urls.py "$HORZVERT_DIR" --outdir "$HORZVERT_DIR"
create_data_download_commands.py "$DATA_FILES_TXT"
if [[ -f "$ORIGINAL_DIR/$HORZVERT_DIR/urls.log" ]]; then
    echo "insarmaps frames created:"
    cat "$ORIGINAL_DIR/$HORZVERT_DIR/urls.log"
fi
