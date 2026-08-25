#!/usr/bin/env bash
# Run generated ISCE3 workflow files locally or submit their SLURM jobs.

set -o pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MINSAR_HOME="${MINSAR_HOME:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
MINSAR_UTILS="${MINSAR_HOME}/minsar/lib/utils.sh"
[[ -f "$MINSAR_UTILS" ]] || {
    echo "Error: MinSAR utilities not found: $MINSAR_UTILS" >&2
    exit 1
}
source "$MINSAR_UTILS" >/dev/null

print_help() {
    cat <<EOF
usage: ${SCRIPT_NAME} [OPTIONS]

Run ISCE3 steps from the current processing directory.

options:
  -h, --help            show this help
  --backend BACKEND     auto, local, or slurm (default: auto)
  --start STEP          first step, inclusive
  --end STEP, --stop STEP
                        last step, inclusive
  --dostep STEP         run one step only
  --max-parallel N      local parallel tasks for launcher task lists (default: 1)
  --dry-run             print commands without executing or submitting

STEP may be a step number, step name, or run-file basename.

SAFE steps:    download_safe, create_cslc, run_dolphin, create_hdfeos5, ingest_insarmaps
CSLC steps:    download_cslc, run_dolphin, create_hdfeos5, ingest_insarmaps
DISP-S1 steps: download_disp, reformat_disp, create_hdfeos5, ingest_insarmaps

Examples:
  ${SCRIPT_NAME}
  ${SCRIPT_NAME} --start 2
  ${SCRIPT_NAME} --start 2 --stop 3
  ${SCRIPT_NAME} --dostep 3
  ${SCRIPT_NAME} --start run_dolphin --end create_hdfeos5
  ${SCRIPT_NAME} --dostep ingest_insarmaps
  ${SCRIPT_NAME} --backend local
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

require_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || die "$option requires a value"
}

backend="auto"
start_step=""
end_step=""
do_step=""
max_parallel=1
dry_run=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --backend)
            require_value "$1" "${2:-}"
            backend="$2"
            shift 2
            ;;
        --start)
            require_value "$1" "${2:-}"
            start_step="$2"
            shift 2
            ;;
        --end|--stop)
            require_value "$1" "${2:-}"
            end_step="$2"
            shift 2
            ;;
        --dostep)
            require_value "$1" "${2:-}"
            do_step="$2"
            shift 2
            ;;
        --max-parallel)
            require_value "$1" "${2:-}"
            max_parallel="$2"
            shift 2
            ;;
        --dry-run)
            dry_run=true
            shift
            ;;
        -?*|--*)
            die "unknown option: $1"
            ;;
        *)
            die "unexpected positional argument: $1"
            ;;
    esac
done

[[ "$backend" == "auto" || "$backend" == "local" || "$backend" == "slurm" ]] || die "--backend must be auto, local, or slurm"
[[ "$max_parallel" =~ ^[1-9][0-9]*$ ]] || die "--max-parallel must be a positive integer"
[[ -z "$do_step" || ( -z "$start_step" && -z "$end_step" ) ]] || die "--dostep cannot be combined with --start or --end"

if [[ "$backend" == "auto" ]]; then
    slurm_status="$(minsar_are_we_on_slurm_system 2>/dev/null)" || die "automatic SLURM detection failed; use --backend local or --backend slurm"
    case "$slurm_status" in
        login_node)
            if [[ -z "${SLURM_JOB_ID:-}" ]]; then
                backend="slurm"
            else
                backend="local"
            fi
            ;;
        compute_node|False)
            backend="local"
            ;;
        *)
            die "automatic SLURM detection returned unexpected status: $slurm_status"
            ;;
    esac
fi
echo "Backend: $backend"

work_dir="$(pwd -P)"
run_dir="$work_dir/run_files"
[[ -d "$run_dir" ]] || die "run_files directory not found under $work_dir"

stage_numbers=()
stage_names=()
stage_modes=()
stage_run_files=()
stage_job_files=()

job_uses_launcher() {
    local job_file="$1"
    local line
    while IFS= read -r line; do
        [[ "$line" == "export LAUNCHER_JOB_FILE="* ]] && return 0
    done < "$job_file"
    return 1
}

