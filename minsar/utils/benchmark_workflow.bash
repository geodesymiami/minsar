#!/usr/bin/env bash
# Run the first line of each given run file with OMP_NUM_THREADS=1,2,4 (or custom list),
# measure with /usr/bin/time -v, and write summary to benchmark_threads.txt.

set -e

SCRIPT_NAME="benchmark_workflow.bash"
OUTFILE_DEFAULT="benchmark_threads.txt"
RUNFILES_DIR_DEFAULT="run_files"
THREADS_DEFAULT="1,2,4"

usage() {
    echo "Usage: $SCRIPT_NAME [OPTIONS] RUN_FILE [RUN_FILE ...]"
    echo ""
    echo "Run the first (non-empty) line of each RUN_FILE with different OMP_NUM_THREADS,"
    echo "measure with /usr/bin/time -v, and append summary to a text file."
    echo ""
    echo "Options:"
    echo "  --help                    Show this help"
    echo "  --OMP_NUM_THREADS N,M,... Comma-separated thread counts (default: $THREADS_DEFAULT)"
    echo "  --outfile FILE            Output file (default: $OUTFILE_DEFAULT)"
    echo "  --runfiles-dir DIR         Directory for run files when name has no path (default: $RUNFILES_DIR_DEFAULT)"
    echo ""
    echo "Examples:"
    echo "  topsStack:"
    echo "    $SCRIPT_NAME run_01_unpack_topo_reference run_02_unpack_secondary_slc run_03_average_baseline run_04_extract_burst_overlaps run_05_overlap_geo2rdr run_06_overlap_resample run_07_pairs_misreg run_08_timeseries_misreg"
    echo "    $SCRIPT_NAME run_09_fullBurst_geo2rdr run_10_fullBurst_resample run_11_extract_stack_valid_region run_12_merge_reference_secondary_slc run_13_generate_burst_igram run_14_merge_burst_igram run_15_filter_coherence run_16_unwrap"
    echo "  stripmapStack:"
    echo "    $SCRIPT_NAME run_01_crop run_02_reference run_03_focus_split run_04_geo2rdr_coarseResamp run_05_refineSecondaryTiming run_06_invertMisreg run_07_fineResamp run_08_grid_baseline run_09_igram"
    echo "  miaplpy:"
    echo "    $SCRIPT_NAME run_01_miaplpy_load_data run_02_miaplpy_phase_linking run_03_miaplpy_concatenate_patches run_04_miaplpy_generate_ifgram run_05_miaplpy_unwrap_ifgram run_06_miaplpy_load_ifgram run_07_mintpy_ifgram_correction run_08_miaplpy_invert_network"
    echo "  All run files (exclude .job, .e, numbered suffixes):"
    echo "    $SCRIPT_NAME \$(ls run_* | grep -vE '\\.(job|e)\$|_[0-9]+\$')"
    exit 0
}

