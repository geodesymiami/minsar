#!/usr/bin/env bash
# horzvert_timeseries.bash
# Wrapper script for horzvert_timeseries.py
# Resolves file paths, geocodes radar-coded inputs, runs horzvert_timeseries.py,
# and ingests results into insarmaps.
#
# Flow (2026-03):
#   Step 0: Parse options and resolve file paths (dirs -> specific .he5 via get_eos5_file)
#   Step 1: Geocode inputs if radar-coded (geocode.py; skip if already geocoded)
#   Step 2: Run horzvert_timeseries.py (applies ref point internally, computes vert/horz)
#   Step 3: Locate vert/horz outputs
#   Step 4: Ingest into insarmaps (if not --no-insarmaps)
#           4a: ingest vert/horz (no --ref-lalo, ref already in file)
#           4b: ingest original asc/desc S1*.he5 with --ref-lalo (not geo_*.he5; reference_point_hdfeos5.bash called internally)
#           4c: HTML/URLs

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

source ${SCRIPT_DIR}/../lib/utils.sh

# Dependencies: utils.sh [get_base_projectname], horzvert_timeseries.py (external),
#   geocode.py, write_insarmaps_framepage_urls.py, create_data_download_commands.py, ingest_insarmaps.bash.
#   PlotData: plotdata.helper_functions (get_eos5_file, find_longitude_degree) -- TODO: copy into minsar.

