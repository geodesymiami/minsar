#!/usr/bin/env bash
# Show per-node CPU/load/memory plus process-level metrics for a running SLURM job.
set -euo pipefail

SCRIPT_NAME="${0##*/}"

usage() {
    cat <<EOF
usage: ${SCRIPT_NAME} JOB_ID
       ${SCRIPT_NAME} [-h|--help]

Per-node utilization and top processes for a running SLURM job.
Resolves the job file from scontrol (Command= or WorkDir/JobName.job).

options:
  -h, --help    show this help

Examples:
  ${SCRIPT_NAME} 2945105
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

# Job summary from squeue (elapsed, limit, alloc CPUs)
squeue_line=$(squeue -j "$jobid" -h -o '%i %P %j %T %M %l %D %C %m %N' 2>/dev/null || true)
if [[ -n "$squeue_line" ]]; then
    read -r sq_jobid sq_part sq_name sq_state sq_elapsed sq_limit sq_nodes sq_cpus sq_mem sq_nodelist <<< "$squeue_line"
    echo "Job: $sq_jobid  $sq_name  $sq_state  partition=$sq_part"
    echo "  Elapsed: $sq_elapsed / $sq_limit   Nodes: $sq_nodes   AllocCPUs: $sq_cpus   MemReq: $sq_mem"
    echo "  NodeList: $sq_nodelist"
    echo ""
fi

jobfile=""
if [[ -n "$job_info" ]]; then
    cmd_path=$(echo "$job_info" | tr ' ' '\n' | sed -n 's/^Command=//p' | head -1)
    if [[ -n "$cmd_path" && -f "$cmd_path" ]]; then
        jobfile="$cmd_path"
    else
        work_dir=$(echo "$job_info" | sed -E 's/.*\bWorkDir=([^[:space:]]+).*/\1/')
        job_name=$(echo "$job_info" | sed -E 's/.*\bJobName=([^[:space:]]+).*/\1/')
        if [[ -n "$work_dir" && -n "$job_name" ]]; then
            for base in \
                "$work_dir/run_files_isce3/$job_name.job" \
                "$work_dir/run_files/$job_name.job" \
                "$work_dir/$job_name.job" \
                "$work_dir/run_files_isce3/${job_name}.job" \
                "$work_dir/run_files/${job_name}.job"
            do
                if [[ -f "$base" ]]; then
                    jobfile="$base"
                    break
                fi
            done
        fi
    fi
fi

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
            launcher_job_file=$(echo "${BASH_REMATCH[1]}" | sed -E 's/^["'\'']?//; s/[[:space:]#].*//; s/["'\'']$//')
        fi
    done < "$f"
    echo "$nodes" "$ntasks" "$walltime" "$partition" "$cpus_per_task" "$omp_threads" "$launcher_job_file"
}

launcher_file_lines=""
resolve_launcher_tasks() {
    local job_f="$1"
    local launcher_path="$2"
    [[ -z "$launcher_path" ]] && return
    local resolved=""
    if [[ -f "$launcher_path" ]]; then
        resolved="$launcher_path"
    else
        local job_dir base
        job_dir=$(dirname "$job_f")
        base=$(echo "$launcher_path" | sed -E 's/.*\/([^/]+)$/\1/')
        if [[ -f "$job_dir/$base" ]]; then
            resolved="$job_dir/$base"
        fi
    fi
    if [[ -n "$resolved" && -r "$resolved" ]]; then
        launcher_file_lines=$(grep -c . "$resolved" 2>/dev/null) || launcher_file_lines=""
        [[ -z "$launcher_file_lines" ]] && launcher_file_lines=0
    fi
    return 0
}

sbatch_nodes="" sbatch_ntasks="" sbatch_walltime="" sbatch_partition=""
sbatch_cpus_per_task="1" sbatch_omp_threads="" sbatch_launcher_job_file=""
total_cores=0

