#!/usr/bin/env bash
#
# burst_download.bash — Download ASF bursts and run burst2stack per date
#
# Runs asf_download.sh --print to get burst listing, parses it for dates,
# writes one burst2stack command per date, and runs them in parallel via xargs.
#
# Prerequisites: Run generate_download_command.py first so download_asf_burst.sh
# and download_asf_burst2stack.sh exist in the work directory.
#
# Usage:
#   burst_download.bash [--work-dir DIR] [--slc-dir DIR] [--parallel N] [--skip-listing] [--help]
#

set -e

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

usage() {
    echo "Usage: $SCRIPT_NAME [OPTIONS]"
    echo ""
    echo "Download ASF bursts and run burst2stack per date (parallel)."
    echo ""
    echo "Options:"
    echo "  --relativeOrbit N     Relative orbit number (standalone mode)"
    echo "  --intersectsWith POL  AOI polygon, e.g. 'Polygon((W S, E S, E N, W N, W S))' (standalone mode)"
    echo "  --start-date DATE     Start date YYYY-MM-DD (default: 2000-01-01)"
    echo "  --end-date DATE       End date YYYY-MM-DD (default: 2099-12-31)"
    echo "  --work-dir DIR        Work directory (default: .)"
    echo "  --slc-dir DIR         SLC directory (default: SLC)"
    echo "  --dir DIR             Same as --slc-dir"
    echo "  --parallel N          Max parallel burst2stack jobs (default: 20)"
    echo "  --skip-listing        Skip asf_download --print; use existing asf_burst_listing.txt"
    echo "  --help, -h            Show this help"
    echo ""
    echo "Example:"
    echo "  $SCRIPT_NAME --relativeOrbit 36 --intersectsWith='Polygon((25.32 36.33, 25.49 36.33, 25.49 36.49, 25.32 36.49, 25.32 36.33))' --start-date 2014-10-01 --end-date 2015-12-31 --parallel 20 --dir SLC"
    echo ""
    echo "Template mode: run generate_download_command.py first. Standalone: pass --relativeOrbit and --intersectsWith."
    exit 0
}

work_dir="."
slc_dir="SLC"
parallel=20
skip_listing=0
relative_orbit=""
intersects_with=""
start_date="2000-01-01"
end_date="2099-12-31"

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --work-dir)
            [[ $# -lt 2 ]] && { echo "Error: --work-dir requires an argument" >&2; exit 1; }
            work_dir="$2"
            shift 2
            ;;
        --slc-dir|--dir)
            [[ $# -lt 2 ]] && { echo "Error: $1 requires an argument" >&2; exit 1; }
            slc_dir="$2"
            shift 2
            ;;
        --relativeOrbit=*)
            relative_orbit="${1#--relativeOrbit=}"
            shift
            ;;
        --relativeOrbit)
            [[ $# -lt 2 ]] && { echo "Error: --relativeOrbit requires an argument" >&2; exit 1; }
            relative_orbit="$2"
            shift 2
            ;;
        --intersectsWith=*)
            intersects_with="${1#--intersectsWith=}"
            shift
            ;;
        --intersectsWith)
            [[ $# -lt 2 ]] && { echo "Error: --intersectsWith requires an argument" >&2; exit 1; }
            intersects_with="$2"
            shift 2
            ;;
        --start-date=*)
            start_date="${1#--start-date=}"
            shift
            ;;
        --start-date)
            [[ $# -lt 2 ]] && { echo "Error: --start-date requires an argument" >&2; exit 1; }
            start_date="$2"
            shift 2
            ;;
        --end-date=*)
            end_date="${1#--end-date=}"
            shift
            ;;
        --end-date)
            [[ $# -lt 2 ]] && { echo "Error: --end-date requires an argument" >&2; exit 1; }
            end_date="$2"
            shift 2
            ;;
        --parallel)
            [[ $# -lt 2 ]] && { echo "Error: --parallel requires an argument" >&2; exit 1; }
            parallel="$2"
            shift 2
            ;;
        --skip-listing)
            skip_listing=1
            shift
            ;;
        --help|-h)
            usage
            ;;
        -*)
            echo "Error: unknown option: $1" >&2
            exit 1
            ;;
        *)
            echo "Error: unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

cd "$work_dir" || { echo "Error: cannot cd to $work_dir" >&2; exit 1; }

standalone_mode=0
if [[ -n "$relative_orbit" && -n "$intersects_with" ]]; then
    standalone_mode=1
fi

