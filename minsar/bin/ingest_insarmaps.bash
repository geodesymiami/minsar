#!/usr/bin/env bash
# ingest_insarmaps.bash

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

echo "sourcing ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh ..."
source ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh
echo "sourcing ${SCRIPT_DIR}/../lib/utils.sh ..."
source ${SCRIPT_DIR}/../lib/utils.sh

# Dependencies (PATH): reference_point_hdfeos5.bash, hdfeos5_2json_mbtiles.py, hdfeos5_or_csv_2json_mbtiles.py,
#   get_data_footprint_centroid.py, get_zoomfactor_from_data_footprint.py; step 2 needs rsync/ssh and
#   json_mbtiles2insarmaps.py on the remote host. Sourced: minsarApp_specifics.sh, utils.sh.
# Output: With --ref-lalo the selected .he5 in the input dir is modified in place. insarmaps.log appended. No backup files.

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Examples:
    $SCRIPT_NAME mintpy
    $SCRIPT_NAME miaplpy/network_single_reference --dataset PS,DS,filt*DS --suffix auto
    $SCRIPT_NAME S1_IW1_128_20180303_XXXXXXXX__S00878_S00791_W091201_W091113.he5
    $SCRIPT_NAME TSX_036_20170923_20251008_N2598W08016_N2576W08016_N2576W08011_N2598W08011.csv
    $SCRIPT_NAME hvGalapagosSenD128/mintpy --ref-lalo -0.81,-91.190 --submit
    $SCRIPT_NAME mintpy --dataset geo --step 1
    $SCRIPT_NAME mintpy --json_mbtiles2insarmaps
    $SCRIPT_NAME mintpy --dataset geo --suffix thermal --insarmapshost \$INSARMAPSHOST2 --quiet-summary
    $SCRIPT_NAME mintpy --mask-thresh 0.85 --overwrite
    $SCRIPT_NAME timeseries/S1_….he5 -m tc+sim --vmin 0.7 --vmin-sim 0.5

  Options:
      --ref-lalo LAT,LON or LAT LON   Reference point (lat,lon or lat lon)
      --dataset {PS,DS,filtDS,filt*DS,geo} or comma-separated {PS,DS,filt*DS}  Dataset to upload (default: geo)
                                          Use comma-separated values to ingest multiple types: --dataset PS,DS or --dataset PS,DS,filt*DS
      --suffix TAG or auto              Append _TAG to .he5/.csv basename for ingest (mbtiles/dataset name)
                                          auto reads miaplpy.timeseries.minTempCoh from ../miaplpyApp.cfg (0.85 -> coh085)
      --insarmapshost HOST[,HOST...]  Override INSARMAPSHOST_RECENTDATA / INSARMAPSHOST_OLDDATA for upload
      --hdfeos5_2json_mbtiles         Run only HDFEOS5 → JSON/mbtiles (no insarmaps upload); same as --step 1
                                      For a .csv input, step 1 runs hdfeos5_or_csv_2json_mbtiles.py instead of hdfeos5_2json_mbtiles.py
      --json_mbtiles2insarmaps        Run only insarmaps upload (assumes step 1 succeeded); same as --step 2
      --step N                        N is 1 or 2; same effect as the long names above. Also --step=N
                                      Step 2: rsync JSON/ to REMOTEUSER@host:/data/scratch/<path-under-\$SCRATCHDIR>/,
                                      then ssh-run json_mbtiles2insarmaps.py on the host (--host 127.0.0.1;
                                      DB password from /data/insarmaps2/postgres_dir/.insaradmin_db_password).
                                      After success, removes remote /data/scratch/<project>/ (includes JSON/)
      --num-workers N                 Parallel workers for hdfeos5_2json_mbtiles (sets HDFEOS_NUM_WORKERS; default 1 or env)
      --mbtiles-num-workers N         Parallel workers for json_mbtiles2insarmaps (sets MBTILES_NUM_WORKERS; default 6 or env)
      --quiet-summary                 suppress printing generated insarmaps URLs (still appends to insarmaps.log)
      --submit                        Run ingest now (inline on Mac/Jetstream; jobfile + run_workflow on SLURM login)
                                      Prints InsarMaps URLs after completion when using --submit
      --debug                         Enable debug mode (set -x)
      -m MASK, --mask-source MASK     Remask before ingest (same as remask_he5.py): recommended, tc, similarity, tc+sim, recommendedDensity, psDensity
      --vmin FLOAT                    Cutoff for -m (not used with -m recommended)
      --vmin-sim FLOAT                Similarity cutoff for -m tc+sim
      --mask-thresh FLOAT             Alias for -m tc --vmin (MintPy minTempCoh-style)
      --overwrite                     Replace input .he5 when remasking (no _tcNNN suffix; no backup)
      Default (no step flags): run both steps in order.

      Uses environment variables
      - INSARMAPSHOST_RECENTDATA : when filename contains XXXXXXXX, else INSARMAPSHOST_OLDDATA
      - --insarmapshost overrides both when given
      - REMOTEUSER : ssh/rsync user for step 2 (default: exouser)
      - SCRATCHDIR : required for step 2 remote path under /data/scratch/
      - INSARMAPS_RSH / INSARMAPS_SSH_JUMP : remote shell for step 2 (default: ssh).
                                      From Stampede use e.g. INSARMAPS_SSH_JUMP=exouser@\$REMOTEHOST_DATA
                                      so rsync/ssh hop through jetstream to the InsarMaps host.

  Output: With --ref-lalo the selected .he5 in the input dir is modified in place. insarmaps.log appended. No backup files.

  Memory: Default --num-workers is 1 to limit RAM. Increase only if you have enough memory, or set HDFEOS_NUM_WORKERS.
    "
    printf "$helptext"
    exit 0