if [[ -n "$jobfile" && -f "$jobfile" && -r "$jobfile" ]]; then
    parsed=$(parse_sbatch "$jobfile" 2>/dev/null) || parsed=""
    read -r sbatch_nodes sbatch_ntasks sbatch_walltime sbatch_partition sbatch_cpus_per_task sbatch_omp_threads sbatch_launcher_job_file <<< "${parsed:-}"
    resolve_launcher_tasks "$jobfile" "$sbatch_launcher_job_file"
    echo "From job file: $jobfile"
    echo "  Nodes: ${sbatch_nodes:-n/a}   Ntasks: ${sbatch_ntasks:-n/a}   CPUs/task: ${sbatch_cpus_per_task:-1}   Walltime: ${sbatch_walltime:-n/a}   Partition: ${sbatch_partition:-n/a}"
    total_cores=$(( ${sbatch_ntasks:-0} * ${sbatch_cpus_per_task:-1} )) || total_cores=0
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

# Prefer AllocCPUs from squeue when job file did not set -n/-c clearly
if [[ "${total_cores:-0}" -le 0 && -n "${sq_cpus:-}" && "$sq_cpus" =~ ^[0-9]+$ ]]; then
    total_cores="$sq_cpus"
fi

nodelist=$(squeue -j "$jobid" -h -o %N 2>/dev/null || true)
if [[ -z "$nodelist" ]]; then
    nodelist=$(scontrol show job "$jobid" 2>/dev/null | sed -E 's/.* NodeList=([^[:space:]]+).*/\1/' || true)
fi
nodelist=$(printf '%s' "$nodelist" | tr -d '\r' | tr '\n' ',' | sed 's/,$//;s/^[[:space:]]*//;s/[[:space:]]*$//')
nodes=$(scontrol show hostnames "$nodelist" 2>/dev/null || true)
if [[ -z "$nodes" && -n "$nodelist" && "$nodelist" != *,* && "$nodelist" != *[* && "$nodelist" != *]* ]]; then
    nodes="$nodelist"
fi
nodes=$(printf '%s' "$nodes" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr -s '\n' '\n' | sed '/^$/d' || true)
if [[ -z "$nodes" ]]; then
    echo "Job $jobid not found or no node list (squeue/scontrol). Showing no nodes." >&2
    exit 0
fi

job_user=$(squeue -j "$jobid" -h -o %u 2>/dev/null || true)
[[ -z "$job_user" ]] && job_user=$(whoami)

printf "%-10s %5s %7s %7s %7s %7s %10s %10s  %s\n" \
    "NODES" "CPU" "LOAD" "L/CPU" "IDLE%" "WA%" "MEM%" "GB/core" "STATUS"
printf "%s\n" "-------------------------------------------------------------------------------"

for n in $nodes; do
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$n" \
        JOB_USER="$job_user" TOTAL_CORES="$total_cores" bash -s <<'REMOTE' || echo "Failed to query node $n (ssh or remote command failed)." >&2
set -euo pipefail
cores=$(nproc)
load=$(awk '{print $1}' /proc/loadavg)

cpu_line=$(top -bn2 -d 0.2 | awk '/^%Cpu/{line=$0} END{print line}')
idle=$(echo "$cpu_line" | sed -E 's/.*, *([0-9.]+) id,.*/\1/')
wa=$(echo "$cpu_line" | sed -E 's/.*, *([0-9.]+) wa,.*/\1/')

read -r mem_total mem_used mem_avail <<< "$(free -g | awk '/^Mem:/{print $2, $3, $7}')"

mem_pct=$(awk -v u="$mem_used" -v t="$mem_total" 'BEGIN{printf "%.1f", (t>0)?100*u/t:0}')
mem_per_core=$(awk -v u="$mem_used" -v c="$cores" 'BEGIN{printf "%.2f", (c>0)?u/c:0}')
load_per_cpu=$(awk -v l="$load" -v c="$cores" 'BEGIN{printf "%.2f", (c>0)?l/c:0}')

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
    "$(hostname -s)" "$cores" "$load" "$load_per_cpu" "$idle" "$wa" "$mem_pct" "$mem_per_core" "$status"

