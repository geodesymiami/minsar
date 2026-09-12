#!/usr/bin/env bash
# Identify a dataset (template or AOI+name), write ISCE3 run/job files, then submit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
export MINSAR_HOME="${MINSAR_HOME:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GENERATOR="${MINSAR_HOME}/minsar/src/minsar/cli/create_isce3_runfiles.py"
RUNNER="${MINSAR_HOME}/minsar/src/minsar/cli/run_isce3_workflow.bash"
ISCE3_RUN_DIR_NAME="run_files_isce3"

print_help() {
    cat <<EOF
usage: ${SCRIPT_NAME} TEMPLATE [OPTIONS]
       ${SCRIPT_NAME} AOI NAME --flight-dir {asc,desc} [OPTIONS]

Run an ISCE3 SAFE/CSLC/DISP workflow. Use --start --end --dostep for processing steps.
single-run steps: [download, dolphin_wrapped, dolphin_unwrap, dolphin_timeseries, dolphin_2_hdfeos5, ingest_insarmaps, upload]
opera steps: [download, disp_s1_process, reformat_disp, dolphin_2_hdfeos5, ingest_insarmaps, upload]
Additional step for data-type safe: create_cslc. For disp-s1: reformat_disp
Template or project names that contain SAFE, CSLC, or DISPS1/DISP (and Opera) set --data-type and --dolphin-mode when those flags are omitted.
Aliases: download, dolphin, hdfeos5, ingest, dolphin2hdfeos5. Hyphens and run_NN_ prefixes are accepted (dolphin-2-hdfeos5, run_04_dolphin_2_hdfeos5).
upload is its own step (he5 and insarmaps.log). A full run includes it. --dostep stops at that step and does not upload.
--dostep upload uploads existing products and prints the last new insarmaps.log line, same as minsarApp.bash.
Supports dolphin config from config.yaml or OPERA_DISP-S1.nc (uses metadata/dolphin_workflow_config).
Additional --section.option flags go to dolphin config.

options:
  -h, --help            show this help
  --data-type TYPE      safe, cslc, or disp-s1 (Default: safe)
  --start STEP          first step
  --end STEP, --stop STEP
                        last step, inclusive
  --dostep STEP         run one step only
  --start-date DATE     first date YYYYMMDD
  --end-date DATE       last date YYYYMMDD
  --flight-dir DIR      asc or desc
  --dolphin-dir DIR     work directory (Default: dolphin, or auto-name from diffs)
  --unwrap-method NAME  shortcut for --unwrap-options.unwrap-method (Default: snaphu)
  --half-window Y X     phase-linking half-window or from --half-window-preset (Default: 6 12)
  --stride Y X          output strides (Default: 3 6)
  --half-window-preset {standard,dry,wet,arctic}
                        phase-linking half-window: standard 6x12, dry 5x11, wet 9x18, arctic 9x19 (Default: standard)
  --dolphin-mode MODE   {single-run,opera} (one Dolphin stack or local DISP-S1; not for disp-s1) (Default: single-run)
  --reference-method METHOD
                        disp-s1-reformat reference: NONE, POINT, MEDIAN, BORDER, HIGH_COHERENCE (Default: HIGH_COHERENCE)
  --backend BACKEND     auto, local, or slurm (Default: auto)
  --max-parallel N      override local launcher PPN (default: LAUNCHER_PPN from the job file)
  --sleep SECS          sleep seconds before running
  --dry-run             print the generator plan without writing files or submitting
  --no-run              write run/job files without starting run_isce3_workflow.bash

Examples:
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20220331
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type safe --start-date 20220101 --end-date 20220331
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type safe --start-date 20220101 --end-date 20220331 --backend local --max-parallel 12
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type disp-s1 --start-date 20220101 --end-date 20230331
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --start-date 20220101 --end-date 20220331
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --stride 2 4 --half-window 6 12  --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --half-window-preset dry --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --reference-method BORDER --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna dolphin_config.yaml --flight-dir desc --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna OPERA_L3_DISP-S1.nc --flight-dir desc --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --start-date 20170101 --end-date 20211231
  ${SCRIPT_NAME} 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type cslc --start-date 20170101 --end-date 20211231
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

is_consume_one() {
    case "$1" in
        --data-type|--platform|--flight-dir|--start-date|--end-date|--track|--relativeOrbit|--frame-id|--queue|--long-queue|--config|--half-window-preset|--burst-count-method|--dolphin-dir|--from-dolphin-dir|--unwrap-method|--ministack-size|--dolphin-mode|--reference-method|--backend)
            return 0
            ;;
    esac
    [[ "$1" == --*.* ]] && return 0
    return 1
}