fi

# Log file in the directory where script is invoked (current working directory)
WORK_DIR="$PWD"
LOG_FILE="$WORK_DIR/log"

# Log the command line as early as possible (before parsing)
echo "####################################" | tee -a "$LOG_FILE"
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" | tee -a "$LOG_FILE"

# Initialize option parsing variables (lowercase)
debug_flag=0
submit_flag=0
positional=()
# ingest_step: all (default) | step1 (HDFEOS5→JSON/mbtiles only) | step2 (upload only; step1 must have run)
ingest_step="all"

# Default values for options (lowercase - local/temporary variables)
geom_file=()
mask_thresh=""
mask_source=""
mask_vmin=""
mask_vmin_sim=""
mask_overwrite=0
ingest_mask_active=0
ref_lalo=()
dataset="geo"
lat_step=""
horz_az_angle=""
window_size=""
intervals=""
start_date=""
stop_date=""
period=""
num_workers_cli=""
mbtiles_num_workers_cli=""
quiet_summary=0
suffix=""
insarmaps_host_cli=""

# Apply ingest step from numeric argument (1 or 2), long flags, or --step N
_apply_ingest_step_arg() {
    local step_arg="$1"
    case "$step_arg" in
        1)
            if [[ "$ingest_step" == "step2" ]]; then
                echo "Error: step 1 (--step 1, --hdfeos5_2json_mbtiles) cannot be combined with step 2 (--step 2, --json_mbtiles2insarmaps)" >&2
                exit 1
            fi
            ingest_step="step1"
            ;;
        2)
            if [[ "$ingest_step" == "step1" ]]; then
                echo "Error: step 2 (--step 2, --json_mbtiles2insarmaps) cannot be combined with step 1 (--step 1, --hdfeos5_2json_mbtiles)" >&2
                exit 1
            fi
            ingest_step="step2"
            ;;
        *)
            echo "Error: --step must be 1 or 2 (got '${step_arg}')" >&2
            exit 1
            ;;
    esac
}