# Process snapshot for the job owner (CPU, threads, state, RSS)
echo ""
echo "Top processes (user=${JOB_USER}):"
printf "  %-8s %6s %5s %5s %4s %8s  %s\n" "PID" "%CPU" "%MEM" "STATE" "NLWP" "RSS_GB" "COMMAND"
ps -u "$JOB_USER" -o pid=,pcpu=,pmem=,state=,nlwp=,rss=,args= --sort=-pcpu 2>/dev/null | head -12 | while IFS= read -r line; do
    pid=$(echo "$line" | awk '{print $1}')
    pcpu=$(echo "$line" | awk '{print $2}')
    pmem=$(echo "$line" | awk '{print $3}')
    state=$(echo "$line" | awk '{print $4}')
    nlwp=$(echo "$line" | awk '{print $5}')
    rss_kb=$(echo "$line" | awk '{print $6}')
    cmd=$(echo "$line" | awk '{for(i=7;i<=NF;i++) printf "%s%s", $i, (i<NF?" ":""); print ""}')
    # Shorten long paths in command
    cmd_short=$(echo "$cmd" | sed -E 's|/[^ ]+/||g' | cut -c1-60)
    rss_gb=$(awk -v r="$rss_kb" 'BEGIN{printf "%.2f", r/1024/1024}')
    printf "  %-8s %6s %5s %5s %4s %8s  %s\n" "$pid" "$pcpu" "$pmem" "$state" "$nlwp" "$rss_gb" "$cmd_short"
done

# Aggregate CPU% and runnable/D counts for this user
read -r nproc_user sum_pcpu sum_nlwp n_D n_R <<< "$(
    ps -u "$JOB_USER" -o pcpu=,state=,nlwp= --no-headers 2>/dev/null | awk '
    {
      n++; sum+=$1; nlwp+=$3;
      if ($2 ~ /D/) d++;
      if ($2 ~ /R/) r++;
    }
    END { printf "%d %.1f %d %d %d", n+0, sum+0, nlwp+0, d+0, r+0 }'
)"
echo ""
echo "  User process summary: n=${nproc_user:-0}  sum_%CPU=${sum_pcpu:-0}  sum_NLWP=${sum_nlwp:-0}  R=${n_R:-0}  D(iowait)=${n_D:-0}"
if [[ -n "${TOTAL_CORES:-}" && "${TOTAL_CORES}" =~ ^[1-9][0-9]*$ ]]; then
    # %CPU of 100 ≈ 1 core; compare sum_%CPU/100 to requested cores
    cores_busy=$(awk -v s="${sum_pcpu:-0}" 'BEGIN{printf "%.1f", s/100}')
    pct_of_req=$(awk -v b="$cores_busy" -v t="$TOTAL_CORES" 'BEGIN{printf "%.0f", (t>0)?100*b/t:0}')
    echo "  Approx busy cores: ${cores_busy} / ${TOTAL_CORES} requested (${pct_of_req}%)"
    if (( $(echo "${sum_pcpu:-0} < ${TOTAL_CORES} * 25" | bc -l) )); then
        echo "  Hint: job holds many CPUs but little CPU work — check worker/thread settings or I/O (STATE=D)."
    fi
fi
if [[ "${n_D:-0}" -gt 0 ]]; then
    echo "  Hint: processes in D state are often blocked on disk/NFS I/O."
fi
REMOTE
done

echo ""
if [[ -n "${sbatch_launcher_job_file:-}" && -n "${launcher_file_lines:-}" && "$launcher_file_lines" -gt 0 ]]; then
    echo "Efficiency note: launcher job with $launcher_file_lines tasks; compare L/CPU and process count to LAUNCHER_PPN."
elif [[ "${total_cores:-0}" -gt 8 ]]; then
    echo "Efficiency note: single-multicore job requested ${total_cores} CPUs. If sum_%CPU stays near one process × threads_per_worker (e.g. ~800 for 8 threads), raise n_parallel_bursts / threads_per_worker or reduce -n."
fi