if [[ $standalone_mode -eq 0 ]]; then
    if [[ ! -f download_asf_burst.sh ]]; then
        echo "Error: download_asf_burst.sh not found in $work_dir. Run generate_download_command.py first, or pass --relativeOrbit and --intersectsWith." >&2
        exit 1
    fi
    if [[ ! -f download_asf_burst2stack.sh ]]; then
        echo "Error: download_asf_burst2stack.sh not found in $work_dir. Run generate_download_command.py first, or pass --relativeOrbit and --intersectsWith." >&2
        exit 1
    fi
fi

mkdir -p "$slc_dir"

# 1. Run ASF listing (unless --skip-listing)
if [[ $skip_listing -eq 0 ]]; then
    echo "Running asf_download.sh --print to populate $slc_dir/asf_burst_listing.txt ..."
    if [[ $standalone_mode -eq 1 ]]; then
        # Standalone: build asf_download command from options
        asf_download.sh --processingLevel=BURST --relativeOrbit="$relative_orbit" \
            --intersectsWith="$intersects_with" --platform=SENTINEL-1A,SENTINEL-1B \
            --start="$start_date" --end="$end_date" --parallel="$parallel" --dir="$slc_dir" --print \
            > "$slc_dir/asf_burst_listing.txt"
    else
        # Template mode: execute first asf_download line from download_asf_burst.sh
        first_line=$(grep 'asf_download' download_asf_burst.sh | head -1)
        eval "$first_line"
    fi
fi

if [[ ! -s "$slc_dir/asf_burst_listing.txt" ]]; then
    echo "Error: $slc_dir/asf_burst_listing.txt is missing or empty. Run without --skip-listing." >&2
    exit 1
fi

# 2. Parse listing for unique dates (portable: no grep -oP, no date -d)
# Data lines start with YYYY-MM-DD
dates=$(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "$slc_dir/asf_burst_listing.txt" 2>/dev/null | \
    sed -E 's/^([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/' | sort -u)

if [[ -z "$dates" ]]; then
    echo "Error: no date lines found in $slc_dir/asf_burst_listing.txt" >&2
    exit 1
fi

# Count bursts per date for parallelism
counts=$(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "$slc_dir/asf_burst_listing.txt" 2>/dev/null | \
    sed -E 's/^([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/' | sort | uniq -c)
max_bursts=1
while read -r cnt _; do
    [[ -n "$cnt" && "$cnt" -gt "$max_bursts" ]] && max_bursts="$cnt"
done <<< "$counts"

