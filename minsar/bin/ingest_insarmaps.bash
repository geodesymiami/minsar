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
#   json_mbtiles2insarmaps.py, get_data_footprint_centroid.py, get_zoomfactor_from_data_footprint.py.
#   Sourced: minsarApp_specifics.sh, utils.sh.
# Output: With --ref-lalo the selected .he5 in the input dir is modified in place. insarmaps.log appended. No backup files.

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Examples:
    $SCRIPT_NAME mintpy
    $SCRIPT_NAME miaplpy/network_single_reference
    $SCRIPT_NAME S1_IW1_128_20180303_XXXXXXXX__S00878_S00791_W091201_W091113.he5
    $SCRIPT_NAME TSX_036_20170923_20251008_N2598W08016_N2576W08016_N2576W08011_N2598W08011.csv
    $SCRIPT_NAME hvGalapagosSenD128/mintpy --ref-lalo -0.81,-91.190
    $SCRIPT_NAME hvGalapagosSenD128/miaplpy/network_single_reference
    $SCRIPT_NAME miaplpy/network_single_reference --dataset geo
    $SCRIPT_NAME miaplpy/network_single_reference --dataset PS
    $SCRIPT_NAME miaplpy/network_single_reference --dataset filt*DS
    $SCRIPT_NAME miaplpy/network_single_reference --dataset PS,DS
    $SCRIPT_NAME miaplpy/network_single_reference --dataset PS,DS,filt*DS
    $SCRIPT_NAME mintpy --dataset geo                    # default: both steps (HDFEOS5→JSON/mbtiles + insarmaps)
    $SCRIPT_NAME mintpy --dataset geo --hdfeos5_2json_mbtiles   # step 1 only (same as --step 1)
    $SCRIPT_NAME mintpy --dataset geo --step 1
    $SCRIPT_NAME mintpy --step 1                         # dataset defaults to geo
    $SCRIPT_NAME mintpy --json_mbtiles2insarmaps         # step 2 only (same as --step 2); requires prior step 1

  Options:
      --ref-lalo LAT,LON or LAT LON   Reference point (lat,lon or lat lon)
      --dataset {PS,DS,filtDS,filt*DS,geo} or comma-separated {PS,DS,filt*DS}  Dataset to upload (default: geo)
                                          Use comma-separated values to ingest multiple types: --dataset PS,DS or --dataset PS,DS,filt*DS
      --hdfeos5_2json_mbtiles         Run only HDFEOS5 → JSON/mbtiles (no insarmaps upload); same as --step 1
                                      For a .csv input, step 1 runs hdfeos5_or_csv_2json_mbtiles.py instead of hdfeos5_2json_mbtiles.py
      --json_mbtiles2insarmaps        Run only insarmaps upload (assumes step 1 succeeded); same as --step 2
      --step N                        N is 1 or 2; same effect as the long names above. Also --step=N
      --num-workers N                 Parallel workers for hdfeos5_2json_mbtiles (sets HDFEOS_NUM_WORKERS; default 6 or env)
      --mbtiles-num-workers N         Parallel workers for json_mbtiles2insarmaps (sets MBTILES_NUM_WORKERS; default 6 or env)
      --quiet-summary                 suppress printing generated insarmaps URLs (still appends to insarmaps.log)
      --debug                         Enable debug mode (set -x)
      Default (no step flags): run both steps in order.

      Uses environment variables 
      - INSARMAPSHOST_RECENTDATA : when filename contains XXXXXXXX, else INSARMAPSHOST_OLDDATA

  Output: With --ref-lalo the selected .he5 in the input dir is modified in place. insarmaps.log appended. No backup files.

  Memory: If the HDF5 conversion is killed (OOM), use --num-workers 2 or 1, or set HDFEOS_NUM_WORKERS in the environment.
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
positional=()
# ingest_step: all (default) | step1 (HDFEOS5→JSON/mbtiles only) | step2 (upload only; step1 must have run)
ingest_step="all"

# Default values for options (lowercase - local/temporary variables)
geom_file=()
mask_thresh=""
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
        --debug)
            debug_flag=1
            shift
            ;;
        --quiet-summary)
            quiet_summary=1
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
    ingest_files=("$INPUT_PATH")
    ext_lc=$(echo "${INPUT_PATH##*.}" | tr '[:upper:]' '[:lower:]')
    if [[ "$ext_lc" == "csv" ]]; then
        input_format="csv"
    fi
elif [[ -d "$INPUT_PATH" ]]; then
    # Input is a directory - find .he5 files based on dataset option(s)
    DATA_DIR="$INPUT_PATH"
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

SSARAHOME=${SSARAHOME:-""}
if [[ -n "$SSARAHOME" ]]; then
    INSARMAPS_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insaruser)" 2>/dev/null || echo "")
    INSARMAPS_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_insarpass)" 2>/dev/null || echo "")
    DB_USER=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databaseuser)" 2>/dev/null || echo "")
    DB_PASS=$(python3 -c "import sys; sys.path.insert(0, '$SSARAHOME'); import password_config; print(password_config.docker_databasepass)" 2>/dev/null || echo "")
fi

# Parallelism: env defaults 6; CLI overrides env for the respective step
if [[ -n "$num_workers_cli" ]]; then
    HDFEOS_NUM_WORKERS="$num_workers_cli"
else
    HDFEOS_NUM_WORKERS="${HDFEOS_NUM_WORKERS:-6}"
fi
if [[ -n "$mbtiles_num_workers_cli" ]]; then
    MBTILES_NUM_WORKERS="$mbtiles_num_workers_cli"
else
    MBTILES_NUM_WORKERS="${MBTILES_NUM_WORKERS:-6}"
fi

# Process each input file (.he5 or .csv)
for ingest_file in "${ingest_files[@]}"; do
    echo "####################################"
    echo "Processing: $ingest_file"
    if [[ "$ingest_file" == *"XXXXXXXX"* ]]; then
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
        for insarmaps_host in "${HOSTS[@]}"; do
            echo "####################################"
            echo "Running json_mbtiles2insarmaps.py..."
            cmd="json_mbtiles2insarmaps.py --num-workers $MBTILES_NUM_WORKERS -u \"$INSARMAPS_USER\" -p \"$INSARMAPS_PASS\" --host \"$insarmaps_host\" -P \"$DB_PASS\" -U \"$DB_USER\" --json_folder \"$JSON_DIR\" --mbtiles_file \"$MBTILES_FILE\""

            run_command "$cmd"
        done

        wait   # Wait for all ingests to complete (parallel uinsg & is not implemented)

        # Get center coordinates and zoom factorfrom data_footprint
        read CENTER_LAT CENTER_LON < <(get_data_footprint_centroid.py "$ingest_file" 2>/dev/null || echo "0.0000 0.0000")
        ZOOM_FACTOR=$(get_zoomfactor_from_data_footprint.py "$ingest_file" 2>/dev/null || echo "11.0")

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