get_path_without_scratchdir() {
    local file_path="$1"
    [[ -z "$file_path" || ! -f "$file_path" ]] && return

    local abs_path=$(realpath "$file_path" 2>/dev/null)
    [[ -z "$abs_path" ]] && abs_path=$(cd "$(dirname "$file_path")" && pwd)/$(basename "$file_path")

    if [[ -n "${SCRATCHDIR:-}" ]]; then
        local scratchdir_resolved=$(realpath "$SCRATCHDIR" 2>/dev/null || (cd "$SCRATCHDIR" && pwd))
        [[ "$abs_path" == "$scratchdir_resolved"/* ]] && abs_path="${abs_path#$scratchdir_resolved/}"
    fi

    echo "$abs_path"
}

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
Examples:
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878
    $SCRIPT_NAME ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878 --intervals 6
    $SCRIPT_NAME hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190
    $SCRIPT_NAME hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190 --no-insarmaps
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy/network_single_reference hvGalapagosSenA106/miaplpy/network_single_reference --ref-lalo -0.81 -91.190 --no-ingest-los
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy/.../filtSingDS.he5 hvGalapagosSenA106/miaplpy/.../filtSingDS.he5 --ref-lalo -0.81 -91.190
    $SCRIPT_NAME FernandinaSenD128/mintpy/ FernandinaSenA106/mintpy/ --ref-lalo -0.453 -91.390
    $SCRIPT_NAME FernandinaSenD128/miaplpy/network_delaunay_4 FernandinaSenA106/miaplpy/network_delaunay_4 --ref-lalo -0.415 -91.543
    $SCRIPT_NAME MaunaLoaSenDT87/mintpy MaunaLoaSenAT124/mintpy --period 20181001:20191031 --ref-lalo 19.50068 -155.55856

  Arguments:
      <file_or_dir1> <file_or_dir2>     Two ascending/descending .he5 files or directories.
                                        If a directory: with --dataset use the youngest .he5 matching that type;
                                        otherwise the newest .he5 is selected (PlotData get_eos5_file).

  Options:
      --dataset TYPE                  Select .he5 by type when argument is a directory: PS, DS, filtDS, filt*DS, or geo.
                                        When not given, resolve_he5 is used (newest .he5 or get_eos5_file).
      --mask-thresh FLOAT             Coherence threshold for masking (default: 0.55)
      --ref-lalo LAT,LON or LAT LON   Reference point (required). Comma form or two numbers;
                                        also --ref-lalo=LAT,LON
      --lat-step FLOAT                Latitude step for geocoding (LON_STEP computed automatically)
      --lalo-step LAT LON             Lat and lon step for geocoding (overrides --lat-step)
      --horz-az-angle FLOAT           Horizontal azimuth angle (default: 90)
      --window-size INT               Window size for reference point lookup (default: 3)
      --intervals INT                 Interval block index (default: 2)
      --start-date YYYYMMDD           Start date of limited period
      --end-date YYYYMMDD             End date of limited period
      --period YYYYMMDD:YYYYMMDD      Period of the search
      --no-ingest-los                 Skip ingesting both input files with --ref-lalo (default: ingest-los is enabled)
      --no-insarmaps                  Skip running ingest_insarmaps.bash (default: insarmaps ingestion is enabled)
      --debug                         Enable debug mode (set -x)

  Geocoding: If inputs are radar S1*.he5, an existing geo_S1*.he5 in the same directory is reused
  only when it is newer than the radar file; otherwise geocode.py is run (refreshes stale geo).
  If a geo_S1*.he5 is selected and the sibling radar file is newer, geocode is re-run from radar.

  Output: data_files.txt, *vert*.he5, *horz*.he5, maskTempCoh.h5, image_pairs.txt.
  Other: overlay.html, index.html (copy of overlay), matrix.html, insarmaps.log, urls.log, download_commands.txt. Overwritten/recreated; no backups.
  Logging: run_workflow-style lines (YYYYMMDD:HH-MM + ...) go to each input dataset mother log for the
  full horzvert invocation and horzvert_timeseries.py. Each geocode.py line goes only to the project log
  for that .he5 path (e.g. SantoriniSenA29/log vs SantoriniSenD109/log), using the file path, its
  directory, or PWD when the project dir is on the path. CWD ./log unchanged.
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
ingest_los_flag=1
ingest_insarmaps_flag=1
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
        --no-ingest-los)
            ingest_los_flag=0
            shift
            ;;
        --no-insarmaps)
            ingest_insarmaps_flag=0
            shift
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

echo "FILE1: $FILE1"
echo "FILE2: $FILE2"

# Save original resolved paths for LOS ingestion (Step 4b). After Step 1, FILE1/FILE2
# may point to geo_*.he5; insarmaps LOS ingest must use the original S1*.he5.
ORIGINAL_RESOLVED_FILE1="$(realpath "$FILE1")"
ORIGINAL_RESOLVED_FILE2="$(realpath "$FILE2")"

###############################################################################
# Step 1: Geocode inputs if radar-coded
###############################################################################
echo ""
echo "##############################################"
echo "Step 1: Geocode inputs if radar-coded"

# geocode.py is always called with --lalo-step LAT_STEP LON_STEP (or --lat-step when only lat is set).
# LON_STEP is derived from ref_lalo[0] via find_longitude_degree when using --lat-step or default.
# Default LAT_STEP when neither --lalo-step nor --lat-step given: 0.00014.
DEFAULT_LAT_STEP="0.00014"
GEOCODE_LALO_ARGS=""
if [[ ${#lalo_step[@]} -eq 2 ]]; then
    GEOCODE_LALO_ARGS="--lalo-step ${lalo_step[0]} ${lalo_step[1]}"
    echo "Using --lalo-step ${lalo_step[0]} ${lalo_step[1]} for geocode.py"
elif [[ -n "$lat_step" ]]; then
    ref_lat_for_lon="${REF_LAT:-0}"
    LON_STEP=$(compute_lon_step "$ref_lat_for_lon" "$lat_step")
    GEOCODE_LALO_ARGS="--lalo-step $lat_step $LON_STEP"
    echo "Using --lalo-step $lat_step $LON_STEP (LON_STEP from ref_lat=$ref_lat_for_lon) for geocode.py"
else
    ref_lat_for_lon="${REF_LAT:-0}"
    LON_STEP=$(compute_lon_step "$ref_lat_for_lon" "$DEFAULT_LAT_STEP")
    GEOCODE_LALO_ARGS="--lalo-step $DEFAULT_LAT_STEP $LON_STEP"
    echo "Using default --lalo-step $DEFAULT_LAT_STEP $LON_STEP (LON_STEP from ref_lat=$ref_lat_for_lon) for geocode.py"
fi

# Writes result path to $2 (temp file). All other output (messages + geocode.py) goes to stdout.
# Refreshes stale geo_*.he5 when sibling radar *.he5 is newer (mtime). Reuses geo only when geo is newer than radar.
geocode_if_needed() {
    local file="$1"
    local out_path="$2"
    local file_dir file_base geo_out radar_in

    file_dir=$(dirname "$file")
    file_base=$(basename "$file")

    if [[ "$file_base" == geo_* ]]; then
        geo_out="${file_dir}/${file_base}"
        radar_in="${file_dir}/${file_base#geo_}"
        if [[ -f "$radar_in" ]] && [[ "$radar_in" -nt "$geo_out" ]] && is_geocoded "$file"; then
            echo "Radar stack newer than geo; re-geocoding from: $radar_in"
            file="$radar_in"
            file_dir=$(dirname "$file")
            file_base=$(basename "$file")
        elif is_geocoded "$file"; then
            echo "Already geocoded: $file"
            echo "$file" > "$out_path"
            return
        elif [[ -f "$radar_in" ]]; then
            echo "Geo file not usable as geocoded input; geocoding from radar: $radar_in"
            file="$radar_in"
            file_dir=$(dirname "$file")
            file_base=$(basename "$file")
        fi
    elif is_geocoded "$file"; then
        echo "Already geocoded: $file"
        echo "$file" > "$out_path"
        return
    fi

    file_dir=$(dirname "$file")
    file_base=$(basename "$file")
    if [[ "$file_base" == geo_* ]]; then
        echo "Error: Cannot geocode: expected radar-coded S1*.he5 beside geo file, missing: ${file_dir}/${file_base#geo_}" >&2
        exit 1
    fi

    geo_out="${file_dir}/geo_${file_base}"

    if is_geocoded "$file"; then
        echo "Already geocoded: $file"
        echo "$file" > "$out_path"
        return
    fi

    if [[ -f "$geo_out" ]] && [[ "$geo_out" -nt "$file" ]]; then
        echo "Using existing geocoded file (newer than radar): $geo_out"
        echo "$geo_out" > "$out_path"
        return
    fi

    echo ""
    echo "Geocoding: $file"
    echo "Running: geocode.py \"$file\" $GEOCODE_LALO_ARGS"
    append_hv_geocode_log_for_file "$file" "$(date +"%Y%m%d:%H-%M") + geocode.py \"$file\" $GEOCODE_LALO_ARGS"
    geocode.py "$file" $GEOCODE_LALO_ARGS

    if [[ ! -f "$geo_out" ]]; then
        echo "Error: Expected geocoded file not found: $geo_out"
        exit 1
    fi
    echo "$geo_out" > "$out_path"
}

TMP1=$(mktemp)
TMP2=$(mktemp)
trap 'rm -f "$TMP1" "$TMP2"' EXIT

echo ""
geocode_if_needed "$FILE1" "$TMP1"
FILE1=$(cat "$TMP1")

echo ""
geocode_if_needed "$FILE2" "$TMP2"
FILE2=$(cat "$TMP2")

echo "After geocoding:"
echo "FILE1: $FILE1"
echo "FILE2: $FILE2"

# Always pass the resolved (and possibly geocoded) .he5 file paths to horzvert_timeseries.py,
# so that when the user passes directories (e.g. with --dataset filt*DS) Python receives the actual files.
ORIGINAL_DIR="$PWD"
FILE1_ABS=$(realpath "$FILE1")
FILE2_ABS=$(realpath "$FILE2")

# Compute output directory from user path (same as old script)
PROJECT_DIR=$(get_base_projectname "$DIR_OR_FILE1")
dir="$([ -f "$DIR_OR_FILE1" ] && dirname "$DIR_OR_FILE1" || echo "$DIR_OR_FILE1")"
processing_method_dir=$(echo "$dir" | tr '/' '\n' | grep -E '^(mintpy|miaplpy)' | head -1 | cut -d'_' -f1)
HORZVERT_DIR="${PROJECT_DIR}/${processing_method_dir}"
mkdir -p "$ORIGINAL_DIR/$HORZVERT_DIR"

###############################################################################
# Step 2: Run horzvert_timeseries.py (from ORIGINAL_DIR, same as old script)
###############################################################################
echo ""
echo "##############################################"
echo "Step 2: Run horzvert_timeseries.py"

CMD="horzvert_timeseries.py \"$FILE1_ABS\" \"$FILE2_ABS\""

[[ -n "$mask_thresh" ]] && CMD="$CMD --mask-thresh $mask_thresh"
[[ -n "$REF_LAT" && -n "$REF_LON" ]] && CMD="$CMD --ref-lalo $REF_LAT $REF_LON"
[[ -n "$lat_step" ]] && CMD="$CMD --lat-step $lat_step"
[[ -n "$horz_az_angle" ]] && CMD="$CMD --horz-az-angle $horz_az_angle"
[[ -n "$window_size" ]] && CMD="$CMD --window-size $window_size"
[[ -n "$intervals" ]] && CMD="$CMD --intervals $intervals"
[[ -n "$start_date" ]] && CMD="$CMD --start-date $start_date"
[[ -n "$stop_date" ]] && CMD="$CMD --end-date $stop_date"
[[ -n "$period" ]] && CMD="$CMD --period $period"

echo ""
echo "Full horzvert_timeseries.py command (for verification):"
echo "$CMD"
append_hv_to_project_logs "$(date +"%Y%m%d:%H-%M") + ${CMD}"
echo ""
eval $CMD

###############################################################################
# Step 3: Locate outputs (same as old script: cd to HORZVERT_DIR, find vert/horz)
###############################################################################
echo ""
echo "##############################################"
echo "Step 3: Locate outputs"

DATA_FILES_TXT="$ORIGINAL_DIR/$HORZVERT_DIR/data_files.txt"
rm -f $DATA_FILES_TXT ; touch $DATA_FILES_TXT

cd "$ORIGINAL_DIR/$HORZVERT_DIR"
rm -f insarmaps.log
VERT_FILE=$(ls -t *vert*.he5 2>/dev/null | head -1)
HORZ_FILE=$(ls -t *horz*.he5 2>/dev/null | head -1)

echo "Found vert file: $VERT_FILE"
echo "Found horz file: $HORZ_FILE"

###############################################################################
# Step 4: Ingest (if not --no-insarmaps)
###############################################################################

if [[ $ingest_insarmaps_flag == "0" ]]; then
    exit 0
fi

echo ""
echo "##############################################"
echo "Step 4: Ingest into insarmaps"

echo ""
echo "##############################################"
echo "ingest_insarmaps.bash $VERT_FILE"
ingest_insarmaps.bash "$VERT_FILE"
echo "$ORIGINAL_DIR/$HORZVERT_DIR/$VERT_FILE" >> $DATA_FILES_TXT

echo ""
echo "##############################################"
echo "ingest_insarmaps.bash $HORZ_FILE"
ingest_insarmaps.bash "$HORZ_FILE"
echo "$ORIGINAL_DIR/$HORZVERT_DIR/$HORZ_FILE" >> $DATA_FILES_TXT

get_ingest_dataset_opt() {
    local path="$1"
    local abs_path
    if [[ "$path" == /* ]]; then
        abs_path="$path"
    else
        abs_path="$ORIGINAL_DIR/$path"
    fi
    local he5_basename=""
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
if [[ $ingest_los_flag == "1" ]]; then
    cd "$ORIGINAL_DIR/$HORZVERT_DIR"
    echo ""
    echo "##############################################"
    # Use original resolved S1*.he5 for LOS ingestion, not geo_*.he5 (see ORIGINAL_RESOLVED_FILE1/2).
    ingest_dataset_opt1=$(get_ingest_dataset_opt "$ORIGINAL_RESOLVED_FILE1")
    if [[ -n "$ingest_dataset_opt1" ]]; then
        echo "ingest_insarmaps.bash $ORIGINAL_RESOLVED_FILE1 --ref-lalo ${ref_lalo[*]} --dataset $ingest_dataset_opt1"
        ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE1" --ref-lalo "${ref_lalo[@]}" --dataset "$ingest_dataset_opt1"
    else
        echo "ingest_insarmaps.bash $ORIGINAL_RESOLVED_FILE1 --ref-lalo ${ref_lalo[*]}"
        ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE1" --ref-lalo "${ref_lalo[@]}"
    fi
    echo "$ORIGINAL_RESOLVED_FILE1" >> $DATA_FILES_TXT

    echo ""
    echo "##############################################"
    ingest_dataset_opt2=$(get_ingest_dataset_opt "$ORIGINAL_RESOLVED_FILE2")
    if [[ -n "$ingest_dataset_opt2" ]]; then
        echo "ingest_insarmaps.bash $ORIGINAL_RESOLVED_FILE2 --ref-lalo ${ref_lalo[*]} --dataset $ingest_dataset_opt2"
        ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE2" --ref-lalo "${ref_lalo[@]}" --dataset "$ingest_dataset_opt2"
    else
        echo "ingest_insarmaps.bash $ORIGINAL_RESOLVED_FILE2 --ref-lalo ${ref_lalo[*]}"
        ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE2" --ref-lalo "${ref_lalo[@]}"
    fi
    echo "$ORIGINAL_RESOLVED_FILE2" >> $DATA_FILES_TXT

    normalize_insarmaps_coordinates "insarmaps.log"

    echo ""
    echo "##############################################"
    cd "$ORIGINAL_DIR"
    HTML_SOURCE="${SCRIPT_DIR}/../html"
    cp "$HTML_SOURCE"/*.html "$ORIGINAL_DIR/$HORZVERT_DIR/"
    cp "$ORIGINAL_DIR/$HORZVERT_DIR/overlay.html" "$ORIGINAL_DIR/$HORZVERT_DIR/index.html"
    write_insarmaps_framepage_urls.py "$HORZVERT_DIR" --outdir "$HORZVERT_DIR"
    create_data_download_commands.py "$DATA_FILES_TXT"

    echo "insarmaps frames created:"
    cat "$HORZVERT_DIR/urls.log"
fi