# Parse options
OUTFILE="$OUTFILE_DEFAULT"
RUNFILES_DIR="$RUNFILES_DIR_DEFAULT"
THREADS_STR="$THREADS_DEFAULT"
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            usage
            ;;
        --OMP_NUM_THREADS)
            [[ $# -lt 2 ]] && { echo "Error: --OMP_NUM_THREADS requires a value" >&2; exit 1; }
            THREADS_STR="$2"
            shift 2
            ;;
        --outfile)
            [[ $# -lt 2 ]] && { echo "Error: --outfile requires a value" >&2; exit 1; }
            OUTFILE="$2"
            shift 2
            ;;
        --runfiles-dir)
            [[ $# -lt 2 ]] && { echo "Error: --runfiles-dir requires a value" >&2; exit 1; }
            RUNFILES_DIR="$2"
            shift 2
            ;;
        -?*|--*)
            echo "Error: unknown option: $1" >&2
            exit 1
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

if [[ ${#POSITIONAL[@]} -eq 0 ]]; then
    echo "Error: at least one RUN_FILE is required" >&2
    usage
fi

# Split comma-separated threads into array
IFS=',' read -ra THREADS <<< "$THREADS_STR"

# Resolve run file path: if no directory in name, try runfiles_dir/name
resolve_runfile() {
    local name="$1"
    if [[ "$name" == */* ]]; then
        echo "$name"
    elif [[ -f "$RUNFILES_DIR/$name" ]]; then
        echo "$RUNFILES_DIR/$name"
    else
        echo "$name"
    fi
}

# Parse elapsed (wall clock) from time -v output. Format: "Elapsed (wall clock) time (h:mm:ss or m:ss): 1:23.45" or "0:01:23"
elapsed_seconds() {
    local logfile="$1"
    local line
    line=$(grep "Elapsed (wall clock)" "$logfile" 2>/dev/null || true)
    if [[ -z "$line" ]]; then
        echo "0"
        return
    fi
    local value
    value=$(echo "$line" | sed -n 's/.*): \([0-9:.]*\)$/\1/p')
    if [[ -z "$value" ]]; then
        echo "0"
        return
    fi
    # Convert m:ss or h:mm:ss to seconds
    awk -F: -v v="$value" 'BEGIN{
        n=split(v,a,":");
        if(n==2) sec=a[1]*60+a[2];
        else if(n==3) sec=a[1]*3600+a[2]*60+a[3];
        else sec=0;
        printf "%.2f", sec
    }'
}

# Parse "User time (seconds): 98.20"
parse_time_field() {
    local logfile="$1"
    local key="$2"
    local line
    line=$(grep "$key" "$logfile" 2>/dev/null | head -1)
    if [[ -z "$line" ]]; then
        echo "0"
        return
    fi
    echo "$line" | sed -n 's/.*: \([0-9.]*\)$/\1/p'
}

# Parse "File system inputs: 1024" (bytes)
parse_fs_field() {
    local logfile="$1"
    local key="$2"
    local line
    line=$(grep "$key" "$logfile" 2>/dev/null | head -1)
    if [[ -z "$line" ]]; then
        echo "0"
        return
    fi
    local val
    val=$(echo "$line" | sed -n 's/.*: \([0-9]*\)$/\1/p')
    echo "${val:-0}"
}

# Bytes to MB (divide by 1048576)
bytes_to_mb() {
    local bytes="${1:-0}"
    awk -v b="$bytes" 'BEGIN { printf "%.2f", b/1048576 }'
}

# Write header once (overwrites OUTFILE on first call)
header_written=false
write_header() {
    if [[ "$header_written" == true ]]; then return; fi
    {
        echo "# $SCRIPT_NAME"
        echo "# Date: $(date -Iseconds 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')"
        echo "# Host: $(hostname 2>/dev/null || echo 'unknown')"
        echo "# OMP_NUM_THREADS: $THREADS_STR"
        echo "# user_% and system_% are 100*user_sec/elapsed_sec and 100*system_sec/elapsed_sec (can exceed 100% with multithreading)"
        echo "#"
        printf "%-20s %7s %11s %7s %8s %12s %13s  %s\n" "run_file" "threads" "elapsed_sec" "user_%" "system_%" "fs_inputs_MB" "fs_outputs_MB" "command"
    } > "$OUTFILE"
    header_written=true
}

# Process each run file
for run_arg in "${POSITIONAL[@]}"; do
    run_path=$(resolve_runfile "$run_arg")
    if [[ ! -f "$run_path" ]]; then
        echo "Warning: run file not found, skipping: $run_path" >&2
        continue
    fi

    first_line=""
    while IFS= read -r line; do
        line=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        if [[ -n "$line" ]]; then
            first_line="$line"
            break
        fi
    done < "$run_path"

    if [[ -z "$first_line" ]]; then
        echo "Warning: no non-empty line in $run_path, skipping" >&2
        continue
    fi

    run_basename=$(basename "$run_path")

    for n in "${THREADS[@]}"; do
        n=$(echo "$n" | tr -d ' ')
        [[ -z "$n" ]] && continue

        echo "##########################"
        echo "$run_basename:  running with OMP_NUM_THREADS=$n ...."
        echo "##########################"

        timelog="${TMPDIR:-/tmp}/benchmark_time_$$_${run_basename}_${n}.log"
        export OMP_NUM_THREADS="$n"
        /usr/bin/time -v -o "$timelog" bash -c "$first_line" 2>/dev/null || true

        elapsed=$(elapsed_seconds "$timelog")
        user_sec=$(parse_time_field "$timelog" "User time (seconds)")
        system_sec=$(parse_time_field "$timelog" "System time (seconds)")
        fs_in=$(parse_fs_field "$timelog" "File system inputs")
        fs_out=$(parse_fs_field "$timelog" "File system outputs")

        user_pct="0.00"
        system_pct="0.00"
        if [[ -n "$elapsed" && "${elapsed:-0}" != "0" ]]; then
            user_pct=$(awk -v u="$user_sec" -v e="$elapsed" 'BEGIN { printf "%.1f", (e>0 && u+0) ? 100*u/e : 0 }')
            system_pct=$(awk -v s="$system_sec" -v e="$elapsed" 'BEGIN { printf "%.1f", (e>0 && s+0) ? 100*s/e : 0 }')
        fi

        fs_in_mb=$(bytes_to_mb "$fs_in")
        fs_out_mb=$(bytes_to_mb "$fs_out")

        write_header
        printf "%-20s %7s %11s %7s %8s %12s %13s  %s\n" \
            "$run_basename" "$n" "$elapsed" "$user_pct" "$system_pct" "$fs_in_mb" "$fs_out_mb" "$first_line" >> "$OUTFILE"

        rm -f "$timelog"
    done
done

if [[ "$header_written" == true ]]; then
    echo "Summary written to $OUTFILE"
fi