# Parse command line arguments
while [[ $# -gt 0 ]]
do
    key="$1"

    case $key in
        --mask-thresh)
            mask_thresh="$2"
            shift 2
            ;;
        -m|--mask-source)
            [[ $# -lt 2 ]] && { echo "Error: $key requires a MASK argument" >&2; exit 1; }
            mask_source="$2"
            shift 2
            ;;
        --vmin)
            [[ $# -lt 2 ]] && { echo "Error: --vmin requires a FLOAT argument" >&2; exit 1; }
            mask_vmin="$2"
            shift 2
            ;;
        --vmin-sim)
            [[ $# -lt 2 ]] && { echo "Error: --vmin-sim requires a FLOAT argument" >&2; exit 1; }
            mask_vmin_sim="$2"
            shift 2
            ;;
        --overwrite)
            mask_overwrite=1
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
        --suffix)
            [[ $# -lt 2 ]] && { echo "Error: --suffix requires a TAG" >&2; exit 1; }
            suffix="$2"
            shift 2
            ;;
        --insarmapshost=*)
            insarmaps_host_cli="${key#--insarmapshost=}"
            shift
            ;;
        --insarmapshost)
            [[ $# -lt 2 ]] && { echo "Error: --insarmapshost requires a HOST" >&2; exit 1; }
            insarmaps_host_cli="$2"
            shift 2
            ;;
        --debug)
            debug_flag=1
            shift
            ;;
        --quiet-summary)
            quiet_summary=1
            shift
            ;;
        --submit)
            submit_flag=1
            shift
            ;;
        --step=*)
            _apply_ingest_step_arg "${key#--step=}"
            shift
            ;;
        --step)
            [[ $# -lt 2 ]] && { echo "Error: --step requires an argument: 1 or 2" >&2; exit 1; }
            _apply_ingest_step_arg "$2"
            shift 2
            ;;
        --hdfeos5_2json_mbtiles)
            _apply_ingest_step_arg 1
            shift
            ;;
        --json_mbtiles2insarmaps)
            _apply_ingest_step_arg 2
            shift
            ;;
        --num-workers=*)
            num_workers_cli="${key#--num-workers=}"
            shift
            ;;
        --num-workers)
            [[ $# -lt 2 ]] && { echo "Error: --num-workers requires a positive integer" >&2; exit 1; }
            num_workers_cli="$2"
            shift 2
            ;;
        --mbtiles-num-workers=*)
            mbtiles_num_workers_cli="${key#--mbtiles-num-workers=}"
            shift
            ;;
        --mbtiles-num-workers)
            [[ $# -lt 2 ]] && { echo "Error: --mbtiles-num-workers requires a positive integer" >&2; exit 1; }
            mbtiles_num_workers_cli="$2"
            shift 2
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
        lat="${parts[0]}" lon="${parts[1]}"
    else
        lat="${arr[0]}" lon="${arr[1]}"
    fi
    if ! [[ "$lat" =~ ^-?[0-9]+\.?[0-9]*$ ]] || ! [[ "$lon" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
        echo "Error: --ref-lalo requires numeric lat,lon (e.g. --ref-lalo 36.87 25.94)"
        exit 1
    fi
}
validate_ref_lalo "${ref_lalo[@]}"

# Validate --dataset if provided
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
                echo "Error: --dataset '$t' not valid. Allowed: PS, DS, filtDS, filt*DS, geo (or comma-separated)"
                exit 1
                ;;
        esac
    done
}
validate_dataset "$dataset"

# Resolve remask options (same semantics as remask_he5.py)
resolve_ingest_mask_options() {
    if [[ -n "$mask_thresh" || -n "$mask_source" || -n "$mask_vmin" || -n "$mask_vmin_sim" || "$mask_overwrite" == 1 ]]; then
        ingest_mask_active=1
    fi
    if [[ -n "$mask_thresh" ]]; then
        if [[ -n "$mask_source" && "$mask_source" != "tc" ]]; then
            echo "Error: --mask-thresh implies -m tc; do not combine with -m $mask_source" >&2
            exit 1
        fi
        if [[ -n "$mask_vmin" && "$mask_vmin" != "$mask_thresh" ]]; then
            echo "Error: --mask-thresh conflicts with --vmin" >&2
            exit 1
        fi
        mask_source="tc"
        mask_vmin="$mask_thresh"
    fi
    if [[ $ingest_mask_active -eq 1 && "$ingest_step" == "step2" ]]; then
        echo "Error: mask options cannot be used with --step 2 / --json_mbtiles2insarmaps" >&2
        exit 1
    fi
}
resolve_ingest_mask_options

ingest_apply_remask() {
    local he5="$1"
    local -a cmd=(remask_he5.py "$he5")
    [[ -n "$mask_source" ]] && cmd+=(-m "$mask_source")
    [[ -n "$mask_vmin" ]] && cmd+=(--vmin "$mask_vmin")
    [[ -n "$mask_vmin_sim" ]] && cmd+=(--vmin-sim "$mask_vmin_sim")
    [[ "$mask_overwrite" == 1 ]] && cmd+=(--overwrite)
    echo "####################################" | tee -a "$LOG_FILE" >&2
    echo "Remask before ingest: ${cmd[*]}" | tee -a "$LOG_FILE" >&2
    local remask_tmp new_path remask_status
    remask_tmp=$(mktemp "${TMPDIR:-/tmp}/ingest_remask.XXXXXX")
    "${cmd[@]}" 2>&1 | tee -a "$LOG_FILE" "$remask_tmp" >&2
    remask_status=${PIPESTATUS[0]}
    if [[ "$remask_status" -ne 0 ]]; then
        rm -f "$remask_tmp"
        echo "Error: remask_he5.py failed (exit $remask_status); see log above" >&2
        exit 1
    fi
    new_path=$(sed -nE 's/^Output:[[:space:]]+(.+\.he5)( \(overwrite\))?/\1/p' "$remask_tmp" | tail -1)
    if [[ -z "$new_path" ]]; then
        new_path=$(sed -nE 's/^ HDFEOS file remasked:[[:space:]]+(.+\.he5)/\1/p' "$remask_tmp" | tail -1)
    fi
    rm -f "$remask_tmp"
    if [[ -z "$new_path" || ! -f "$new_path" ]]; then
        echo "Error: remask_he5.py did not produce an output .he5" >&2
        exit 1
    fi
    echo "$new_path"
}

# Normalize --suffix (same rules as sarvey2insarmaps.py)
normalize_suffix() {
    local tag="$1"
    tag="${tag#"${tag%%[![:space:]]*}"}"
    tag="${tag%"${tag##*[![:space:]]}"}"
    tag="${tag#_}"
    tag="${tag%_}"
    if [[ -z "$tag" ]]; then
        echo "Error: --suffix must be a non-empty tag" >&2
        exit 1
    fi
    if [[ "$tag" == *"/"* || "$tag" == *"\\"* ]]; then
        echo "Error: --suffix must not contain path separators" >&2
        exit 1
    fi
    echo "$tag"
}

# Resolve --suffix auto and normalize explicit tags (after DATA_DIR is known).
_resolve_and_normalize_ingest_suffix() {
    [[ -z "$suffix" ]] && return 0
    if [[ "$suffix" == "auto" ]]; then
        suffix="$(resolve_ingest_suffix_auto "$DATA_DIR")" || exit 1
        echo "Ingest suffix (auto from miaplpyApp.cfg or smallbaselineApp.cfg): $suffix" | tee -a "$LOG_FILE"
    fi
    suffix="$(normalize_suffix "$suffix")"
}

# True for prior ingest hardlinks (..._coh085.he5 or legacy ..._075.he5 after PS/DS tag).
_is_prior_ingest_tagged_he5() {
    local base="$1" stem n
    [[ "$base" =~ _coh[0-9]{3}\.he5$ ]] && return 0
    [[ "$base" =~ _[0-9]{3}\.he5$ ]] || return 1
    stem="${base%.he5}"
    [[ "$stem" =~ _([0-9]{3})$ ]] || return 1
    n="${BASH_REMATCH[1]}"
    (( 10#$n >= 50 && 10#$n <= 100 ))
}

# Remove prior ingest tag from stem before applying a new --suffix tag.
_strip_prior_ingest_suffix_from_stem() {
    local stem="$1" n
    if [[ "$stem" =~ ^(.*)_coh[0-9]{3}$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    if [[ "$stem" =~ ^(.*)_([0-9]{3})$ ]]; then
        n="${BASH_REMATCH[2]}"
        if (( 10#$n >= 50 && 10#$n <= 100 )); then
            echo "${BASH_REMATCH[1]}"
            return 0
        fi
    fi
    echo "$stem"
}

# Hardlink/symlink to stem_TAG.ext so mbtiles/dataset names include the tag (no file copy).
apply_ingest_suffix() {
    local src="$1"
    local tag="$2"
    local dir base ext stem dest
    dir="$(dirname "$src")"
    base="$(basename "$src")"
    ext="${base##*.}"
    stem="${base%.*}"
    stem="$(_strip_prior_ingest_suffix_from_stem "$stem")"
    if [[ "$stem" == *"_${tag}" ]]; then
        echo "$src"
        return 0
    fi
    dest="${dir}/${stem}_${tag}.${ext}"
    if [[ -e "$dest" ]]; then
        echo "$dest"
        return 0
    fi
    if ln "$src" "$dest" 2>/dev/null; then
        # Messages must go to stderr/log only — stdout is captured as the path
        echo "Created hardlink for --suffix: $dest" | tee -a "$LOG_FILE" >&2
        echo "$dest"
        return 0
    fi
    if (cd "$dir" && ln -s "$base" "${stem}_${tag}.${ext}"); then
        echo "Created symlink for --suffix: $dest" | tee -a "$LOG_FILE" >&2
        echo "$dest"
        return 0
    fi
    echo "Error: could not create hardlink/symlink for --suffix: $dest" >&2
    exit 1
}

_validate_positive_int_opt() {
    local opt_name="$1" val="$2"
    [[ "$val" =~ ^[1-9][0-9]*$ ]] || {
        echo "Error: $opt_name must be a positive integer (got '$val')" >&2
        exit 1
    }
}
[[ -n "$num_workers_cli" ]] && _validate_positive_int_opt "--num-workers" "$num_workers_cli"
[[ -n "$mbtiles_num_workers_cli" ]] && _validate_positive_int_opt "--mbtiles-num-workers" "$mbtiles_num_workers_cli"

# Check for required positional arguments
if [[ ${#positional[@]} -lt 1 ]]; then
    echo "Error: One input file or directory is required"
    echo "Usage: $SCRIPT_NAME <directory | file.he5 | file.csv> [options]"
    echo "Use --help for more information"
    exit 1
fi

# Enable debug mode if requested
[[ $debug_flag == "1" ]] && set -x

# Important workflow variables (UPPERCASE)
INPUT_PATH="${positional[0]}"

# Function to check if a file matches a dataset type
file_matches_dataset() {
    local file="$1"
    local ds_type="$2"
    
    case "$ds_type" in
        "geo")
            [[ "$file" != *"DS"* && "$file" != *"PS"* ]]
            ;;
        "PS")
            [[ "$file" == *"PS"* ]]
            ;;
        "DS")
            [[ "$file" == *"DS"* && "$file" != *"filt"* ]]
            ;;
        "filtDS"|"filt*DS")
            [[ "$file" == *"DS"* && "$file" == *"filt"* ]]
            ;;
        *)
            return 1
            ;;
    esac
}


# Input format: he5 (default) or csv when the path is a file whose extension is .csv (case-insensitive)
input_format="he5"

# Check if input is a file or directory
if [[ -f "$INPUT_PATH" ]]; then
    # Input is a file - use it directly
    DATA_DIR=$(dirname "$INPUT_PATH")
    _resolve_and_normalize_ingest_suffix
    ingest_files=("$INPUT_PATH")
    ext_lc=$(echo "${INPUT_PATH##*.}" | tr '[:upper:]' '[:lower:]')
    if [[ "$ext_lc" == "csv" ]]; then
        input_format="csv"
    fi
elif [[ -d "$INPUT_PATH" ]]; then
    # Input is a directory - find .he5 files based on dataset option(s)
    DATA_DIR="$INPUT_PATH"
    _resolve_and_normalize_ingest_suffix
    all_he5_files=($(ls -t "$DATA_DIR"/*.he5 2>/dev/null))
    
    if [[ ${#all_he5_files[@]} -eq 0 ]]; then
        echo "Error: No .he5 files found in directory: $DATA_DIR"
        exit 1
    fi
    
    # Parse comma-separated dataset types
    IFS=',' read -ra DATASET_TYPES <<< "$dataset"
    
    # Find the youngest (latest) matching file for each dataset type
    ingest_files=()
    
    # Iterate through dataset types in order (PS,DS means PS file first, then DS file)
    for ds_type in "${DATASET_TYPES[@]}"; do
        ds_type=$(echo "$ds_type" | xargs)  # Trim whitespace
        # Find the youngest file matching this dataset type
        for file in "${all_he5_files[@]}"; do
            # Prefer originals when --suffix is set (skip prior ingest hardlinks)
            if [[ -n "$suffix" ]]; then
                if [[ "$(basename "$file")" == *"_${suffix}.he5" ]]; then
                    continue
                fi
                if _is_prior_ingest_tagged_he5 "$(basename "$file")"; then
                    continue
                fi
            fi
            if file_matches_dataset "$file" "$ds_type"; then
                ingest_files+=("$file")
                break  # Only take the first (youngest) match for this dataset type
            fi
        done
    done
    
    if [[ ${#ingest_files[@]} -eq 0 ]]; then
        echo "Error: No .he5 files found matching dataset option(s) '$dataset' in directory: $DATA_DIR"
        exit 1
    fi
else
    echo "Error: Input path does not exist or is not a file or directory: $INPUT_PATH"
    [[ "$INPUT_PATH" != /* ]] && echo "  (relative paths use current directory: $PWD)"
    exit 1
fi

ingest_submit_slurm_job() {
    local job_file="${WORK_DIR}/ingest_insarmaps.job"
    local -a cmd=(create_ingest_insarmaps_jobfile.py "$INPUT_PATH")
    if [[ ${#ref_lalo[@]} -gt 0 ]]; then
        cmd+=(--ref-lalo)
        if [[ ${#ref_lalo[@]} -eq 1 ]]; then
            cmd+=("${ref_lalo[0]}")
        else
            cmd+=("${ref_lalo[0]}" "${ref_lalo[1]}")
        fi
    fi
    [[ -n "$dataset" ]] && cmd+=(--dataset "$dataset")
    [[ -n "$suffix" ]] && cmd+=(--suffix "$suffix")
    [[ -n "$insarmaps_host_cli" ]] && cmd+=(--insarmapshost "$insarmaps_host_cli")
    [[ $debug_flag == 1 ]] && cmd+=(--debug)
    [[ $quiet_summary == 1 ]] && cmd+=(--quiet-summary)
    [[ -n "$num_workers_cli" ]] && cmd+=(--num-workers "$num_workers_cli")
    [[ -n "$mbtiles_num_workers_cli" ]] && cmd+=(--mbtiles-num-workers "$mbtiles_num_workers_cli")
    [[ -n "$mask_source" ]] && cmd+=(-m "$mask_source")
    [[ -n "$mask_vmin" ]] && cmd+=(--vmin "$mask_vmin")
    [[ -n "$mask_vmin_sim" ]] && cmd+=(--vmin-sim "$mask_vmin_sim")
    [[ "$mask_overwrite" == 1 ]] && cmd+=(--overwrite)
    case "$ingest_step" in
        step1) cmd+=(--hdfeos5_2json_mbtiles) ;;
        step2) cmd+=(--json_mbtiles2insarmaps) ;;
    esac
    echo "Creating jobfile: ${cmd[*]}"
    "${cmd[@]}"
    [[ -f "$job_file" ]] || {
        echo "Error: jobfile not created: $job_file" >&2
        exit 1
    }
    echo "Submitting via run_workflow.bash --jobfile $job_file"
    run_workflow.bash --jobfile "$job_file"
    ingest_print_insarmaps_urls "$DATA_DIR" "$WORK_DIR"
}

if [[ $submit_flag == 1 ]] && minsar_should_use_slurm_jobfile; then
    ingest_submit_slurm_job
    exit 0
fi

SSARAHOME=${SSARAHOME:-""}
if [[ -n "$SSARAHOME" ]]; then
    INSARMAPS_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insaruser)" 2>/dev/null || echo "")
    INSARMAPS_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insarpass)" 2>/dev/null || echo "")
    DB_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databaseuser)" 2>/dev/null || echo "")
    DB_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databasepass)" 2>/dev/null || echo "")
fi

# Parallelism: CLI overrides env; else HDFEOS_NUM_WORKERS default 1, MBTILES_NUM_WORKERS default 6
if [[ -n "$num_workers_cli" ]]; then
    HDFEOS_NUM_WORKERS="$num_workers_cli"
else
    HDFEOS_NUM_WORKERS="${HDFEOS_NUM_WORKERS:-1}"
fi
if [[ -n "$mbtiles_num_workers_cli" ]]; then
    MBTILES_NUM_WORKERS="$mbtiles_num_workers_cli"
else
    MBTILES_NUM_WORKERS="${MBTILES_NUM_WORKERS:-6}"
fi

# Map local DATA_DIR under $SCRATCHDIR to /data/scratch/<relpath> on the insarmaps host.
# Prints: remote_data_dir  remote_project_dir
#   e.g. /data/scratch/Proj/mintpy_x   /data/scratch/Proj
ingest_remote_paths_for_scratch() {
    local data_dir="$1"
    local scratch_abs data_abs rel project_rel remote_data_dir remote_project_dir
    if [[ -z "${SCRATCHDIR:-}" ]]; then
        echo "Error: SCRATCHDIR must be set for step 2 remote upload (path under /data/scratch/)" >&2
        exit 1
    fi
    scratch_abs=$(cd "$SCRATCHDIR" && pwd)
    data_abs=$(cd "$data_dir" && pwd)
    if [[ "$data_abs" != "$scratch_abs" && "$data_abs" != "$scratch_abs"/* ]]; then
        echo "Error: data dir is not under \$SCRATCHDIR ($scratch_abs): $data_abs" >&2
        exit 1
    fi
    rel="${data_abs#"$scratch_abs"/}"
    if [[ -z "$rel" || "$rel" == "$data_abs" ]]; then
        echo "Error: cannot derive path under \$SCRATCHDIR for: $data_abs" >&2
        exit 1
    fi
    project_rel="${rel%%/*}"
    if [[ -z "$project_rel" || "$project_rel" == "." || "$project_rel" == ".." ]]; then
        echo "Error: invalid project name under \$SCRATCHDIR for: $data_abs" >&2
        exit 1
    fi
    remote_data_dir="/data/scratch/${rel}"
    remote_project_dir="/data/scratch/${project_rel}"
    # Safety: never allow deleting /data/scratch itself
    if [[ "$remote_project_dir" != /data/scratch/* || "$remote_project_dir" == "/data/scratch" ]]; then
        echo "Error: refusing unsafe remote project path: $remote_project_dir" >&2
        exit 1
    fi
    echo "$remote_data_dir" "$remote_project_dir"
}

# Remote shell for step 2 rsync/ssh (default: ssh). Nested hop example from Stampede:
#   INSARMAPS_SSH_JUMP=exouser@149.165.154.65  →  rsh becomes: ssh exouser@… ssh
ingest_step2_rsh() {
    if [[ -n "${INSARMAPS_RSH:-}" ]]; then
        echo "$INSARMAPS_RSH"
    elif [[ -n "${INSARMAPS_SSH_JUMP:-}" ]]; then
        echo "ssh ${INSARMAPS_SSH_JUMP} ssh"
    else
        echo "ssh"
    fi
}

# Step 2: rsync JSON/ to host, then ssh-run json_mbtiles2insarmaps.py with local DB (--host 127.0.0.1).
ingest_step2_rsync_and_remote_ingest() {
    local insarmaps_host="$1"
    local local_json_dir="$2"
    local local_mbtiles="$3"
    local remote_user="${REMOTEUSER:-exouser}"
    local remote_pass_file="/data/insarmaps2/postgres_dir/.insaradmin_db_password"
    local remote_path_prefix="${INSARMAPS_REMOTE_PATH:-/data/insarmaps2/code/minsar/tools/insarmaps_scripts:/data/insarmaps2/code/minsar/tools/miniforge3/envs/minsar/bin}"
    local remote_mbtiles_dir="${INSARMAPS_REMOTE_MBTILES_DIR:-/data/insarmaps2/mbtiles_dir}"
    local remote_data_dir remote_project_dir remote_json_dir remote_mbtiles json_basename mbtiles_basename
    local rsh mkdir_cmd rsync_cmd remote_status remote_body cleanup_cmd
    local remote_json_q remote_mbtiles_q remote_pass_q remote_mbtiles_dir_q remote_project_q workers_q path_q

    rsh="$(ingest_step2_rsh)"
    read -r remote_data_dir remote_project_dir < <(ingest_remote_paths_for_scratch "$DATA_DIR")
    json_basename="$(basename "$local_json_dir")"
    mbtiles_basename="$(basename "$local_mbtiles")"
    remote_json_dir="${remote_data_dir}/${json_basename}"
    remote_mbtiles="${remote_json_dir}/${mbtiles_basename}"

    echo "####################################"
    echo "Uploading JSON dir to ${remote_user}@${insarmaps_host}:${remote_json_dir}/ (rsh: $rsh)"
    mkdir_cmd="${rsh} ${remote_user}@${insarmaps_host} mkdir -p $(printf '%q' "$remote_json_dir")"
    run_command "$mkdir_cmd"
    rsync_cmd="rsync -avzh --progress -e $(printf '%q' "$rsh") $(printf '%q' "${local_json_dir}/") $(printf '%q' "${remote_user}@${insarmaps_host}:${remote_json_dir}/")"
    run_command "$rsync_cmd"

    # -p via sudo cat of remote password file (root-only); -u insaradmin.
    # Mbtiles: copy into mbtiles_dir on the host (HTTP /auth login to 127.0.0.1 is unreliable).
    remote_json_q=$(printf '%q' "$remote_json_dir")
    remote_mbtiles_q=$(printf '%q' "$remote_mbtiles")
    remote_pass_q=$(printf '%q' "$remote_pass_file")
    remote_mbtiles_dir_q=$(printf '%q' "$remote_mbtiles_dir")
    workers_q=$(printf '%q' "$MBTILES_NUM_WORKERS")
    path_q=$(printf '%q' "$remote_path_prefix")

    echo "####################################"
    echo "Running json_mbtiles2insarmaps.py on ${remote_user}@${insarmaps_host} (--host 127.0.0.1)..."
    echo "$(date +"%Y%m%d:%H-%M") * ${rsh} ${remote_user}@${insarmaps_host} json_mbtiles2insarmaps.py --host 127.0.0.1 --json_folder ${remote_json_dir}" | tee -a log
    # Single remote bash -lc string (printf %q) so nested rsh (ssh jump ssh) still runs on the final host.
    remote_body="set -euo pipefail; "
    remote_body+="export PATH=${path_q}:\$PATH; "
    remote_body+="PG_PASS=\$(sudo -n cat ${remote_pass_q} | tr -d '[:space:]'); "
    remote_body+="[[ -n \"\$PG_PASS\" ]] || { echo \"Error: empty password from ${remote_pass_file}\" >&2; exit 1; }; "
    remote_body+="json_mbtiles2insarmaps.py --num-workers ${workers_q} -u insaradmin -p \"\$PG_PASS\" --host 127.0.0.1 --json_folder ${remote_json_q}; "
    remote_body+="sudo -n mkdir -p ${remote_mbtiles_dir_q}; "
    remote_body+="sudo -n cp -f ${remote_mbtiles_q} ${remote_mbtiles_dir_q}/; "
    remote_body+="sudo -n chown www-data:www-data ${remote_mbtiles_dir_q}/$(printf '%q' "$mbtiles_basename"); "
    remote_body+="echo \"Installed mbtiles: ${remote_mbtiles_dir}/${mbtiles_basename}\""
    # shellcheck disable=SC2086
    ${rsh} "${remote_user}@${insarmaps_host}" "bash -lc $(printf '%q' "$remote_body")"
    remote_status=$?
    if [[ "$remote_status" -ne 0 ]]; then
        echo "${rsh} ${remote_user}@${insarmaps_host} json_mbtiles2insarmaps.py exited with a non-zero exit code (exit code: $remote_status). Exiting."
        exit 1
    fi

    # Drop remote staging tree for this project (JSON and any parent dirs under /data/scratch/<project>).
    remote_project_q=$(printf '%q' "$remote_project_dir")
    echo "####################################"
    echo "Removing remote project folder ${remote_user}@${insarmaps_host}:${remote_project_dir}"
    cleanup_cmd="${rsh} ${remote_user}@${insarmaps_host} rm -rf ${remote_project_q}"
    run_command "$cleanup_cmd"
}

# Process each input file (.he5 or .csv)
for ingest_file in "${ingest_files[@]}"; do
    if [[ -n "$suffix" ]]; then
        ingest_file="$(apply_ingest_suffix "$ingest_file" "$suffix")"
    fi
    if [[ $ingest_mask_active -eq 1 ]]; then
        if [[ "$input_format" == "csv" ]]; then
            echo "Warning: mask options ignored for CSV input" >&2
        else
            ingest_file="$(ingest_apply_remask "$ingest_file")"
        fi
    fi
    echo "####################################"
    echo "Processing: $ingest_file"
    if [[ -n "$insarmaps_host_cli" ]]; then
        INSARMAPS_HOSTS="$insarmaps_host_cli"
        echo "InsarMaps host (CLI --insarmapshost): $INSARMAPS_HOSTS"
    elif [[ "$ingest_file" == *"XXXXXXXX"* ]]; then
        INSARMAPS_HOSTS="${INSARMAPSHOST_RECENTDATA:-}"
    else
        INSARMAPS_HOSTS="${INSARMAPSHOST_OLDDATA:-}"
    fi
    IFS=',' read -ra HOSTS <<< "$INSARMAPS_HOSTS"
    if [[ "$ingest_step" != "all" ]]; then
        echo "Ingest mode: $ingest_step"
    fi

    if [[ "$ingest_step" == "step2" && ${#ref_lalo[@]} -gt 0 ]]; then
        echo "Warning: --ref-lalo ignored with --step 2 / --json_mbtiles2insarmaps (step 1 must have produced JSON/mbtiles)" >&2
    fi

    # If --ref-lalo was provided, update the reference point in the he5 file (step 1 or full run only; not CSV)
    if [[ "$ingest_step" == "all" || "$ingest_step" == "step1" ]] && [[ ${#ref_lalo[@]} -gt 0 ]]; then
        if [[ "$input_format" == "csv" ]]; then
            echo "Warning: --ref-lalo applies to HDFEOS5 (.he5) only; skipping for CSV input" >&2
        else
            echo "####################################"
            echo "Updating reference point in HDFEOS5 file"
            echo "####################################"

            # Parse reference point coordinates
            if [[ ${#ref_lalo[@]} -eq 1 ]]; then
                # Comma-separated format
                IFS=',' read -ra COORDS <<< "${ref_lalo[0]}"
                REF_LAT="${COORDS[0]}"
                REF_LON="${COORDS[1]}"
            else
                # Space-separated format
                REF_LAT="${ref_lalo[0]}"
                REF_LON="${ref_lalo[1]}"
            fi

            echo "Running: reference_point_hdfeos5.bash $ingest_file --ref-lalo $REF_LAT $REF_LON"
            reference_point_hdfeos5.bash "$ingest_file" --ref-lalo "$REF_LAT" "$REF_LON"
        fi
    fi

    # Determine JSON directory suffix based on file pattern
    JSON_SUFFIX=""
    if [[ "$ingest_file" == *"PS"* ]]; then
        JSON_SUFFIX="_PS"
    elif [[ "$ingest_file" == *"filt"* && "$ingest_file" == *"DS"* ]]; then
        JSON_SUFFIX="_filtDS"
    elif [[ "$ingest_file" == *"DS"* ]]; then
        JSON_SUFFIX="_DS"
    fi

    JSON_DIR=$DATA_DIR/JSON${JSON_SUFFIX}

    if [[ "$input_format" == "csv" ]]; then
        MBTILES_FILE="$JSON_DIR/$(basename "${ingest_file%.csv}.mbtiles")"
    else
        MBTILES_FILE="$JSON_DIR/$(basename "${ingest_file%.he5}.mbtiles")"
    fi

    if [[ "$ingest_step" == "step2" ]]; then
        if [[ ! -d "$JSON_DIR" ]]; then
            echo "Error: JSON directory missing (run --step 1 or --hdfeos5_2json_mbtiles first): $JSON_DIR" >&2
            exit 1
        fi
        if [[ ! -f "$MBTILES_FILE" ]]; then
            echo "Error: mbtiles file missing (run --step 1 or --hdfeos5_2json_mbtiles first): $MBTILES_FILE" >&2
            exit 1
        fi
    fi

    if [[ "$ingest_step" == "all" || "$ingest_step" == "step1" ]]; then
        echo "####################################"
        rm -rf "$JSON_DIR"
        if [[ "$input_format" == "csv" ]]; then
            cmd="hdfeos5_or_csv_2json_mbtiles.py \"$ingest_file\" \"$JSON_DIR\" --num-workers $HDFEOS_NUM_WORKERS"
        else
            cmd="hdfeos5_2json_mbtiles.py \"$ingest_file\" \"$JSON_DIR\" --num-workers $HDFEOS_NUM_WORKERS"
        fi
        run_command "$cmd"
    fi

    if [[ "$ingest_step" == "all" || "$ingest_step" == "step2" ]]; then
        if [[ ${#HOSTS[@]} -eq 0 || -z "${HOSTS[0]:-}" ]]; then
            echo "Error: no InsarMaps host set (use --insarmapshost or INSARMAPSHOST_RECENTDATA / INSARMAPSHOST_OLDDATA)" >&2
            exit 1
        fi
        for insarmaps_host in "${HOSTS[@]}"; do
            [[ -z "$insarmaps_host" ]] && continue
            ingest_step2_rsync_and_remote_ingest "$insarmaps_host" "$JSON_DIR" "$MBTILES_FILE"
        done

        wait   # Wait for all ingests to complete (parallel using & is not implemented)

        # Get center coordinates and zoom factorfrom data_footprint
        read CENTER_LAT CENTER_LON < <(get_data_footprint_centroid.py "$ingest_file" 2>/dev/null || echo "0.0000 0.0000")
        ZOOM_FACTOR=$(get_zoomfactor_from_data_footprint.py "$ingest_file" --viewport-fill 0.5 2>/dev/null || echo "11.0")

        if [[ "$input_format" == "csv" ]]; then
            DATASET_NAME=$(basename "${ingest_file%.csv}")
        else
            DATASET_NAME=$(basename "${ingest_file%.he5}")
        fi

        # Generate insarmaps URLs and store in array
        INSARMAPS_URLS=()
        for insarmaps_host in "${HOSTS[@]}"; do
            # Use https for insarmaps.miami.edu, http for others
            if [[ "$insarmaps_host" == *"insarmaps.miami.edu"* ]]; then
                protocol="https"
            else
                protocol="http"
            fi
            url="${protocol}://${insarmaps_host}/start/${CENTER_LAT}/${CENTER_LON}/${ZOOM_FACTOR}?flyToDatasetCenter=false&startDataset=${DATASET_NAME}"
            INSARMAPS_URLS+=("$url")
        done

        # Write URLs to log files
        if [[ "$quiet_summary" != "1" ]]; then
            echo "Appending to insarmaps.log file"
        fi
        # Determine the log directory: use pic/ if it exists, otherwise use DATA_DIR directly
        if [[ -d "${DATA_DIR}/pic" ]]; then
            LOG_DIR="$DATA_DIR/pic"
        else
            LOG_DIR="$WORK_DIR"
        fi

        for url in "${INSARMAPS_URLS[@]}"; do
            if [[ "$quiet_summary" != "1" ]]; then
                echo "$url"
            fi
            # Only write to WORK_DIR/insarmaps.log if it's different from LOG_DIR/insarmaps.log
            # Normalize paths to compare them (handle relative paths like ".")
            if [[ "$(cd "$WORK_DIR" && pwd)" != "$(cd "$LOG_DIR" && pwd)" ]]; then
                echo "$url" >> "$WORK_DIR/insarmaps.log"
            fi
            echo "$url" >> "$LOG_DIR/insarmaps.log"
        done
    fi
done

if [[ $submit_flag == 1 ]]; then
    ingest_print_insarmaps_urls "$DATA_DIR" "$WORK_DIR"
fi
