#!/usr/bin/env bash
set -euo pipefail

function show_help() {
  cat << EOF
Usage: ${0##*/} [OPTIONS] "<command> [<cmd_args>...]"
       ${0##*/} [OPTIONS] --from-file <script>

Creates a SLURM job file for a command string, or for a bash script (--from-file).
With --from-file, the job body runs: bash /abs/path/to/script

Options:
  --help                Show this help message and exit
  --queue <queue>       Override SLURM partition/queue (default: \$QUEUENAME)
  --wall-time <hh:mm:ss> Override wall time (default: fetched from job_defaults.cfg)
  --job-name <name>     Override job name (default: base command minus .py/.sh/.bash)
  --from-file <path>    Job body is: bash <path> (script-style run file; no LAUNCHER)

Environment variables (if not overridden by flags):
  NOTIFICATIONEMAIL         e.g. falk.amelung@gmail.com
  JOBSHEDULER_PROJECTNAME   e.g. TG-EAR200012
  QUEUENAME                 e.g. skx
  PLATFORM_NAME             e.g. stampede3, frontera, etc.

Examples:
  ${0##*/} "smallbaselineApp.py /path/to/template --dir mintpy"
  ${0##*/} --queue skx --wall-time 1:50:00 --job-name smallbaseline_wrapper "create_runfiles.py --arg1 val1"
  ${0##*/} --job-name horzvert2timeseries --from-file run_horzvert2timeseries
EOF
}

# Parse command-line options with GNU getopt
TEMP="$(getopt \
  -o '' \
  --long help,queue:,wall-time:,job-name:,from-file: \
  -n "${0##*/}" -- "$@")"

if [ $? -ne 0 ]; then
  echo "Error: Invalid command line arguments." >&2
  exit 1
fi

eval set -- "$TEMP"

# Initialize default overrides
queue="${QUEUENAME:-}"
job_name=""
wall_time=""
from_file=""

while true; do
  case "$1" in
    --help)
      show_help
      exit 0
      ;;
    --queue)
      queue="$2"
      shift 2
      ;;
    --wall-time)
      wall_time="$2"
      shift 2
      ;;
    --job-name)
      job_name="$2"
      shift 2
      ;;
    --from-file)
      from_file="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Error: Unexpected option '$1'." >&2
      exit 1
      ;;
  esac
done

###############################################################################
# Check environment variables
###############################################################################
: "${NOTIFICATIONEMAIL:?Environment variable NOTIFICATIONEMAIL not set or empty.}"
: "${JOBSHEDULER_PROJECTNAME:?Environment variable JOBSHEDULER_PROJECTNAME not set or empty.}"

# If queue is still empty, default to \$QUEUENAME or "skx"
if [[ -z "${queue}" ]]; then
  queue="${QUEUENAME:-skx}"
fi

###############################################################################
# Resolve command body: --from-file or positional command string
###############################################################################
app_cmd=""
app_args=()
job_body=""

if [[ -n "$from_file" ]]; then
  if [[ ! -f "$from_file" ]]; then
    echo "Error: --from-file not found: $from_file" >&2
    exit 1
  fi
  # Absolute path for the job body
  if [[ "$from_file" != /* ]]; then
    from_file="$PWD/$from_file"
  fi
  from_file="$(cd "$(dirname "$from_file")" && pwd)/$(basename "$from_file")"
  if [[ -z "$job_name" ]]; then
    base="$(basename "$from_file")"
    base="${base#run_}"
    job_name="$base"
  fi
  job_body="bash $(printf '%q' "$from_file")"
else
  if [[ $# -lt 1 ]]; then
    echo "Error: Missing <command> positional argument (or use --from-file)."
    show_help
    exit 1
  fi
  app_cmd_str="$1"
  read -r -a cmd_array <<< "$app_cmd_str"
  app_cmd="${cmd_array[0]}"
  app_args=("${cmd_array[@]:1}")

  base_cmd="$(basename "$app_cmd")"
  base_cmd="${base_cmd%.py}"
  base_cmd="${base_cmd%.sh}"
  base_cmd="${base_cmd%.bash}"
  if [[ -z "$job_name" ]]; then
    job_name="$base_cmd"
  fi
  job_body="$app_cmd ${app_args[*]}"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils/minsar_functions.bash"

if [[ -z "$wall_time" ]]; then
  if ! wall_time="$(get_slurm_job_parameter --jobname "$job_name" c_walltime)"; then
    echo "Warning: Could not retrieve c_walltime for job_name='$job_name'. Using default 1:00:00 for wall time."
    wall_time="1:00:00"
  fi
fi

job_file="${job_name}.job"

cat << EOF > "$job_file"
#!/bin/bash
#SBATCH -J $job_name
#SBATCH -A $JOBSHEDULER_PROJECTNAME
#SBATCH --mail-user=$NOTIFICATIONEMAIL
#SBATCH --mail-type=fail
#SBATCH -N 1
#SBATCH -n 48
#SBATCH -o $PWD/${job_name}%J.o
#SBATCH -e $PWD/${job_name}%J.e
#SBATCH -p $queue
#SBATCH -t $wall_time

# The actual command to run:
$job_body
EOF

chmod +x "$job_file"

echo "Created SLURM job file: $job_file"
