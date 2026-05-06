#!/usr/bin/env bash
#
# burst_download.bash — Download ASF bursts and run burst2stack per date
#
# Runs asf_download.sh --print to get burst listing, parses it for dates,
# writes one burst2stack command per date, and runs them in parallel via xargs.
#
# Prerequisites: Run generate_download_command.py first so download_burst2safe.sh
# and burst2stack_cmd.sh exist in the work directory.
#
# Usage:
#   burst_download.bash [--work-dir DIR] [--slc-dir DIR] [--parallel N] [--skip-listing] [--no-check-bursts-includeAOI] [--help]
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
    echo "  --exclude-season WIN  Exclude recurring MMDD-MMDD window, e.g. 1005-0320"
    echo "  --work-dir DIR        Work directory (default: .)"
    echo "  --slc-dir DIR         SLC directory (default: SLC)"
    echo "  --dir DIR             Same as --slc-dir"
    echo "  --parallel N          Max parallel burst2stack jobs (default: 20)"
    echo "  --skip-listing        Skip asf_download --print; use existing asf_burst_listing.txt"
    echo "  --no-check-bursts-includeAOI  Skip check_if_bursts_includeAOI.py and AOI pruning"
    echo "  --help, -h            Show this help"
    echo ""
    echo "Example:"
    echo "  $SCRIPT_NAME --relativeOrbit 36 --intersectsWith='Polygon((25.32 36.33, 25.49 36.33, 25.49 36.49, 25.32 36.49, 25.32 36.33))' --start-date 2014-10-01 --end-date 2015-12-31 --parallel 30 --dir SLC"
    echo "  $SCRIPT_NAME --relativeOrbit 35 --intersectsWith='Polygon((-121.84 36.2, -121.8 36.2, -121.8 36.28, -121.84 36.28, -121.84 36.2))' --start-date 2016-01-01 --end-date 2026-04-10 --exclude-season 1005-0320 --dir SLC"
    echo ""
    echo "Template mode: run generate_download_command.py first. Standalone: pass --relativeOrbit and --intersectsWith."
    exit 0
}