is_consume_two() {
    case "$1" in
        --half-window|--stride)
            return 0
            ;;
    esac
    return 1
}

is_flag() {
    case "$1" in
        --safe|--cslc|--disp-S1|--dry-run|--no-dolphin-split|--preset-naming|--no-preset-naming)
            return 0
            ;;
    esac
    return 1
}

is_download_range_start() {
    case "$1" in
        download|download_safe|download_cslc|download_disp|create_cslc|download_create_cslc)
            return 0
            ;;
    esac
    return 1
}

normalize_step() {
    local step="$1"
    step="${step%.job}"
    if [[ "$step" =~ ^run_[0-9][0-9]_(.+)$ ]]; then
        step="${BASH_REMATCH[1]}"
    fi
    step="${step//-/_}"
    case "$step" in
        dolphin2hdfeos5) step="dolphin_2_hdfeos5" ;;
    esac
    printf '%s\n' "$step"
}

infer_dataset_from_name() {
    local name="$1"
    local lower prefix_len
    name="${name##*/}"
    name="${name%.template}"
    lower="${name,,}"
    inferred_data_type=""
    inferred_dolphin_mode=""
    if [[ "$lower" =~ ^(.+)(sen|s1|tsx|alos2|csk|rs2|env|nisar)[ad][0-9]+$ ]]; then
        prefix_len="${#BASH_REMATCH[1]}"
        name="${name:0:prefix_len}"
        lower="${name,,}"
    fi
    if [[ "$lower" == *opera ]]; then
        inferred_dolphin_mode="opera"
        name="${name:0:${#name}-5}"
        lower="${name,,}"
    elif [[ "$lower" == *standard ]]; then
        inferred_dolphin_mode="single-run"
        name="${name:0:${#name}-8}"
        lower="${name,,}"
    fi
    if [[ "$lower" == *disps1 ]]; then
        inferred_data_type="disp-s1"
        inferred_dolphin_mode=""
    elif [[ "$lower" == *cslc ]]; then
        inferred_data_type="cslc"
    elif [[ "$lower" == *safe ]]; then
        inferred_data_type="safe"
    elif [[ "$lower" == *disp ]]; then
        inferred_data_type="disp-s1"
        inferred_dolphin_mode=""
    else
        inferred_data_type=""
        inferred_dolphin_mode=""
    fi
}

cli_dataset_from_gen_args() {
    local i=0
    cli_data_type=""
    cli_dolphin_mode=""
    while [[ "$i" -lt "${#gen_args[@]}" ]]; do
        case "${gen_args[$i]}" in
            --data-type)
                cli_data_type="${gen_args[$((i + 1))]:-}"
                ;;
            --safe)
                cli_data_type="safe"
                ;;
            --cslc)
                cli_data_type="cslc"
                ;;
            --disp-S1)
                cli_data_type="disp-s1"
                ;;
            --dolphin-mode)
                cli_dolphin_mode="${gen_args[$((i + 1))]:-}"
                ;;
        esac
        i=$((i + 1))
    done
    case "${cli_data_type,,}" in
        disp|disp-s1|disp_s1) cli_data_type="disp-s1" ;;
    esac
}

