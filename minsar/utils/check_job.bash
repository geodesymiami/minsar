#!/usr/bin/env bash
# Show per-node CPU, load, memory and status for a SLURM job; optionally show job-file parameters.
set -euo pipefail

usage() {
    cat << EOF
Usage: ${0##*/} JOB_ID
       ${0##*/} --help

Print per-node utilization (CPU load, idle%, I/O wait, memory) and status for a running or
recent SLURM job. The job file is located from scontrol (Command= or WorkDir/JobName.job).

Options:
  --help    Show this help and exit.

Arguments:
  JOB_ID    SLURM job id (required).

Output:
  - Per-node table: NODES, CPU (cores), LOAD, L/CPU (load per core), IDLE%, WA% (iowait),
    MEM%, GB/core, STATUS (OK, UNDERUSED, OVERSUB, IO-bound, MEM-limited).
  - If the job file is found: "From job file" section with requested nodes, ntasks,
    cpus-per-task, walltime, partition; OMP_NUM_THREADS; LAUNCHER_JOB_FILE and number of
    launcher tasks (lines in that file).
  - Brief efficiency notes when relevant (e.g. L/CPU vs cpus-per-task).

Examples:
  ${0##*/} 2945105
  ${0##*/} --help
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ $# -lt 1 ]]; then
    echo "Error: JOB_ID required." >&2
    usage >&2
    exit 1
fi

jobid="$1"

# Get job info and require job to be running (reject pending/completed so we only SSH to live nodes)
job_info=""
if command -v scontrol &>/dev/null; then
    job_info=$(scontrol show job "$jobid" 2>/dev/null || true)
fi
if [[ -n "$job_info" ]]; then
    job_state=$(echo "$job_info" | tr ' ' '\n' | sed -n 's/^JobState=//p' | head -1 | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    job_state_upper=$(echo "$job_state" | tr '[:lower:]' '[:upper:]')
    if [[ -n "$job_state" && "$job_state_upper" != "RUNNING" ]]; then
        echo "Job $jobid is not running (state: $job_state). This script reports utilization only for running jobs." >&2
        exit 1
    fi
fi

# Resolve job file from scontrol: Command= (batch script path), else WorkDir + run_files/JobName.job
jobfile=""
if [[ -n "$job_info" ]]; then
    # Try Command= first (path to the submitted batch script)
    cmd_path=$(echo "$job_info" | tr ' ' '\n' | sed -n 's/^Command=//p' | head -1)
    if [[ -n "$cmd_path" && -f "$cmd_path" ]]; then
        jobfile="$cmd_path"
    else
        work_dir=$(echo "$job_info" | sed -E 's/.*\bWorkDir=([^[:space:]]+).*/\1/')
        job_name=$(echo "$job_info" | sed -E 's/.*\bJobName=([^[:space:]]+).*/\1/')
        if [[ -n "$work_dir" && -n "$job_name" ]]; then
            for base in "$work_dir/run_files/$job_name.job" "$work_dir/$job_name.job" "$work_dir/run_files/${job_name}.job"; do
                if [[ -f "$base" ]]; then
                    jobfile="$base"
                    break
                fi
            done
        fi
    fi
fi

# Parse job file for #SBATCH and export OMP_NUM_THREADS / LAUNCHER_JOB_FILE
parse_sbatch() {
    local f="$1"
    local nodes="" ntasks="" walltime="" partition="" cpus_per_task="1" omp_threads="" launcher_job_file=""
    while IFS= read -r line; do
        if [[ "$line" =~ ^#SBATCH[[:space:]]+-N[[:space:]]+([0-9]+) ]]; then
            nodes="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^#SBATCH[[:space:]]+-n[[:space:]]+([0-9]+) ]]; then
            ntasks="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^#SBATCH[[:space:]]+-t[[:space:]]+([^[:space:]]+) ]]; then
            walltime="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^#SBATCH[[:space:]]+-p[[:space:]]+([^[:space:]]+) ]]; then
            partition="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^#SBATCH[[:space:]]+(-c|--cpus-per-task)[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            cpus_per_task="${BASH_REMATCH[2]}"
        elif [[ "$line" =~ ^#SBATCH[[:space:]]+(-c|--cpus-per-task)[[:space:]]+([0-9]+) ]]; then
            cpus_per_task="${BASH_REMATCH[2]}"
        elif [[ "$line" =~ export[[:space:]]+OMP_NUM_THREADS=(.+) ]]; then
            omp_threads=$(echo "${BASH_REMATCH[1]}" | sed -E 's/^["'\'']?([0-9]+).*/\1/')
        elif [[ "$line" =~ export[[:space:]]+LAUNCHER_JOB_FILE=(.+) ]]; then
            # Strip quotes/newline; take path (may end at space or #)
            launcher_job_file=$(echo "${BASH_REMATCH[1]}" | sed -E 's/^["'\'']?//; s/[[:space:]#].*//; s/["'\'']$//')
        fi
    done < "$f"
    echo "$nodes" "$ntasks" "$walltime" "$partition" "$cpus_per_task" "$omp_threads" "$launcher_job_file"
}

# Resolve launcher job file path (may be absolute or contain $VAR); count non-empty lines
launcher_file_lines=""
resolve_launcher_tasks() {
    local job_f="$1"
    local launcher_path="$2"
    [[ -z "$launcher_path" ]] && return
    local resolved=""
    if [[ -f "$launcher_path" ]]; then
        resolved="$launcher_path"
    else
        # Try same directory as .job file (run_files/) with basename
        local job_dir base
        job_dir=$(dirname "$job_f")
        base=$(echo "$launcher_path" | sed -E 's/.*\/([^/]+)$/\1/')
        if [[ -f "$job_dir/$base" ]]; then
            resolved="$job_dir/$base"
        fi
    fi
    if [[ -n "$resolved" && -r "$resolved" ]]; then
        # Count non-empty lines (launcher task list)
        launcher_file_lines=$(grep -c . "$resolved" 2>/dev/null) || launcher_file_lines=""
        [[ -z "$launcher_file_lines" ]] && launcher_file_lines=0
    fi
    return 0
}

if [[ -n "$jobfile" && -f "$jobfile" && -r "$jobfile" ]]; then
    parsed=$(parse_sbatch "$jobfile" 2>/dev/null) || parsed=""
    read -r sbatch_nodes sbatch_ntasks sbatch_walltime sbatch_partition sbatch_cpus_per_task sbatch_omp_threads sbatch_launcher_job_file <<< "${parsed:-}"
    resolve_launcher_tasks "$jobfile" "$sbatch_launcher_job_file"
    echo "From job file: $jobfile"
    echo "  Nodes: ${sbatch_nodes:-n/a}   Ntasks: ${sbatch_ntasks:-n/a}   CPUs/task: ${sbatch_cpus_per_task:-1}   Walltime: ${sbatch_walltime:-n/a}   Partition: ${sbatch_partition:-n/a}"
    total_cores=$(( (sbatch_ntasks ? sbatch_ntasks : 0) * (sbatch_cpus_per_task ? sbatch_cpus_per_task : 1) )) || total_cores=0
    if [[ -n "${sbatch_ntasks:-}" && "${sbatch_ntasks:-0}" -gt 0 ]] 2>/dev/null; then
        echo "  Total requested CPUs: $total_cores"
    fi
    if [[ -n "$sbatch_omp_threads" ]]; then
        echo "  OMP_NUM_THREADS: $sbatch_omp_threads"
    fi
    if [[ -n "$sbatch_launcher_job_file" ]]; then
        echo "  LAUNCHER_JOB_FILE: $sbatch_launcher_job_file"
        if [[ -n "$launcher_file_lines" ]]; then
            echo "  Launcher file lines: $launcher_file_lines"
        fi
    fi
    echo ""
fi

# Get nodelist: from squeue if job is running, else from scontrol (recently finished).
# Handle both single-node and multi-node jobs; some systems use compact form (e.g. c454-[043-044],c455-082).
nodelist=$(squeue -j "$jobid" -h -o %N 2>/dev/null || true)
if [[ -z "$nodelist" ]]; then
    nodelist=$(scontrol show job "$jobid" 2>/dev/null | sed -E 's/.* NodeList=([^[:space:]]+).*/\1/' || true)
fi
# Trim and normalize: remove \r, fold newlines to commas so single-line and multi-line nodelist both work
nodelist=$(printf '%s' "$nodelist" | tr -d '\r' | tr '\n' ',' | sed 's/,$//;s/^[[:space:]]*//;s/[[:space:]]*$//')
nodes=$(scontrol show hostnames "$nodelist" 2>/dev/null || true)
# Single-node fallback: some systems leave nodelist as one hostname; scontrol show hostnames may return nothing
if [[ -z "$nodes" && -n "$nodelist" && "$nodelist" != *,* && "$nodelist" != *[* && "$nodelist" != *]* ]]; then
    nodes="$nodelist"
fi
# Normalize nodes for loop: trim so single-node and multi-node both iterate correctly
nodes=$(printf '%s' "$nodes" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr -s '\n' '\n' | sed '/^$/d' || true)
if [[ -z "$nodes" ]]; then
    echo "Job $jobid not found or no node list (squeue/scontrol). Showing no nodes." >&2
    exit 0
fi

printf "%-10s %5s %7s %7s %7s %7s %10s %10s  %s\n" \
    "NODES" "CPU" "LOAD" "L/CPU" "IDLE%" "WA%" "MEM%" "GB/core" "STATUS"
printf "%s\n" "-------------------------------------------------------------------------------"

for n in $nodes; do
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$n" '
cores=$(nproc)
load=$(awk "{print \$1}" /proc/loadavg)

cpu_line=$(top -bn2 -d 0.2 | awk "/^%Cpu/{line=\$0} END{print line}")
idle=$(echo "$cpu_line" | sed -E "s/.*, *([0-9.]+) id,.*/\1/")
wa=$(echo "$cpu_line" | sed -E "s/.*, *([0-9.]+) wa,.*/\1/")

read mem_total mem_used mem_avail <<< $(free -g | awk "/^Mem:/{print \$2, \$3, \$7}")

mem_pct=$(awk -v u=$mem_used -v t=$mem_total "BEGIN{printf \"%.1f\", 100*u/t}")
mem_per_core=$(awk -v u=$mem_used -v c=$cores "BEGIN{printf \"%.2f\", u/c}")

load_per_cpu=$(awk -v l=$load -v c=$cores "BEGIN{printf \"%.2f\", l/c}")

status="OK"

if (( $(echo "$wa > 10" | bc -l) )); then
    status="IO-bound"
elif (( $(echo "$mem_pct > 85" | bc -l) )); then
    status="MEM-limited"
elif (( $(echo "$idle > 20" | bc -l) )); then
    status="UNDERUSED"
elif (( $(echo "$load_per_cpu > 1.2" | bc -l) )); then
    status="OVERSUB"
elif (( $(echo "$load_per_cpu < 0.7" | bc -l) )); then
    status="UNDERUSED"
fi

printf "%-10s %5d %7.1f %7.2f %7.1f %7.1f %9.1f%% %10.2f  %s\n" \
"$(hostname -s)" $cores $load $load_per_cpu $idle $wa $mem_pct $mem_per_core "$status"
' || echo "Failed to query node $n (ssh or remote command failed)." >&2
done

# Efficiency note when we have job file info
if [[ -n "$jobfile" && -n "$sbatch_cpus_per_task" && "$sbatch_cpus_per_task" -gt 1 ]]; then
    echo ""
    echo "Efficiency note: Job requests $sbatch_cpus_per_task CPU(s) per task. If L/CPU is consistently below 1.0 on all nodes, the workload may be mostly single-threaded; using 1 CPU per task can sometimes improve throughput (fewer context switches). If L/CPU is near or above 1.0, multi-threading is likely in use."
fi
