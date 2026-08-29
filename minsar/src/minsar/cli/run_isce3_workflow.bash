#!/usr/bin/env bash
# Run generated ISCE3 workflow files locally or submit their SLURM jobs.

set -o pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MINSAR_HOME="${MINSAR_HOME:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
MINSAR_UTILS="${MINSAR_HOME}/minsar/lib/utils.sh"
WORKFLOW_UTILS="${MINSAR_HOME}/minsar/lib/workflow_utils.sh"
SUBMIT_JOBS="${MINSAR_HOME}/minsar/bin/submit_jobs.bash"
ISCE3_JOB_DEFAULTS="job_defaults_isce3.cfg"
STAGE_SWEETS_PIXI="${MINSAR_HOME}/minsar/scripts/stage_sweets_pixi_env.bash"
[[ -f "$MINSAR_UTILS" ]] || {
    echo "Error: MinSAR utilities not found: $MINSAR_UTILS" >&2
    exit 1
}
[[ -f "$WORKFLOW_UTILS" ]] || {
    echo "Error: workflow utilities not found: $WORKFLOW_UTILS" >&2
    exit 1
}
[[ -f "$SUBMIT_JOBS" ]] || {
    echo "Error: submit_jobs.bash not found: $SUBMIT_JOBS" >&2
    exit 1
}
source "$MINSAR_UTILS" >/dev/null
source "$WORKFLOW_UTILS"

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

SAFE steps:    download_safe, create_cslc, dolphin, dolphin_2_hdfeos5, ingest_insarmaps
CSLC steps:    download_cslc, dolphin_wrapped, dolphin_unwrap, dolphin_timeseries, dolphin_2_hdfeos5, ingest_insarmaps
CSLC monolithic: download_cslc, dolphin, dolphin_2_hdfeos5, ingest_insarmaps (create_isce3_runfiles.py --no-dolphin-split)
DISP-S1 steps: download_disp, reformat_disp, dolphin_2_hdfeos5, ingest_insarmaps

Examples:
  ${SCRIPT_NAME}
  ${SCRIPT_NAME} --start 2
  ${SCRIPT_NAME} --start 2 --stop 3
  ${SCRIPT_NAME} --dostep 3
  ${SCRIPT_NAME} --start dolphin --end dolphin_2_hdfeos5
  ${SCRIPT_NAME} --dostep ingest_insarmaps
  ${SCRIPT_NAME} --backend local
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