work_dir="."
slc_dir="SLC"
parallel=30
skip_listing=0
skip_check_include_aoi=0
relative_orbit=""
intersects_with=""
start_date="2000-01-01"
end_date="2099-12-31"
exclude_season=""

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
        --exclude-season=*)
            exclude_season="${1#--exclude-season=}"
            shift
            ;;
        --exclude-season)
            [[ $# -lt 2 ]] && { echo "Error: --exclude-season requires an argument" >&2; exit 1; }
            exclude_season="$2"
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
        --no-check-bursts-includeAOI)
            skip_check_include_aoi=1
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
exclude_season_opt=()
if [[ -n "$exclude_season" ]]; then
    exclude_season_opt=( "--exclude-season=$exclude_season" )
fi

# AOI extension loop: when burst2stack fails with "Products from swaths * do not overlap"
AOI_EXTENSION_INIT=0.01      # degrees per step (~1 km at mid-latitudes)
AOI_EXTENSION_MAX=0.05       # max total extension
AOI_EXTENSION_ITER_MAX=5     # max iterations

standalone_mode=0
if [[ -n "$relative_orbit" && -n "$intersects_with" ]]; then
    standalone_mode=1
fi

if [[ $standalone_mode -eq 0 ]]; then
    if [[ ! -f download_burst2safe.sh ]]; then
        echo "Error: download_burst2safe.sh not found in $work_dir. Run generate_download_command.py first, or pass --relativeOrbit and --intersectsWith." >&2
        exit 1
    fi
    if [[ ! -f burst2stack_cmd.sh ]]; then
        echo "Error: burst2stack_cmd.sh not found in $work_dir. Run generate_download_command.py first, or pass --relativeOrbit and --intersectsWith." >&2
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
            --start="$start_date" --end="$end_date" --parallel="$parallel" --dir="$slc_dir" \
            "${exclude_season_opt[@]}" --print \
            > "$slc_dir/asf_burst_listing.txt"
    else
        # Template mode: execute first asf_download line from download_burst2safe.sh
        first_line=$(grep 'asf_download' download_burst2safe.sh | head -1)
        if [[ -n "$exclude_season" ]]; then
            first_line="$first_line --exclude-season=$exclude_season"
        fi
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

if [[ -n "$exclude_season" ]]; then
    dates_filtered=$(python3 -c "
import sys
from minsar.utils.exclude_season import parse_exclude_season, iso_date_to_date, date_in_exclude_season
start_mmdd, end_mmdd = parse_exclude_season(sys.argv[1])
for token in sys.argv[2:]:
    d = iso_date_to_date(token)
    if not date_in_exclude_season(d, start_mmdd, end_mmdd):
        print(token)
" "$exclude_season" $dates)
    dates="$dates_filtered"
fi

if [[ -z "$dates" ]]; then
    echo "All dates were excluded by --exclude-season=$exclude_season. Nothing to run."
    exit 0
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
    burst2stack_line=$(grep 'burst2stack' burst2stack_cmd.sh | head -1)
    rel_orbit=$(echo "$burst2stack_line" | sed -E 's/.*--rel-orbit[= ]([^ ]+).*/\1/')
    extent=$(echo "$burst2stack_line" | sed -E 's/.*--extent[= ]([^ ]+ [^ ]+ [^ ]+ [^ ]+).*/\1/')
fi

if [[ -z "$rel_orbit" || -z "$extent" ]]; then
    echo "Error: could not get rel_orbit or extent (standalone: check --relativeOrbit/--intersectsWith; template: check burst2stack_cmd.sh)" >&2
    exit 1
fi

extent_orig="$extent"   # Store for AOI extension loop (extend from original each iteration)

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
    d_compact=$(echo "$d" | tr -d '-')
    echo "burst2stack --rel-orbit $rel_orbit --start-date $d --end-date $end_date --extent $extent --keep-files --all-anns --pols VV 2> burst2stack_${d_compact}.e" >> "$run_file"
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
count_before=$(wc -l < "$run_file" | tr -d ' \n')
skipped_dates=()
for safe in "$slc_dir"/*.SAFE; do
    [[ -d "$safe" ]] || continue
    date_str=$(basename "$safe" .SAFE | sed -E 's/.*([0-9]{4})([0-9]{2})([0-9]{2})T.*/\1-\2-\3/')
    [[ "$date_str" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
    if grep -q -- "--start-date $date_str " "$run_file"; then
        skipped_dates+=( "$date_str" )
    fi
    grep -v -- "--start-date $date_str " "$run_file" > "${run_file}.tmp" && mv "${run_file}.tmp" "$run_file"
done

if [[ ! -s "$run_file" ]]; then
    echo "All dates already have SAFEs. Nothing to run."
    exit 0
fi

if [[ ${#skipped_dates[@]} -gt 0 ]]; then
    echo "After filtering: $(wc -l < "$run_file" | tr -d ' \n') burst2stack commands remaining (skipped ${#skipped_dates[@]} date(s) that already have complete SAFEs: ${skipped_dates[*]})."
fi

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

_get_burst2stack_error() {
    local date_str="$1"
    local d_compact="${date_str//-/}"
    local errfile="$slc_dir/burst2stack_${d_compact}.e"
    if [[ -f "$errfile" && -s "$errfile" ]]; then
        local err_line
        err_line=$(grep -E 'ValueError:|Error:' "$errfile" | tail -1 2>/dev/null)
        [[ -z "$err_line" ]] && err_line=$(tail -1 "$errfile" 2>/dev/null)
        if [[ -n "$err_line" ]]; then
            echo "$err_line" | head -c 120
        else
            echo "(empty stderr)"
        fi
    else
        echo "(no stderr file)"
    fi
}

_verify_and_build_rerun() {
    local run_f="$1"
    local fail_f="$2"
    local rerun_f="$3"
    local reason_suffix="$4"
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
            err_summary=$(_get_burst2stack_error "$date_from_line")
            echo "$date_from_line  $reason_suffix; $err_summary" >> "$fail_f"
            echo "$line" >> "$rerun_f"
        fi
    done < "$run_f"
}

# AOI extension: detect "Products from swaths * do not overlap" in failures
_has_overlap_errors() {
    [[ -f "$failures_file" ]] && grep -q "Products from swaths" "$failures_file" 2>/dev/null && grep -q "do not overlap" "$failures_file" 2>/dev/null
}

_extract_overlap_failed_dates() {
    if [[ ! -f "$failures_file" ]]; then
        return
    fi
    grep "Products from swaths" "$failures_file" 2>/dev/null | grep "do not overlap" | sed -E 's/^([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/' | sort -u
}

# Extend extent (W S E N) by buffer_deg; output extent on line 1, polygon on line 2
_extend_extent_and_polygon() {
    local extent_str="$1"
    local buf="$2"
    python3 -c "
import sys
w, s, e, n = [float(x) for x in sys.argv[1].split()]
b = float(sys.argv[2])
w -= b; s -= b; e += b; n += b
extent = ' '.join(str(x) for x in [w, s, e, n])
polygon = f'Polygon(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))'
print(extent)
print(polygon)
" "$extent_str" "$buf"
}

# Re-fetch ASF burst listing with extended AOI polygon
_refetch_listing_with_extended_aoi() {
    local polygon="$1"
    echo "Re-fetching burst listing with extended AOI ..."
    if [[ $standalone_mode -eq 1 ]]; then
        asf_download.sh --processingLevel=BURST --relativeOrbit="$relative_orbit" \
            --intersectsWith="$polygon" --platform=SENTINEL-1A,SENTINEL-1B \
            --start="$start_date" --end="$end_date" --parallel="$parallel" --dir="$slc_dir" \
            "${exclude_season_opt[@]}" --print \
            > "$slc_dir/asf_burst_listing.txt"
    else
        first_line=$(grep 'asf_download' download_burst2safe.sh | head -1)
        mod_cmd=$(python3 -c "
import re, sys
line = sys.argv[1]
poly = sys.argv[2]
out_path = sys.argv[3]
new_line = re.sub(r\"--intersectsWith='[^']*'\", \"--intersectsWith='\" + poly + \"'\", line)
new_line = re.sub(r'>[^\\s]+asf_burst_listing\\.txt', '>' + out_path, new_line)
print(new_line)
" "$first_line" "$polygon" "$slc_dir/asf_burst_listing.txt")
        if [[ -n "$exclude_season" ]]; then
            mod_cmd="$mod_cmd --exclude-season=$exclude_season"
        fi
        eval "$mod_cmd"
    fi
}

# Run check_SAFE_completeness again (remove any incomplete SAFEs from main pass)
if [[ -f "$SCRIPT_DIR/check_SAFE_completeness.py" ]]; then
    python3 "$SCRIPT_DIR/check_SAFE_completeness.py" "$slc_dir" || true
elif command -v check_SAFE_completeness.py &>/dev/null; then
    check_SAFE_completeness.py "$slc_dir" || true
fi

_verify_and_build_rerun "$run_file" "$failures_file" "$rerun_file" "no SAFE produced"

# One retry pass for failed dates
if [[ -s "$rerun_file" ]]; then
    num_rerun=$(wc -l < "$rerun_file" | tr -d ' \n')
    echo "Retrying $num_rerun failed date(s) ..."
    xargs -P "$num_parallel" -I {} bash -c "cd \"$work_dir/$slc_dir\" && {}" < "$rerun_file" || true
    # Remove incomplete SAFEs from retry pass so re-verify correctly flags failures
    if [[ -f "$SCRIPT_DIR/check_SAFE_completeness.py" ]]; then
        python3 "$SCRIPT_DIR/check_SAFE_completeness.py" "$slc_dir" || true
    elif command -v check_SAFE_completeness.py &>/dev/null; then
        check_SAFE_completeness.py "$slc_dir" || true
    fi
    # Re-verify after retry; rebuild failures_file and rerun_file with only still-failed dates
    : > "$failures_file"
    _verify_and_build_rerun "$rerun_file" "$failures_file" "${rerun_file}.tmp" "no SAFE produced (retry)"
    mv "${rerun_file}.tmp" "$rerun_file"
fi

# AOI extension loop: if "Products from swaths * do not overlap", extend AOI and retry
aoi_extension_log="$slc_dir/burst2stack_aoi_extension.log"
total_extension=0
iteration=0
while _has_overlap_errors && [[ $iteration -lt $AOI_EXTENSION_ITER_MAX ]] && \
      [[ $(echo "$total_extension $AOI_EXTENSION_MAX" | awk '{print ($1 < $2)}') -eq 1 ]]; do
    if [[ $skip_listing -eq 1 ]]; then
        echo "Error: AOI extension requires re-fetching listing. Re-run without --skip-listing." >&2
        exit 1
    fi

    [[ $iteration -eq 0 ]] && : > "$aoi_extension_log"
    iteration=$((iteration + 1))
    total_extension=$(echo "$total_extension $AOI_EXTENSION_INIT" | awk '{printf "%.4f", $1 + $2}')
    echo "AOI extension attempt $iteration: extending by $AOI_EXTENSION_INIT deg (total $total_extension)"

    ext_output=$(_extend_extent_and_polygon "$extent_orig" "$total_extension")
    extent=$(echo "$ext_output" | head -1)
    extended_polygon=$(echo "$ext_output" | tail -1)
    _refetch_listing_with_extended_aoi "$extended_polygon"

    overlap_dates=$(_extract_overlap_failed_dates)
    echo "iteration=$iteration total_extension=$total_extension extent=$extent dates=$(echo $overlap_dates | tr '\n' ' ')" >> "$aoi_extension_log"
    : > "$rerun_file"
    for d in $overlap_dates; do
        end_d=$(python3 -c "
from datetime import datetime, timedelta
d = datetime.strptime('$d', '%Y-%m-%d')
print((d + timedelta(days=1)).strftime('%Y-%m-%d'))
")
        d_compact=$(echo "$d" | tr -d '-')
        echo "burst2stack --rel-orbit $rel_orbit --start-date $d --end-date $end_d --extent $extent --keep-files --all-anns --pols VV 2> burst2stack_${d_compact}.e" >> "$rerun_file"
    done

    if [[ ! -s "$rerun_file" ]]; then
        echo "Warning: no overlap-failed dates to retry after re-fetch." >&2
        break
    fi

    echo "Running burst2stack for $(wc -l < "$rerun_file" | tr -d ' \n') overlap-failed date(s) with extended AOI ..."
    xargs -P "$num_parallel" -I {} bash -c "cd \"$work_dir/$slc_dir\" && {}" < "$rerun_file" || true

    if [[ -f "$SCRIPT_DIR/check_SAFE_completeness.py" ]]; then
        python3 "$SCRIPT_DIR/check_SAFE_completeness.py" "$slc_dir" || true
    elif command -v check_SAFE_completeness.py &>/dev/null; then
        check_SAFE_completeness.py "$slc_dir" || true
    fi

    # Preserve non-overlap failures; rebuild overlap failures from rerun
    non_overlap_failures=$(grep -v "Products from swaths" "$failures_file" 2>/dev/null || true)
    : > "$failures_file"
    [[ -n "$non_overlap_failures" ]] && echo "$non_overlap_failures" >> "$failures_file"
    _verify_and_build_rerun "$rerun_file" "$failures_file" "${rerun_file}.tmp" "no SAFE produced (AOI ext $iteration)"
    mv "${rerun_file}.tmp" "$rerun_file"
done

if _has_overlap_errors; then
    echo "Error: 'Products from swaths * do not overlap' still present after $iteration AOI extension(s) (max $AOI_EXTENSION_MAX deg). See $failures_file." >&2
    exit 1
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

# 8. AOI coverage pruning: after all burst2stack runs completed, drop dates whose
# burst GeoTIFF footprints do not fully cover the AOI bbox.
#
if [[ "$skip_check_include_aoi" -eq 0 ]]; then
    # We reuse the AOI extent already computed for burst2stack (W S E N) and convert
    # to the bbox format expected by check_if_bursts_includeAOI.py: LAT_S:LAT_N,LON_W:LON_E.
    #
    # This writes $slc_dir/dates_not_including_AOI.txt (one YYYYMMDD per line) and then
    # removes matching paths under $slc_dir (GeoTIFFs + SAFEs) by deleting *${ymd}T*.
    bbox_sn_we=$(python3 -c "
import sys
w, s, e, n = [float(x) for x in sys.argv[1].split()]
print(f'{s}:{n},{w}:{e}')
" "$extent") || {
        echo "ERROR: could not derive bbox from extent '$extent' for AOI pruning." >&2
        exit 1
    }

    check_if_bursts_includeAOI.py "$bbox_sn_we" "$slc_dir"/*.tif* || true
    ndates_file="$slc_dir/dates_not_including_AOI.txt"
    if [[ -f "$ndates_file" ]]; then
        shopt -s nullglob
        while IFS= read -r line || [[ -n "$line" ]]; do
            ymd="$(echo "$line" | tr -d '[:space:]')"
            [[ -z "$ymd" ]] && continue
            [[ "$ymd" =~ ^[0-9]{8}$ ]] || continue
            echo "Removing products for date $ymd (AOI not fully covered)"
            for f in "$slc_dir"/*"${ymd}"T*; do
                rm -rf "$f"
            done
        done < "$ndates_file"
        shopt -u nullglob
    fi
fi