resolve_dataset() {
    local run_dir="$work_dir/$ISCE3_RUN_DIR_NAME"
    infer_dataset_from_name "$project"
    if [[ -z "$inferred_dolphin_mode" && "$inferred_data_type" != "disp-s1" && -f "$work_dir/.isce3_run_slice" ]]; then
        inferred_dolphin_mode="$(sed -n 's/^dolphin_mode=//p' "$work_dir/.isce3_run_slice" | head -1)"
    fi
    if [[ -z "$inferred_data_type" && -d "$run_dir" ]]; then
        if [[ -f "$run_dir/run_01_download_cslc" ]] || compgen -G "$run_dir/run_*_download_cslc" >/dev/null; then
            inferred_data_type="cslc"
        elif [[ -f "$run_dir/run_01_download_safe" ]] || compgen -G "$run_dir/run_*_download_safe" >/dev/null; then
            inferred_data_type="safe"
        elif [[ -f "$run_dir/run_01_download_disp" ]] || compgen -G "$run_dir/run_*_download_disp" >/dev/null; then
            inferred_data_type="disp-s1"
        fi
    fi
    if [[ -z "$inferred_dolphin_mode" && "$inferred_data_type" != "disp-s1" && -d "$run_dir" ]] \
        && compgen -G "$run_dir/run_*_disp_s1_process" >/dev/null; then
        inferred_dolphin_mode="opera"
    fi
    cli_dataset_from_gen_args
    final_data_type="${cli_data_type:-${inferred_data_type:-safe}}"
    final_dolphin_mode="${cli_dolphin_mode:-${inferred_dolphin_mode:-single-run}}"
    case "${final_data_type,,}" in
        disp|disp-s1|disp_s1)
            final_data_type="disp-s1"
            final_dolphin_mode=""
            ;;
    esac
    dataset_notes=()
    if [[ -z "$cli_data_type" && -n "$inferred_data_type" ]]; then
        dataset_notes+=("--data-type $inferred_data_type")
    fi
    if [[ -z "$cli_dolphin_mode" && -n "$inferred_dolphin_mode" && "$final_data_type" != "disp-s1" ]]; then
        dataset_notes+=("--dolphin-mode $inferred_dolphin_mode")
    fi
}

steps_for_dataset() {
    local mode="${final_dolphin_mode:-single-run}"
    case "$final_data_type" in
        disp-s1)
            printf '%s\n' "download download_disp reformat_disp dolphin_2_hdfeos5 ingest_insarmaps upload hdfeos5 ingest"
            ;;
        cslc)
            if [[ "$mode" == "opera" ]]; then
                printf '%s\n' "download download_cslc disp_s1_process reformat_disp dolphin_2_hdfeos5 ingest_insarmaps upload dolphin hdfeos5 ingest"
            else
                printf '%s\n' "download download_cslc dolphin dolphin_wrapped dolphin_unwrap dolphin_timeseries dolphin_2_hdfeos5 ingest_insarmaps upload hdfeos5 ingest"
            fi
            ;;
        *)
            if [[ "$mode" == "opera" ]]; then
                printf '%s\n' "download download_create_cslc download_safe create_cslc disp_s1_process reformat_disp dolphin_2_hdfeos5 ingest_insarmaps upload dolphin hdfeos5 ingest"
            else
                printf '%s\n' "download download_create_cslc download_safe create_cslc dolphin dolphin_wrapped dolphin_unwrap dolphin_timeseries dolphin_2_hdfeos5 ingest_insarmaps upload hdfeos5 ingest"
            fi
            ;;
    esac
}

require_known_step() {
    local step="$1"
    local label="$2"
    local known
    [[ -n "$step" ]] || return 0
    [[ "$step" =~ ^[0-9]+$ ]] && return 0
    known=" $(steps_for_dataset) "
    if [[ "$known" != *" $step "* ]]; then
        die "$label $step is not a step for data-type ${final_data_type}${final_dolphin_mode:+ --dolphin-mode ${final_dolphin_mode}}. Steps: $(steps_for_dataset)"
    fi
}

run_includes_upload() {
    if [[ -n "$app_dostep" ]]; then
        [[ "$app_dostep" == "upload" ]]
        return
    fi
    if [[ -z "$app_start" && -z "$app_end" ]]; then
        return 0
    fi
    if [[ -n "$app_end" ]]; then
        [[ "$app_end" == "upload" ]]
        return
    fi
    if is_download_range_start "$app_start"; then
        return 1
    fi
    return 0
}

