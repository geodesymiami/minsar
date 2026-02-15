#!/usr/bin/env bash
set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "$1" == "--help" || "$1" == "-h" || -z "$1" ]]; then
    echo "Usage: $SCRIPT_NAME <jobfile>"
    echo ""
    echo "Example:"
    echo "  $SCRIPT_NAME SLC/run_01_burst2safe_rerun_0.job"
    echo ""
    echo "Run from the project directory. Checks for non-zero run file (jobfile name without .job)."
    echo "If it exists, runs the job file then check_burst2safe_job_outputs.py. Repeats for 24 hours or until empty."
    exit 0
fi

jobfile="$1"
runfile="${jobfile%.job}"
if [[ ! -f "$jobfile" ]]; then
    echo "ERROR: Job file not found: $jobfile"
    exit 1
fi

slc_dir=$(dirname "$jobfile")
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $jobfile" | tee -a log

max_runtime_seconds=$((24 * 3600))
wait_time=10
start_time=$(date +%s)

while true; do
    if [[ -s "$runfile" ]]; then
        echo "$runfile is non-zero size. Re-running workflow."
        run_workflow.bash --jobfile "$jobfile" --no-check-job-outputs
        check_burst2safe_job_outputs.py "$slc_dir" --clean
        echo "[INFO] Sleeping $wait_time seconds..."
        sleep $wait_time
    else
        echo "$runfile is zero size. All rerun items resolved. Exiting."
        break
    fi

    current_time=$(date +%s)
    elapsed=$((current_time - start_time))
    if (( elapsed >= max_runtime_seconds )); then
        echo "[INFO] Reached 24-hour limit. Exiting."
        break
    fi
done