# 3. Get burst2stack args: rel_orbit and extent
if [[ $standalone_mode -eq 1 ]]; then
    rel_orbit="$relative_orbit"
    # Convert intersectsWith polygon to extent W S E N via Python
    extent=$(python3 -c "
import sys
from minsar.utils.process_utilities import convert_intersects_string_to_extent_string
_, ext = convert_intersects_string_to_extent_string(sys.argv[1])
print(' '.join(str(x) for x in ext))
" "$intersects_with")
else
    burst2stack_line=$(grep 'burst2stack' download_asf_burst2stack.sh | head -1)
    rel_orbit=$(echo "$burst2stack_line" | sed -E 's/.*--rel-orbit[= ]([^ ]+).*/\1/')
    extent=$(echo "$burst2stack_line" | sed -E 's/.*--extent[= ]([^ ]+ [^ ]+ [^ ]+ [^ ]+).*/\1/')
fi

if [[ -z "$rel_orbit" || -z "$extent" ]]; then
    echo "Error: could not get rel_orbit or extent (standalone: check --relativeOrbit/--intersectsWith; template: check download_asf_burst2stack.sh)" >&2
    exit 1
fi

# 4. Write run_burst2stack (one burst2stack per date)
# burst2stack needs --end-date = start + 1 day (exclusive end)
run_file="$slc_dir/run_burst2stack"
: > "$run_file"

for d in $dates; do
    end_date=$(python3 -c "
from datetime import datetime, timedelta
d = datetime.strptime('$d', '%Y-%m-%d')
print((d + timedelta(days=1)).strftime('%Y-%m-%d'))
")
    echo "burst2stack --rel-orbit $rel_orbit --start-date $d --end-date $end_date --extent $extent --keep-files --all-anns" >> "$run_file"
done

echo "Wrote $run_file with $(wc -l < "$run_file" | tr -d ' \n') burst2stack commands."

# 4a. Remove incomplete SAFEs (SLURM restart: timeout mid-write)
# check_SAFE_completeness.py removes SAFEs missing required files (e.g. preview/map-overlay.kml)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/check_SAFE_completeness.py" ]]; then
    python3 "$SCRIPT_DIR/check_SAFE_completeness.py" "$slc_dir" || true
elif command -v check_SAFE_completeness.py &>/dev/null; then
    check_SAFE_completeness.py "$slc_dir" || true
else
    echo "Warning: check_SAFE_completeness.py not found; skipping incomplete-SAFE removal." >&2
fi

# 4b. Filter run_burst2stack: remove lines for dates that already have a complete SAFE
for safe in "$slc_dir"/*.SAFE; do
    [[ -d "$safe" ]] || continue
    date_str=$(basename "$safe" .SAFE | sed -E 's/.*([0-9]{4})([0-9]{2})([0-9]{2})T.*/\1-\2-\3/')
    [[ "$date_str" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
    grep -v -- "--start-date $date_str " "$run_file" > "${run_file}.tmp" && mv "${run_file}.tmp" "$run_file"
done

if [[ ! -s "$run_file" ]]; then
    echo "All dates already have SAFEs. Nothing to run."
    exit 0
fi

echo "After filtering: $(wc -l < "$run_file" | tr -d ' \n') burst2stack commands remaining."

# 5. Compute parallelism
num_parallel=$(( parallel / max_bursts ))
[[ $num_parallel -lt 1 ]] && num_parallel=1
echo "$num_parallel" > "$work_dir/num_parallel.txt"
echo "num_parallel=$num_parallel"
echo "Running burst2stack with -P $num_parallel ..."
xargs -P "$num_parallel" -I {} bash -c "cd \"$work_dir/$slc_dir\" && {}" < "$run_file" || true

# 7. Post-run verification and retry (Option A)
failures_file="$slc_dir/burst2stack_failures.txt"
rerun_file="$slc_dir/run_burst2stack_rerun"
: > "$failures_file"

_verify_and_build_rerun() {
    local run_f="$1"
    local fail_f="$2"
    local rerun_f="$3"
    : > "$rerun_f"
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        date_from_line=$(echo "$line" | sed -E 's/.*--start-date ([0-9]{4}-[0-9]{2}-[0-9]{2}) .*/\1/')
        [[ "$date_from_line" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
        has_safe=0
        for safe in "$slc_dir"/*.SAFE; do
            [[ -d "$safe" ]] || continue
            safe_date=$(basename "$safe" .SAFE | sed -E 's/.*([0-9]{4})([0-9]{2})([0-9]{2})T.*/\1-\2-\3/')
            if [[ "$safe_date" == "$date_from_line" ]]; then
                has_safe=1
                break
            fi
        done
        if [[ $has_safe -eq 0 ]]; then
            echo "$date_from_line  no SAFE produced" >> "$fail_f"
            echo "$line" >> "$rerun_f"
        fi
    done < "$run_f"
}

# Run check_SAFE_completeness again (remove any incomplete SAFEs from main pass)
if [[ -f "$SCRIPT_DIR/check_SAFE_completeness.py" ]]; then
    python3 "$SCRIPT_DIR/check_SAFE_completeness.py" "$slc_dir" || true
elif command -v check_SAFE_completeness.py &>/dev/null; then
    check_SAFE_completeness.py "$slc_dir" || true
fi

_verify_and_build_rerun "$run_file" "$failures_file" "$rerun_file"

# One retry pass for failed dates
if [[ -s "$rerun_file" ]]; then
    num_rerun=$(wc -l < "$rerun_file" | tr -d ' \n')
    echo "Retrying $num_rerun failed date(s) ..."
    xargs -P "$num_parallel" -I {} bash -c "cd \"$work_dir/$slc_dir\" && {}" < "$rerun_file" || true
    # Re-verify after retry; rebuild failures_file and rerun_file with only still-failed dates
    : > "$failures_file"
    : > "${rerun_file}.tmp"
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        date_from_line=$(echo "$line" | sed -E 's/.*--start-date ([0-9]{4}-[0-9]{2}-[0-9]{2}) .*/\1/')
        [[ "$date_from_line" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
        has_safe=0
        for safe in "$slc_dir"/*.SAFE; do
            [[ -d "$safe" ]] || continue
            safe_date=$(basename "$safe" .SAFE | sed -E 's/.*([0-9]{4})([0-9]{2})([0-9]{2})T.*/\1-\2-\3/')
            if [[ "$safe_date" == "$date_from_line" ]]; then
                has_safe=1
                break
            fi
        done
        if [[ $has_safe -eq 0 ]]; then
            echo "$date_from_line  no SAFE produced (retry)" >> "$failures_file"
            echo "$line" >> "${rerun_file}.tmp"
        fi
    done < "$rerun_file"
    mv "${rerun_file}.tmp" "$rerun_file"
fi

if [[ -s "$failures_file" ]]; then
    num_fail=$(wc -l < "$failures_file" | tr -d ' \n')
    echo "Done. $num_fail date(s) failed (see $failures_file)."
    if [[ -s "$rerun_file" ]]; then
        echo "To rerun: xargs -P $num_parallel -I {} bash -c 'cd $slc_dir && {}' < $rerun_file"
    fi
else
    echo "Done."
fi