print_step_banner() {
    local title="$1"
    echo "######################"
    echo "$title"
    echo "######################"
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
wait_time=30
original_args=("$@")

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

if [[ "${SHORT_JOB_COMPLETION_WAITTIME:-}" == [Tt]rue ]]; then
    wait_time=10
fi

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
# Log the full command line with SCRATCHDIR/SAMPLESDIR/TE simplified (as in run_workflow.bash)
simplified_args=()
for arg in "${original_args[@]}"; do
    if [[ -n "${SCRATCHDIR:-}" && "$arg" == "$SCRATCHDIR"* ]]; then
        simplified_args+=("\$SCRATCHDIR${arg#$SCRATCHDIR}")
    elif [[ -n "${SAMPLESDIR:-}" && "$arg" == "$SAMPLESDIR"* ]]; then
        simplified_args+=("\$SAMPLESDIR${arg#$SAMPLESDIR}")
    elif [[ -n "${TE:-}" && "$arg" == "$TE"* ]]; then
        simplified_args+=("\$TE${arg#$TE}")
    else
        simplified_args+=("$arg")
    fi
done
echo "$(date +"%Y%m%d:%H-%M") + ${SCRIPT_NAME} ${simplified_args[*]}" >> "${work_dir}"/log
run_dir="$work_dir/run_files"
project_name="$(basename "$work_dir")"
[[ -d "$run_dir" ]] || die "run_files directory not found under $work_dir"

job_uses_launcher() {
    local job_file="$1"
    local line
    while IFS= read -r line; do
        [[ "$line" == "export LAUNCHER_JOB_FILE="* ]] && return 0
    done < "$job_file"
    return 1
}

step_prefix() {
    local stem="$1"
    if [[ "$stem" =~ ^(run_[0-9][0-9]_.+)_[0-9]+$ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "$stem"
    fi
}

list_jobs_for_pattern() {
    local pattern="$1"
    if ls -1v "${pattern}"*.job >/dev/null 2>&1; then
        ls -1v "${pattern}"*.job
        return 0
    fi
    local job
    local nullglob_state
    nullglob_state="$(shopt -p nullglob)"
    shopt -s nullglob
    for job in "${pattern}"*.job; do
        printf '%s\n' "$job"
    done
    eval "$nullglob_state"
}

jobs_for_step() {
    local number="$1"
    local nn
    local job
    local nullglob_state
    printf -v nn '%02d' "$number"
    nullglob_state="$(shopt -p nullglob)"
    shopt -s nullglob
    for job in "$run_dir"/run_"${nn}"_*.job; do
        printf '%s\n' "$job"
    done
    eval "$nullglob_state"
}

stage_numbers=()
stage_names=()
stage_patterns=()

shopt -s nullglob
all_job_files=("$run_dir"/run_[0-9][0-9]_*.job)
shopt -u nullglob
[[ "${#all_job_files[@]}" -gt 0 ]] || die "no run_NN_*.job files found in $run_dir"

for job_file in "${all_job_files[@]}"; do
    job_basename="$(basename "$job_file" .job)"
    [[ "$job_basename" =~ ^run_([0-9][0-9])_(.+)$ ]] || die "invalid job filename: $job_file"
    number_token="${BASH_REMATCH[1]}"
    rest="${BASH_REMATCH[2]}"
    number="$((10#$number_token))"
    name="$rest"
    if [[ "$name" =~ ^(.+)_([0-9]+)$ ]]; then
        name="${BASH_REMATCH[1]}"
    fi
    already=false
    for existing in "${stage_numbers[@]}"; do
        if [[ "$existing" == "$number" ]]; then
            already=true
            break
        fi
    done
    if [[ "$already" != "true" ]]; then
        stage_numbers+=("$number")
        stage_names+=("$name")
        stage_patterns+=("$run_dir/$(step_prefix "$job_basename")")
    fi
done

stage_count="${#stage_names[@]}"
[[ "$stage_count" -gt 0 ]] || die "no run_NN_*.job files found in $run_dir"

resolve_step() {
    local value="$1"
    local index
    local job
    local stem
    for ((index = 0; index < stage_count; index++)); do
        if [[ "$value" == "${stage_numbers[$index]}" || "$value" == "${stage_names[$index]}" ]]; then
            echo "$index"
            return 0
        fi
        while IFS= read -r job; do
            stem="$(basename "$job" .job)"
            if [[ "$value" == "$stem" || "$value" == "$(step_prefix "$stem")" ]]; then
                echo "$index"
                return 0
            fi
        done < <(jobs_for_step "${stage_numbers[$index]}")
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

run_isce3_runfile() {
    bash "$1"
}

job_path_for_display() {
    local job_file="$1"
    if [[ "$job_file" == "$work_dir"/* ]]; then
        echo "${job_file#"$work_dir"/}"
    else
        echo "$job_file"
    fi
}

run_job_validation() {
    local job_file="$1"
    local display_path
    display_path="$(job_path_for_display "$job_file")"
    print_step_banner "Checking outputs:   validate_isce3_job_outputs.py ${display_path}"
    if [[ "$dry_run" == "true" ]]; then
        return 0
    fi
    validate_isce3_job_outputs.py "$job_file" || die "validation failed: ${display_path}"
}

run_local_stage() {
    local index="$1"
    local job_file
    local run_file

    cd "$work_dir" || die "cannot cd to $work_dir"
    while IFS= read -r job_file; do
        run_file="${job_file%.job}"
        [[ -f "$run_file" ]] || die "run file not found: $run_file"
        print_step_banner "Running:    $(basename "$run_file")"
        if job_uses_launcher "$job_file"; then
            run_task_list "$run_file" || die "task list failed: $run_file"
        else
            if [[ "$dry_run" != "true" ]]; then
                run_isce3_runfile "$run_file" || die "step failed: ${stage_names[$index]}"
            fi
        fi
    done < <(jobs_for_step "${stage_numbers[$index]}")

    while IFS= read -r job_file; do
        run_job_validation "$job_file"
    done < <(jobs_for_step "${stage_numbers[$index]}")
}

wait_for_slurm_jobs() {
    local step_name="$1"
    local file_pattern="$2"
    shift 2
    local files=("$@")
    local jobnumbers=()
    local jns
    local exit_status
    local sbc_command
    local num_jobs num_complete num_running num_pending num_timeout num_waiting
    local j file jobnumber state
    local init_walltime init_queue updated_walltime updated_queue datetime rerun_line

    sbc_command="$SUBMIT_JOBS $file_pattern"
    echo "Jobfiles to submit:"
    printf '%s\n' "${files[@]}"
    echo "Job submission command:"
    echo "$sbc_command"

    if [[ "$dry_run" == "true" ]]; then
        return 0
    fi

    if [[ -f "$STAGE_SWEETS_PIXI" ]]; then
        "$STAGE_SWEETS_PIXI"
    fi

    jns="$("$SUBMIT_JOBS" "$file_pattern")"
    exit_status="$?"
    [[ "$exit_status" -eq 0 ]] || die "submit_jobs.bash failed for $file_pattern"
    jobnumbers=($jns)
    echo "Jobs submitted: $(convert_array_to_comma_separated_string "${jobnumbers[@]}")"
    sleep 5

    num_jobs="${#jobnumbers[@]}"
    num_complete=0
    command -v sacct >/dev/null 2>&1 || die "sacct is not available; use --backend local"

    while [[ "$num_complete" -lt "$num_jobs" ]]; do
        num_complete=0
        num_running=0
        num_pending=0
        num_timeout=0
        num_waiting=0
        sleep "$wait_time"

        for ((j = 0; j < "${#jobnumbers[@]}"; j++)); do
            file="${files[$j]}"
            jobnumber="${jobnumbers[$j]}"
            state="$(sacct --format="State" -j "$jobnumber" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | head -3 | tail -1)"
            if [[ "$state" == *"COMPLETED"* ]]; then
                num_complete=$((num_complete + 1))
            elif [[ "$state" == *"RUNNING"* ]]; then
                num_running=$((num_running + 1))
            elif [[ "$state" == *"PENDING"* ]]; then
                num_pending=$((num_pending + 1))
            elif [[ "$state" == *"TIMEOUT"* || "$state" == *"NODE_FAIL"* ]]; then
                num_timeout=$((num_timeout + 1))
                if [[ "$state" == *"TIMEOUT"* ]]; then
                    init_walltime="$(grep -oE '#SBATCH -t [0-9]+:[0-9]+:[0-9]+' "$file" | awk '{print $3}')"
                    init_queue="$(grep -oE '#SBATCH -p [^[:space:]]+' "$file" | awk '{print $3}')"
                    echo "Job file ${file} timed out with walltime of ${init_walltime}."
                    update_walltime_queuename.py --config "$ISCE3_JOB_DEFAULTS" "$file" &>/dev/null
                    updated_walltime="$(grep -oE '#SBATCH -t [0-9]+:[0-9]+:[0-9]+' "$file" | awk '{print $3}')"
                    updated_queue="$(grep -oE '#SBATCH -p [^[:space:]]+' "$file" | awk '{print $3}')"
                    datetime="$(date +"%Y-%m-%d:%H-%M")"
                    rerun_line="${datetime}: re-running: ${file}: ${init_walltime} --> ${updated_walltime}"
                    if [[ -n "$init_queue" && -n "$updated_queue" && "$init_queue" != "$updated_queue" ]]; then
                        rerun_line="${rerun_line}   ${init_queue} --> ${updated_queue}"
                    fi
                    echo "$rerun_line" >> "${run_dir}/rerun.log"
                    echo "Resubmitting file (${file}) with new walltime of ${updated_walltime}"
                fi
                jobnumbers=($(remove_from_list "$jobnumber" "${jobnumbers[@]}"))
                files=($(remove_from_list "$file" "${files[@]}"))
                if [[ -f "$STAGE_SWEETS_PIXI" ]]; then
                    "$STAGE_SWEETS_PIXI"
                fi
                jobnumber="$($SUBMIT_JOBS "${file%.*}")"
                exit_status="$?"
                if [[ "$exit_status" -eq 0 ]]; then
                    jobnumbers+=("$jobnumber")
                    files+=("$file")
                    j=$((j - 1))
                    echo "Resubmitted as jobnumber: ${jobnumber}."
                else
                    die "resubmit failed for $file"
                fi
            elif [[ "$state" == *"FAILED"* || "$state" == *"CANCELLED"* ]]; then
                die "job $file: state $state"
            else
                echo "Strange job state: $state, encountered."
                continue
            fi
        done

        num_waiting=$((num_jobs - num_complete - num_running - num_pending))
        printf "%s, %s, %-7s: %-12s, %-10s, %-10s, %-12s.\n" "$project_name" "$step_name" "$num_jobs jobs" "$num_complete COMPLETED" "$num_running RUNNING" "$num_pending PENDING" "$num_waiting WAITING"
    done
}

check_step_outputs() {
    shift
    local files=("$@")
    local job_file

    for job_file in "${files[@]}"; do
        run_job_validation "$job_file"
    done
    echo
}

if [[ "$backend" == "slurm" && "$dry_run" != "true" ]]; then
    command -v sbatch >/dev/null 2>&1 || die "sbatch is not available; use --backend local"
fi

for ((index = start_index; index <= end_index; index++)); do
    if [[ "$backend" == "local" ]]; then
        run_local_stage "$index"
    else
        files=()
        while IFS= read -r job_file; do
            files+=("$job_file")
        done < <(list_jobs_for_pattern "${stage_patterns[$index]}")
        [[ "${#files[@]}" -gt 0 ]] || die "no job files for step ${stage_names[$index]}"
        for job_file in "${files[@]}"; do
            print_step_banner "Running:    $(basename "$job_file" .job)"
        done
        wait_for_slurm_jobs "${stage_names[$index]}" "${stage_patterns[$index]}" "${files[@]}"
        check_step_outputs "$index" "${files[@]}"
    fi
done
