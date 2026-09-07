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
single-run steps: [download, dolphin_wrapped, dolphin_unwrap, dolphin_timeseries, dolphin_2_hdfeos5, ingest_insarmaps]
opera steps: [download, disp_s1_process, reformat_disp, dolphin_2_hdfeos5, ingest_insarmaps]
Additional step for data-type safe: create_cslc. For disp-s1: reformat_disp
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
  --copy-dolphin-inputs copy interferograms/unwrapped instead of symlink
  --half-window Y X     phase-linking half-window or from --half-window-preset (Default: 6 12)
  --stride Y X          output strides (Default: 3 6)
  --half-window-preset {standard,dry,wet,arctic}
                        phase-linking half-window: standard 6x12, dry 5x11, wet 9x18, arctic 9x19 (Default: standard)
  --dolphin-mode MODE   {single-run,opera} (one Dolphin stack or local DISP-S1) (Default: single-run)
  --reference-method METHOD
                        disp-s1-reformat reference: NONE, POINT, MEDIAN, BORDER, HIGH_COHERENCE (Default: HIGH_COHERENCE)
  --backend BACKEND     auto, local, or slurm (Default: auto)
  --sleep SECS          sleep seconds before running
  --dry-run             print the generator plan without writing files or submitting
  --no-run              write run/job files without starting run_isce3_workflow.bash

Examples:
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type disp-s1 --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --start-date 20220101 --end-date 20241212
  ${SCRIPT_NAME} 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --half-window 6 12 --stride 3 6 --start-date 20220101 --end-date 20241212
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
        --data-type|--platform|--flight-dir|--start-date|--end-date|--track|--relativeOrbit|--frame-id|--queue|--long-queue|--config|--half-window-preset|--burst-count-method|--dolphin-dir|--from-dolphin-dir|--unwrap-method|--ministack-size|--dolphin-mode|--reference-method|--backend|--max-parallel)
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
        --safe|--cslc|--disp-S1|--dry-run|--no-dolphin-split|--preset-naming|--no-preset-naming|--copy-dolphin-inputs)
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

is_opera_dolphin_mode() {
    [[ "${dolphin_mode:-single-run}" == "opera" ]]
}

is_science_token() {
    case "$1" in
        --unwrap-method|--dolphin-dir|--from-dolphin-dir|--copy-dolphin-inputs|--ministack-size|--half-window|--stride|--half-window-preset|--dolphin-mode)
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
gen_phase=""
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
        --preset|--window-preset)
            die "use --half-window-preset, not $1"
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

if [[ -n "$app_dostep" ]]; then
    if [[ "$app_dostep" =~ ^[0-9]+$ ]]; then
        gen_phase="all"
    elif is_download_step "$app_dostep"; then
        gen_phase="download"
    else
        gen_phase="dolphin"
    fi
elif [[ -n "$app_start" ]]; then
    if [[ "$app_start" =~ ^[0-9]+$ ]]; then
        gen_phase="all"
    elif is_download_step "$app_start"; then
        gen_phase="download"
    else
        gen_phase="dolphin"
    fi
else
    gen_phase="all"
fi

if [[ "$app_start" == "dolphin_wrapped" && "$explicit_dolphin_dir" != true && "$has_science" != true ]]; then
    gen_args+=(--dolphin-dir dolphin)
fi

if [[ -n "$sleep_time" && "$dry_run" != true ]]; then
    echo "sleeping $sleep_time secs before starting ..."
    sleep "$sleep_time"
fi

echo "Running: create_isce3_runfiles.py ${positionals[*]} ${gen_args[*]} --phase ${gen_phase}"
gen_out="$(mktemp)"
trap 'rm -f "$gen_out"' EXIT
"$GENERATOR" "${positionals[@]}" "${gen_args[@]}" --phase "$gen_phase" | tee "$gen_out"
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
dolphin_mode="single-run"
if [[ -f "$work_dir/.isce3_run_slice" ]]; then
    dolphin_dir="$(sed -n 's/^dolphin_dir=//p' "$work_dir/.isce3_run_slice" | head -1)"
    dolphin_mode="$(sed -n 's/^dolphin_mode=//p' "$work_dir/.isce3_run_slice" | head -1)"
fi
dolphin_dir="${dolphin_dir:-dolphin}"
dolphin_mode="${dolphin_mode:-single-run}"
if [[ "$gen_phase" != "download" ]]; then
    echo "Dolphin dir: ${dolphin_dir}"
    if is_opera_dolphin_mode; then
        echo "Dolphin mode: opera"
    fi
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
else
    run_args+=(--start download --end ingest_insarmaps)
fi

echo "Running: run_isce3_workflow.bash ${ISCE3_RUN_DIR_NAME} ${run_args[*]}"
write_log_line "$(date +"%Y%m%d:%H-%M") * run_isce3_workflow.bash ${ISCE3_RUN_DIR_NAME} ${run_args[*]}" "$invoke_dir" "$work_dir"
exec "$RUNNER" "$ISCE3_RUN_DIR_NAME" "${run_args[@]}"
