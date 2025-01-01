#!/bin/bash

# Function to display help message
show_help() {
    echo "Usage: $(basename "$0") [OPTIONS] <script_to_submit>"
    echo
    echo "Submits a SLURM job and waits for its completion."
    echo
    echo "Options:"
    echo "  -h, --help             Show this help message and exit."
    echo "      --waittime SECONDS Set the wait time between status checks (default: 60 seconds)."
    echo
    echo "Arguments:"
    echo "  script_to_submit       The SLURM job script to submit."
    echo
    echo "Example:"
    echo "  $(basename "$0") --waittime 30 smallbaselineApp.py"
}

# Default wait time
waittime=60

# Parse command-line options using getopt
TEMP=$(getopt -o h --long help,waittime: -n 'submit_sbatch.sh' -- "$@")
if [ $? -ne 0 ]; then
    echo "Error: Failed to parse options." >&2
    exit 1
fi
eval set -- "$TEMP"

# Process options
while true; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --waittime)
            if [[ "$2" =~ ^[0-9]+$ ]]; then
                waittime="$2"
                shift 2
            else
                echo "Error: --waittime requires a positive integer argument." >&2
                exit 1
            fi
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Error: Unexpected option: $1" >&2
            exit 1
            ;;
    esac
done

# Check if the script to submit is provided
if [ -z "$1" ]; then
    echo "Error: No script to submit provided." >&2
    show_help
    exit 1
fi
script_to_submit="$1"

# Submit the job and capture the Job ID
job_id=$(sbatch --parsable "$script_to_submit")

# Check if the job was submitted successfully
if [ -z "$job_id" ]; then
    echo "Failed to submit job." >&2
    exit 1
fi

echo "Submitted job with ID: $job_id"

# Function to check job status using scontrol
check_job_status() {
    local status
    status=$(scontrol show job "$1" | awk -F= '/JobState=/{print $2}' | awk '{print $1}')
    echo "$status"
}

# Wait for the job to complete
while true; do
    status=$(check_job_status "$job_id")
    if [[ "$status" == "COMPLETED" ]]; then
        echo "Job $job_id completed successfully."
        exit 0
    elif [[ "$status" == "FAILED" || "$status" == "CANCELLED" || "$status" == "TIMEOUT" ]]; then
        echo "Job $job_id failed with status: $status." >&2
        exit 1
    else
        echo "Job $job_id is still running. Current status: $status. Checking again in $waittime seconds..."
        sleep "$waittime"
    fi
done