shopt -s nullglob
job_files=("$run_dir"/run_[0-9][0-9]_*.job)
shopt -u nullglob
for job_file in "${job_files[@]}"; do
    job_basename="$(basename "$job_file" .job)"
    [[ "$job_basename" =~ ^run_([0-9][0-9])_(.+)$ ]] || die "invalid job filename: $job_file"
    number_token="${BASH_REMATCH[1]}"
    stage_numbers+=("$((10#$number_token))")
    stage_names+=("${BASH_REMATCH[2]}")
    stage_run_files+=("$run_dir/$job_basename")
    stage_job_files+=("$job_file")
    if job_uses_launcher "$job_file"; then
        stage_modes+=("launcher-task-list")
    else
        stage_modes+=("sequential")
    fi
done

stage_count="${#stage_names[@]}"
[[ "$stage_count" -gt 0 ]] || die "no run_NN_*.job files found in $run_dir"

resolve_step() {
    local value="$1"
    local index
    local run_basename
    for ((index = 0; index < stage_count; index++)); do
        run_basename="$(basename "${stage_run_files[$index]}")"
        if [[ "$value" == "${stage_numbers[$index]}" || "$value" == "${stage_names[$index]}" || "$value" == "$run_basename" ]]; then
            echo "$index"
            return 0
        fi
    done
    return 1
}

start_index=0
end_index=$((stage_count - 1))

if [[ -n "$do_step" ]]; then
    start_index="$(resolve_step "$do_step")" || die "unknown step: $do_step"
    end_index="$start_index"
else
    if [[ -n "$start_step" ]]; then
        start_index="$(resolve_step "$start_step")" || die "unknown step: $start_step"
    fi
    if [[ -n "$end_step" ]]; then
        end_index="$(resolve_step "$end_step")" || die "unknown step: $end_step"
    fi
fi

[[ "$start_index" -le "$end_index" ]] || die "--start follows --end"

run_task_list() {
    local run_file="$1"
    local task
    local pid
    local failed=0
    local pids=()

    while IFS= read -r task || [[ -n "$task" ]]; do
        [[ -n "${task//[[:space:]]/}" ]] || continue
        [[ "$task" != \#* ]] || continue
        if [[ "$dry_run" == "true" ]]; then
            echo "$task"
            continue
        fi
        bash -c "$task" &
        pids+=("$!")
        if [[ "${#pids[@]}" -ge "$max_parallel" ]]; then
            if ! wait "${pids[0]}"; then
                failed=1
            fi
            pids=("${pids[@]:1}")
            [[ "$failed" -eq 0 ]] || break
        fi
    done < "$run_file"

    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            failed=1
        fi
    done
    return "$failed"
}

run_local_stage() {
    local index="$1"
    local run_file="${stage_run_files[$index]}"
    local validation_command=(validate_isce3_outputs.py --step "${stage_names[$index]}")
    [[ -f "$run_file" ]] || die "run file not found: $run_file"

    if [[ "${stage_modes[$index]}" == "launcher-task-list" ]]; then
        run_task_list "$run_file" || die "task list failed: $run_file"
    else
        echo "$run_file"
        if [[ "$dry_run" != "true" ]]; then
            "$run_file" || die "step failed: ${stage_names[$index]}"
        fi
    fi

    printf '%q ' "${validation_command[@]}"
    printf '\n'
    if [[ "$dry_run" != "true" ]]; then
        "${validation_command[@]}" || die "validation failed: ${stage_names[$index]}"
    fi
}

submit_slurm_stage() {
    local index="$1"
    local dependency="$2"
    local job_file="${stage_job_files[$index]}"
    local command=(sbatch)
    local result
    local job_id

    [[ -f "$job_file" ]] || die "job file not found: $job_file"
    if [[ -n "$dependency" ]]; then
        command+=(--dependency "afterok:$dependency")
    fi
    command+=("$job_file")
    printf '%q ' "${command[@]}" >&2
    printf '\n' >&2

    if [[ "$dry_run" == "true" ]]; then
        echo "DRYRUN_${stage_numbers[$index]}"
        return
    fi

    result="$("${command[@]}")" || die "SLURM submission failed: $job_file"
    echo "$result" >&2
    job_id="${result##* }"
    [[ "$job_id" =~ ^[0-9]+$ ]] || die "could not parse job ID from: $result"
    echo "$job_id"
}

if [[ "$backend" == "slurm" && "$dry_run" != "true" ]]; then
    command -v sbatch >/dev/null 2>&1 || die "sbatch is not available; use --backend local"
fi

dependency=""
for ((index = start_index; index <= end_index; index++)); do
    printf '[%02d] %s\n' "${stage_numbers[$index]}" "${stage_names[$index]}"
    if [[ "$backend" == "local" ]]; then
        run_local_stage "$index"
    else
        dependency="$(submit_slurm_stage "$index" "$dependency")" || exit 1
    fi
done
