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
usage: ${SCRIPT_NAME} TEMPLATE [DOLPHIN_CONFIG] [OPTIONS]
       ${SCRIPT_NAME} AOI NAME [DOLPHIN_CONFIG] --flight-dir {asc,desc} [OPTIONS]

Run an ISCE3 SAFE/CSLC/DISP workflow: write configs and run/job files, then submit.
Always pass a MinSAR template or AOI plus project name. Science flags alone are invalid.
Use --start-date/--end-date for dates; --start/--end/--dostep are processing steps.
Leftover --section.option flags go to dolphin config. Use --dolphin-dir, not --work-directory.
Processing steps are [download, dolphin_wrapped, dolphin_unwrap, dolphin_timeseries, dolphin_2_hdfeos5, ingest_insarmaps, disp_s1_process]
Additional steps for data-type safe, disp-S1: create_cslc, reformat_disp respectively
disp_s1_process is written for --data-type cslc but not run by default (manual OPERA produce).
Optional DOLPHIN_CONFIG is a .yaml/.yml or OPERA DISP-S1 .nc (prefers metadata/dolphin_workflow_config).

options:
  -h, --help            show this help
  --data-type TYPE      safe, cslc, or disp-S1 (default: safe)
  --start STEP          first step
  --end STEP, --stop STEP
                        last step, inclusive
  --dostep STEP         run one step only
  --start-date DATE     first date YYYYMMDD (forwarded to the generator)
  --end-date DATE       last date YYYYMMDD
  --flight-dir DIR      asc or desc (required for AOI input)
  --dolphin-dir DIR     Dolphin work directory (default: dolphin, or auto-name from diffs)
  --from-dolphin-dir DIR
                        source DIR for YAML comparison and interferogram inputs (default: dolphin)
  --unwrap-method NAME  shortcut for --unwrap-options.unwrap-method
  --copy-dolphin-inputs copy interferograms/unwrapped instead of symlink
  --preset NAME         auto, standard, dry, wet, arctic, disp-s1 (default: standard)
  --half-window Y X     phase-linking half-window (default from preset; standard 6 12)
  --stride Y X          output strides (default from preset; standard 3 6)
  --backend BACKEND     auto, local, or slurm (default: auto)
  --sleep SECS          sleep seconds before running
  --dry-run             print the generator plan without writing files or submitting
  --no-run              write run/job files without starting run_isce3_workflow.bash

Examples:
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --sleep 30
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --no-run
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --data-type cslc --start download
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --data-type cslc --preset dry --stride 2 4
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --data-type cslc --preset disp-s1
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template dolphin_config.yaml --data-type cslc
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template OPERA_L3_DISP-S1.nc --data-type cslc
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --unwrap-options.run-interpolation true
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --start dolphin_unwrap --unwrap-method whirlwind
  ${SCRIPT_NAME} \$TE/HawaiiPunaSenD87.template --start ingest_insarmaps
  ${SCRIPT_NAME} 19.45:19.5,-154.915:-154.852 HawaiiPuna --flight-dir desc
  ${SCRIPT_NAME} 19.45:19.5,-154.915:-154.852 HawaiiPuna dolphin_config.yaml --flight-dir desc --data-type cslc
  ${SCRIPT_NAME} 19.45:19.5,-154.915:-154.852 HawaiiPuna --flight-dir desc --unwrap-options.run-interpolation true
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

is_consume_one() {
    case "$1" in
        --data-type|--platform|--flight-dir|--start-date|--end-date|--track|--relativeOrbit|--frame-id|--queue|--long-queue|--config|--preset|--burst-count-method|--dolphin-dir|--from-dolphin-dir|--unwrap-method|--ministack-size|--backend|--start|--end|--stop|--dostep|--phase|--max-parallel)
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
        --safe|--cslc|--disp|--disp-S1|--dry-run|--no-dolphin-split|--preset-naming|--no-preset-naming|--copy-dolphin-inputs)
            return 0
            ;;
    esac
    return 1
}

is_download_step() {
    case "$1" in
        download|download_safe|download_cslc|download_disp|create_cslc|reformat_disp|download_create_cslc)
            return 0
            ;;
    esac
    return 1
}

is_science_token() {
    case "$1" in
        --unwrap-method|--dolphin-dir|--from-dolphin-dir|--copy-dolphin-inputs|--ministack-size|--half-window|--stride|--preset)
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
    echo "$banner"
    echo "$line"
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

[[ -f "$GENERATOR" ]] || die "create_isce3_runfiles.py not found: $GENERATOR"
[[ -f "$RUNNER" ]] || die "run_isce3_workflow.bash not found: $RUNNER"

app_start=""
app_end=""
app_dostep=""
backend=""
phase=""
user_phase=false
dry_run=false
no_run=false
has_science=false
explicit_dolphin_dir=false
sleep_time=""
positionals=()
gen_args=()
original_args=("$@")
invoke_dir="$(pwd -P)"

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
        --phase)
            [[ -n "${2:-}" && "$2" != --* ]] || die "$1 requires a value"
            phase="$2"
            user_phase=true
            shift 2
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
        --work-directory|--work-dir)
            die "use --dolphin-dir, not --work-directory"
            ;;
        -?*|--*)
            if is_science_token "$1"; then
                has_science=true
            fi
            if is_flag "$1"; then
                gen_args+=("$1")
                shift
            elif is_consume_two "$1"; then
                [[ -n "${2:-}" && "$2" != --* && -n "${3:-}" && "$3" != --* ]] || die "$1 requires Y X"
                gen_args+=("$1" "$2" "$3")
                shift 3
            elif is_consume_one "$1" || [[ "$1" == --* ]]; then
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