run_is_upload_only() {
    if [[ "$app_dostep" == "upload" ]]; then
        return 0
    fi
    if [[ -z "$app_dostep" && "$app_start" == "upload" && ( -z "$app_end" || "$app_end" == "upload" ) ]]; then
        return 0
    fi
    return 1
}

finish_upload_if_requested() {
    run_includes_upload || return 0
    upload_isce3_he5
    local -a product_files=()
    local line log_file=""
    while IFS= read -r line; do
        [[ -n "$line" ]] && product_files+=("$line")
    done < <(find_isce3_he5_files || true)
    if [[ ${#product_files[@]} -gt 0 ]]; then
        log_file="$(find_isce3_insarmaps_log "${product_files[@]}" || true)"
    else
        log_file="$(find_isce3_insarmaps_log || true)"
    fi
    print_new_insarmaps_log_line "$log_file"
}

build_gen_step_args() {
    gen_step_args=()
    if run_is_upload_only; then
        return 0
    fi
    if [[ -n "$app_dostep" ]]; then
        gen_step_args+=(--dostep "$app_dostep")
    elif [[ -n "$app_start" || -n "$app_end" ]]; then
        [[ -n "$app_start" ]] && gen_step_args+=(--start "$app_start")
        if [[ -n "$app_end" && "$app_end" != "upload" ]]; then
            gen_step_args+=(--end "$app_end")
        elif [[ -n "$app_start" ]] && is_download_range_start "$app_start"; then
            gen_step_args+=(--end download)
        fi
    fi
}

filter_gen_args_for_steps() {
    [[ ${#gen_args[@]} -gt 0 ]] || return 0
    local -a filtered=()
    local line
    while IFS= read -r line; do
        [[ -n "$line" ]] && filtered+=("$line")
    done < <(
        PYTHONPATH="$MINSAR_HOME" python3 - "$final_data_type" "${final_dolphin_mode:-single-run}" "$explicit_data_type" "$explicit_dolphin_mode" "$app_dostep" "$app_start" "$app_end" "${gen_args[@]}" <<'PY'
import sys
from minsar.utils.isce3_steps import filter_generator_argv

data_type, dolphin_mode, explicit_data_type, explicit_dolphin_mode, dostep, step_start, step_end, *argv = sys.argv[1:]
out = filter_generator_argv(
    argv,
    data_type=data_type,
    dolphin_mode=dolphin_mode or "single-run",
    dostep=dostep or None,
    start=step_start or None,
    end=step_end or None,
    explicit_data_type=explicit_data_type == "true",
    explicit_dolphin_mode=explicit_dolphin_mode == "true",
)
for item in out:
    print(item)
PY
    )
    gen_args=("${filtered[@]}")
}

is_science_token() {
    case "$1" in
        --unwrap-method|--dolphin-dir|--from-dolphin-dir|--ministack-size|--half-window|--stride|--half-window-preset|--dolphin-mode)
            return 0
            ;;
    esac
    [[ "$1" == --*.* ]] && return 0
    return 1
}

project_from_generator_log() {
    local line rest
    line="$(grep -E '^Project:' "$1" | tail -1)" || return 1
    rest="${line#Project:}"
    rest="${rest#"${rest%%[![:space:]]*}"}"
    rest="${rest#\$SCRATCHDIR/}"
    if [[ -n "${SCRATCHDIR:-}" && "$rest" == "$SCRATCHDIR"/* ]]; then
        rest="${rest#"$SCRATCHDIR"/}"
    fi
    rest="${rest%/}"
    [[ -n "$rest" ]] || return 1
    printf '%s\n' "$rest"
}

log_app_command() {
    local echo_stdout=true
    if [[ "${1:-}" == "--file-only" ]]; then
        echo_stdout=false
        shift
    fi
    local dests=("$@")
    local arg
    local simplified_args=()
    local banner line dest real seen_real
    local -a seen=()
    for arg in "${original_args[@]}"; do
        if [[ -n "${SCRATCHDIR:-}" && "$arg" == "$SCRATCHDIR"* ]]; then
            simplified_args+=("\$SCRATCHDIR${arg#$SCRATCHDIR}")
        elif [[ -n "${SAMPLESDIR:-}" && "$arg" == "$SAMPLESDIR"* ]]; then
            simplified_args+=("\$SAMPLESDIR${arg#$SAMPLESDIR}")
        elif [[ -n "${TE:-}" && "$arg" == "$TE"* ]]; then
            simplified_args+=("\$TE${arg#$TE}")
        elif [[ -n "${TEMPLATES:-}" && "$arg" == "$TEMPLATES"* ]]; then
            simplified_args+=("\$TE${arg#$TEMPLATES}")
        else
            simplified_args+=("$arg")
        fi
    done
    banner="#############################################################################################"
    line="$(date +"%Y%m%d:%H-%M") * ${SCRIPT_NAME} ${simplified_args[*]}"
    if [[ "$echo_stdout" == true ]]; then
        echo "$banner"
        echo "$line"
    fi
    for dest in "${dests[@]}"; do
        mkdir -p "$dest"
        real="$(cd "$dest" && pwd -P)"
        seen_real=false
        if ((${#seen[@]} > 0)); then
            for seen_path in "${seen[@]}"; do
                if [[ "$seen_path" == "$real" ]]; then
                    seen_real=true
                    break
                fi
            done
        fi
        [[ "$seen_real" == true ]] && continue
        seen+=("$real")
        echo "$banner" >> "${real}/log"
        echo "$line" >> "${real}/log"
    done
}

write_log_line() {
    local line="$1"
    shift
    local dest real seen_real
    local -a seen=()
    for dest in "$@"; do
        mkdir -p "$dest"
        real="$(cd "$dest" && pwd -P)"
        seen_real=false
        if ((${#seen[@]} > 0)); then
            for seen_path in "${seen[@]}"; do
                if [[ "$seen_path" == "$real" ]]; then
                    seen_real=true
                    break
                fi
            done
        fi
        [[ "$seen_real" == true ]] && continue
        seen+=("$real")
        echo "$line" >> "${real}/log"
    done
}

isce3_he5_search_dir() {
    local mode dir
    mode="${dolphin_mode:-single-run}"
    if [[ "$mode" == "opera" ]] || compgen -G "$work_dir/$ISCE3_RUN_DIR_NAME/run_*_download_disp*" >/dev/null; then
        printf '%s\n' "."
        return 0
    fi
    dir="$(sed -n 's/^dolphin_dir=//p' "$work_dir/.isce3_run_slice" 2>/dev/null | head -1)"
    dir="${dir:-dolphin}"
    printf '%s\n' "${dir}/timeseries"
}

find_isce3_he5_files() {
    local search_dir abs_dir file rel
    local -a matches=()
    local old_nullglob
    search_dir="$(isce3_he5_search_dir)"
    if [[ "$search_dir" == "." ]]; then
        abs_dir="$work_dir"
    else
        abs_dir="$work_dir/$search_dir"
    fi
    [[ -d "$abs_dir" ]] || return 1
    old_nullglob="$(shopt -p nullglob)"
    shopt -s nullglob
    matches=("$abs_dir"/S1*.he5)
    if [[ ${#matches[@]} -eq 0 ]]; then
        matches=("$abs_dir"/*.he5)
    fi
    eval "$old_nullglob"
    [[ ${#matches[@]} -gt 0 ]] || return 1
    for file in "${matches[@]}"; do
        rel="${file#"$work_dir"/}"
        printf '%s\n' "$rel"
    done
}

file_mtime_epoch() {
    local path="$1"
    if stat -c %Y "$path" >/dev/null 2>&1; then
        stat -c %Y "$path"
    else
        stat -f %m "$path"
    fi
}

find_isce3_insarmaps_log() {
    local he5 dir candidate
    for he5 in "$@"; do
        dir="$(dirname "$he5")"
        for candidate in "$dir/insarmaps.log" "$dir/pic/insarmaps.log"; do
            if [[ -f "$candidate" ]]; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done
    done
    if [[ -f insarmaps.log ]]; then
        printf '%s\n' insarmaps.log
        return 0
    fi
    if [[ -f pic/insarmaps.log ]]; then
        printf '%s\n' pic/insarmaps.log
        return 0
    fi
    return 1
}

print_new_insarmaps_log_line() {
    local log_file="$1"
    local since="${2:-${MINSAR_RUN_START_EPOCH:-}}"
    local mtime line
    [[ -n "$log_file" && -f "$log_file" ]] || return 0
    if [[ -n "$since" ]]; then
        mtime="$(file_mtime_epoch "$log_file" 2>/dev/null || echo 0)"
        [[ "$mtime" -gt "$since" ]] || return 0
    fi
    line="$(tail -n 1 "$log_file")"
    [[ -n "${line//[[:space:]]/}" ]] || return 0
    echo "insarmaps.log:"
    echo "$line"
    echo
}

upload_isce3_he5() {
    local -a he5_files=() upload_args=()
    local line log_file
    while IFS= read -r line; do
        [[ -n "$line" ]] && he5_files+=("$line")
    done < <(find_isce3_he5_files || true)
    if [[ ${#he5_files[@]} -eq 0 ]]; then
        echo "No .he5 product found; skip upload_data_products.py"
        return 0
    fi
    upload_args=("${he5_files[@]}")
    log_file="$(find_isce3_insarmaps_log "${he5_files[@]}" || true)"
    if [[ -n "$log_file" && -f "$log_file" ]]; then
        local he5 he5_dir dest
        for he5 in "${he5_files[@]}"; do
            he5_dir="$(dirname "$he5")"
            dest="$he5_dir/insarmaps.log"
            if [[ ! -f "$dest" ]]; then
                cp -p "$log_file" "$dest"
            fi
            if [[ -f "$dest" ]]; then
                upload_args+=("$dest")
            fi
        done
        upload_args+=("$log_file")
    fi
    # Same log path can be added once per he5 and again from the project root.
    if [[ ${#upload_args[@]} -gt 1 ]]; then
        local -a unique_args=()
        local seen_arg="" arg already
        for arg in "${upload_args[@]}"; do
            already=false
            if [[ ${#unique_args[@]} -gt 0 ]]; then
                for seen_arg in "${unique_args[@]}"; do
                    if [[ "$seen_arg" == "$arg" ]]; then
                        already=true
                        break
                    fi
                done
            fi
            [[ "$already" == true ]] && continue
            unique_args+=("$arg")
        done
        upload_args=("${unique_args[@]}")
    fi
    echo "Running: upload_data_products.py ${upload_args[*]}"
    write_log_line "$(date +"%Y%m%d:%H-%M") * upload_data_products.py ${upload_args[*]}" "$invoke_dir" "$work_dir"
    upload_data_products.py "${upload_args[@]}"
}

[[ -f "$GENERATOR" ]] || die "create_isce3_runfiles.py not found: $GENERATOR"
[[ -f "$RUNNER" ]] || die "run_isce3_workflow.bash not found: $RUNNER"

app_start=""
app_end=""
app_dostep=""
backend=""
max_parallel=""
dry_run=false
no_run=false
has_science=false
explicit_dolphin_dir=false
explicit_data_type=false
explicit_dolphin_mode=false
sleep_time=""
positionals=()
gen_args=()
gen_step_args=()
original_args=("$@")
invoke_dir="$(pwd -P)"
export MINSAR_RUN_START_EPOCH="${MINSAR_RUN_START_EPOCH:-$(date +%s)}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --start)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            app_start="$2"
            shift 2
            ;;
        --end|--stop)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            app_end="$2"
            shift 2
            ;;
        --dostep)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            app_dostep="$2"
            shift 2
            ;;
        --backend)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            backend="$2"
            shift 2
            ;;
        --max-parallel)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            [[ "$2" =~ ^[1-9][0-9]*$ ]] || die "$1 must be a positive integer"
            max_parallel="$2"
            shift 2
            ;;
        --phase)
            die "do not pass --phase; omit --start/--dostep for all run files, or pass --start/--dostep to limit generation and execution"
            ;;
        --dolphin-dir)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            explicit_dolphin_dir=true
            has_science=true
            gen_args+=("$1" "$2")
            shift 2
            ;;
        --sleep)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            [[ "$2" =~ ^[0-9]+$ ]] || die "$1 must be a non-negative integer"
            sleep_time="$2"
            shift 2
            ;;
        --dry-run)
            dry_run=true
            gen_args+=("$1")
            shift
            ;;
        --no-run)
            no_run=true
            shift
            ;;
        --run)
            die "do not pass --run; ${SCRIPT_NAME} submits via run_isce3_workflow.bash"
            ;;
        --disp)
            die "use --disp-S1 or --data-type disp-s1, not --disp"
            ;;
        --dataset|--dataset=*)
            die "use --data-type, not --dataset"
            ;;
        --preset|--window-preset)
            die "use --half-window-preset, not $1"
            ;;
        --copy-dolphin-inputs)
            die "removed --copy-dolphin-inputs; inputs are always symlinked"
            ;;
        --work-directory|--work-dir)
            die "use --dolphin-dir, not --work-directory"
            ;;
        -?*|--*)
            if is_science_token "$1"; then
                has_science=true
            fi
            if is_flag "$1"; then
                case "$1" in
                    --safe|--cslc|--disp-S1)
                        explicit_data_type=true
                        ;;
                esac
                gen_args+=("$1")
                shift
            elif is_consume_two "$1"; then
                [[ -n "${2:-}" && "$2" != --* && -n "${3:-}" && "$3" != --* ]] || die "$1 requires Y X"
                gen_args+=("$1" "$2" "$3")
                shift 3
            elif is_consume_one "$1"; then
                case "$1" in
                    --data-type|--safe|--cslc|--disp-S1)
                        explicit_data_type=true
                        ;;
                    --dolphin-mode)
                        explicit_dolphin_mode=true
                        ;;
                esac
                if [[ -n "${2:-}" && "$2" != --* ]]; then
                    gen_args+=("$1" "$2")
                    shift 2
                else
                    gen_args+=("$1")
                    shift
                fi
            else
                die "unknown option: $1"
            fi
            ;;
        *)
            positionals+=("$1")
            shift
            ;;
    esac
done

[[ "${#positionals[@]}" -ge 1 ]] || die "pass a MinSAR template or AOI plus project name"
if [[ -n "$app_dostep" && ( -n "$app_start" || -n "$app_end" ) ]]; then
    die "--dostep cannot be combined with --start or --end"
fi
[[ -n "$app_dostep" ]] && app_dostep="$(normalize_step "$app_dostep")"
[[ -n "$app_start" ]] && app_start="$(normalize_step "$app_start")"
[[ -n "$app_end" ]] && app_end="$(normalize_step "$app_end")"

is_dolphin_config_positional() {
    case "$1" in
        *.yaml|*.yml|*.nc|*.YAML|*.YML|*.NC)
            return 0
            ;;
    esac
    return 1
}

if [[ "${#positionals[@]}" -eq 1 ]]; then
    template="${positionals[0]}"
    if [[ ! -f "$template" && "$template" != *.template ]]; then
        die "AOI input requires a project NAME (and --flight-dir)"
    fi
    project="$(basename "$template" .template)"
elif [[ "${#positionals[@]}" -eq 2 ]] && is_dolphin_config_positional "${positionals[1]}"; then
    template="${positionals[0]}"
    if [[ ! -f "$template" && "$template" != *.template ]]; then
        die "AOI input requires a project NAME before dolphin config"
    fi
    project="$(basename "$template" .template)"
else
    project="${positionals[1]}"
fi
[[ -n "${SCRATCHDIR:-}" ]] || die "SCRATCHDIR is not set; source setup/environment.bash"
work_dir="${SCRATCHDIR}/${project}"
log_app_command "$invoke_dir"
resolve_dataset
require_known_step "$app_dostep" "--dostep"
require_known_step "$app_start" "--start"
require_known_step "$app_end" "--end"
if [[ ${#dataset_notes[@]} -gt 0 ]]; then
    echo "Inferred ${dataset_notes[*]} from ${project}"
fi

build_gen_step_args
filter_gen_args_for_steps

if [[ "$app_start" == "dolphin_wrapped" && "$explicit_dolphin_dir" != true && "$has_science" != true ]]; then
    gen_args+=(--dolphin-dir dolphin)
    filter_gen_args_for_steps
fi

if [[ -n "$sleep_time" && "$dry_run" != true ]]; then
    echo "sleeping $sleep_time secs before starting ..."
    sleep "$sleep_time"
fi

if run_is_upload_only; then
    echo "Skipping create_isce3_runfiles.py (upload only)"
    [[ -d "$work_dir" ]] || die "project not found: $work_dir (run processing before --dostep upload)"
else
    echo "Running: create_isce3_runfiles.py ${positionals[*]} ${gen_args[*]} ${gen_step_args[*]}"
    gen_out="$(mktemp)"
    trap 'rm -f "$gen_out"' EXIT
    PYTHONUNBUFFERED=1 "$GENERATOR" "${positionals[@]}" "${gen_args[@]}" "${gen_step_args[@]}" 2>&1 | tee "$gen_out"
    if resolved="$(project_from_generator_log "$gen_out")"; then
        project="$resolved"
    fi
    work_dir="${SCRATCHDIR}/${project}"
    mkdir -p "$work_dir"
fi
if [[ "$(cd "$work_dir" && pwd -P)" != "$invoke_dir" ]]; then
    log_app_command --file-only "$work_dir"
fi
if [[ "$dry_run" == true ]]; then
    if run_is_upload_only; then
        echo "Skipping run_isce3_workflow.bash (upload only)"
    elif run_includes_upload; then
        echo "Workflow run will be followed by upload"
    else
        echo "Workflow run stops before upload"
    fi
    exit 0
fi
if [[ "$no_run" == true ]]; then
    echo "Skipping run_isce3_workflow.bash (--no-run)"
    exit 0
fi

cd "$work_dir"

dolphin_mode="single-run"
if [[ -f "$work_dir/.isce3_run_slice" ]]; then
    dolphin_mode="$(sed -n 's/^dolphin_mode=//p' "$work_dir/.isce3_run_slice" | head -1)"
fi
dolphin_mode="${dolphin_mode:-single-run}"

run_args=()
[[ -n "$backend" ]] && run_args+=(--backend "$backend")
[[ -n "$max_parallel" ]] && run_args+=(--max-parallel "$max_parallel")

if run_is_upload_only; then
    echo "Skipping run_isce3_workflow.bash (upload only)"
else
    [[ -d "$work_dir/$ISCE3_RUN_DIR_NAME" ]] || die "$ISCE3_RUN_DIR_NAME not found under $work_dir"
    if [[ -n "$app_dostep" ]]; then
        run_args+=(--dostep "$app_dostep")
    elif [[ -n "$app_start" ]]; then
        run_args+=(--start "$app_start")
        if [[ -n "$app_end" && "$app_end" != "upload" ]]; then
            run_args+=(--end "$app_end")
        elif is_download_range_start "$app_start"; then
            run_args+=(--end download)
        else
            run_args+=(--end ingest_insarmaps)
        fi
    else
        run_args+=(--start download --end ingest_insarmaps)
    fi
    echo "Running: run_isce3_workflow.bash ${ISCE3_RUN_DIR_NAME} ${run_args[*]}"
    write_log_line "$(date +"%Y%m%d:%H-%M") * run_isce3_workflow.bash ${ISCE3_RUN_DIR_NAME} ${run_args[*]}" "$invoke_dir" "$work_dir"
    "$RUNNER" "$ISCE3_RUN_DIR_NAME" "${run_args[@]}"
fi
finish_upload_if_requested