if [[ "$user_phase" != true ]]; then
    if [[ -n "$app_dostep" ]]; then
        if [[ "$app_dostep" =~ ^[0-9]+$ ]]; then
            phase="all"
        elif is_download_step "$app_dostep"; then
            phase="download"
        else
            phase="dolphin"
        fi
    elif [[ -n "$app_start" ]]; then
        if [[ "$app_start" =~ ^[0-9]+$ ]]; then
            phase="all"
        elif is_download_step "$app_start"; then
            phase="download"
        else
            phase="dolphin"
        fi
    elif [[ "$has_science" == true ]]; then
        phase="dolphin"
    else
        phase="all"
    fi
fi

if [[ "$app_start" == "dolphin_wrapped" && "$explicit_dolphin_dir" != true && "$has_science" != true ]]; then
    gen_args+=(--dolphin-dir dolphin)
fi

has_run_stage() {
    local stem="$1"
    local file
    local nullglob_state
    nullglob_state="$(shopt -p nullglob)"
    shopt -s nullglob
    for file in "$work_dir/$ISCE3_RUN_DIR_NAME"/run_[0-9][0-9]_"${stem}"; do
        if [[ -f "$file" ]]; then
            eval "$nullglob_state"
            return 0
        fi
    done
    eval "$nullglob_state"
    return 1
}

if [[ -n "$sleep_time" && "$dry_run" != true ]]; then
    echo "sleeping $sleep_time secs before starting ..."
    sleep "$sleep_time"
fi

echo "Running: create_isce3_runfiles.py ${positionals[*]} ${gen_args[*]} --phase ${phase}"
gen_out="$(mktemp)"
trap 'rm -f "$gen_out"' EXIT
"$GENERATOR" "${positionals[@]}" "${gen_args[@]}" --phase "$phase" | tee "$gen_out"
if resolved="$(project_from_generator_log "$gen_out")"; then
    project="$resolved"
fi
work_dir="${SCRATCHDIR}/${project}"
log_app_command "$invoke_dir" "$work_dir"
echo "Project: \$SCRATCHDIR/${project}"
if [[ "$dry_run" == true ]]; then
    exit 0
fi
if [[ "$no_run" == true ]]; then
    echo "Skipping run_isce3_workflow.bash (--no-run)"
    exit 0
fi

[[ -d "$work_dir/$ISCE3_RUN_DIR_NAME" ]] || die "$ISCE3_RUN_DIR_NAME not found under $work_dir"
cd "$work_dir"

dolphin_dir="dolphin"
layer="wrapped"
if [[ -f "$work_dir/.isce3_run_slice" ]]; then
    dolphin_dir="$(sed -n 's/^dolphin_dir=//p' "$work_dir/.isce3_run_slice" | head -1)"
    layer="$(sed -n 's/^layer=//p' "$work_dir/.isce3_run_slice" | head -1)"
fi
dolphin_dir="${dolphin_dir:-dolphin}"
layer="${layer:-wrapped}"
if [[ "$phase" != "download" ]]; then
    echo "Dolphin dir: ${dolphin_dir}"
fi

run_args=()
[[ -n "$backend" ]] && run_args+=(--backend "$backend")

if [[ -n "$app_dostep" ]]; then
    run_args+=(--dostep "$app_dostep")
elif [[ -n "$app_start" ]]; then
    run_args+=(--start "$app_start")
    if [[ -n "$app_end" ]]; then
        run_args+=(--end "$app_end")
    elif is_download_step "$app_start"; then
        run_args+=(--end download)
    else
        run_args+=(--end ingest_insarmaps)
    fi
elif [[ "$phase" == "download" ]]; then
    run_args+=(--start download --end download)
elif [[ "$phase" == "dolphin" ]]; then
    start_from="$app_start"
    if [[ -z "$start_from" ]]; then
        case "$layer" in
            unwrap) start_from="dolphin_unwrap" ;;
            timeseries) start_from="dolphin_timeseries" ;;
            *) start_from="dolphin_wrapped" ;;
        esac
        if ! has_run_stage "$start_from" && has_run_stage dolphin; then
            start_from="dolphin"
        fi
        if has_run_stage dolphin_2_hdfeos5 && ! has_run_stage dolphin_wrapped && ! has_run_stage dolphin; then
            start_from="dolphin_2_hdfeos5"
        fi
    fi
    run_args+=(--start "$start_from" --end ingest_insarmaps)
else
    run_args+=(--start download --end ingest_insarmaps)
fi

echo "Running: run_isce3_workflow.bash ${ISCE3_RUN_DIR_NAME} ${run_args[*]}"
write_log_line "$(date +"%Y%m%d:%H-%M") * run_isce3_workflow.bash ${ISCE3_RUN_DIR_NAME} ${run_args[*]}" "$invoke_dir" "$work_dir"
exec "$RUNNER" "$ISCE3_RUN_DIR_NAME" "${run_args[@]}"
