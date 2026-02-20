#!/usr/bin/env bash
# Create a SLURM .job file from a script file or command. Same behavior as cmd2jobfile.py.
# Usage: cmd2jobfile.bash FILE_OR_CMD [ ... ] [ --queue QUEUE ] [ --walltime HH:MM ] [ --submit ] [ --background ]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CMD2JOBFILE_PY="${SCRIPT_DIR}/cmd2jobfile.py"

usage() {
    echo "Usage: cmd2jobfile.bash FILE_OR_CMD [ ... ] [ --queue QUEUE ] [ --walltime HH:MM ] [ --submit ] [ --background ]"
    echo "  One argument that is a file -> job name from basename; file contents go in job body."
    echo "  Multiple args -> command line; first token used as job name."
    echo "  --submit: submit via run_workflow.bash (foreground)."
    echo "  --background: submit via sbatch (background). Implies submit."
    exit 0
}

if [[ $# -eq 0 ]] || [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    usage
fi

# Collect positionals and options for Python (without --submit/--background for creation)
py_args=()
submit_flag=0
background_flag=0
queue=""
walltime=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --submit|-s)
            submit_flag=1
            shift
            ;;
        --background|-b)
            background_flag=1
            shift
            ;;
        --queue|-q)
            queue="$2"
            py_args+=("--queue" "$queue")
            shift 2
            ;;
        --walltime|-t)
            walltime="$2"
            py_args+=("--walltime" "$walltime")
            shift 2
            ;;
        *)
            py_args+=("$1")
            shift
            ;;
    esac
done

# Create jobfile (Python does not submit)
"$CMD2JOBFILE_PY" "${py_args[@]}"

# Derive job path: if one positional and it was a file, jobname = basename without extension; else first token
if [[ ${#py_args[@]} -eq 1 ]] && [[ -f "${py_args[0]}" ]]; then
    jobname="$(basename "${py_args[0]}")"
    jobname="${jobname%.*}"
    jobpath="$PWD/${jobname}.job"
else
    jobname="${py_args[0]:-cmd2job}"
    jobpath="$PWD/${jobname}.job"
fi

if [[ $submit_flag -eq 1 ]] || [[ $background_flag -eq 1 ]]; then
    if [[ $background_flag -eq 1 ]]; then
        sbatch "$jobpath"
    else
        echo "Running..... run_workflow.bash --jobfile $(basename "$jobpath")"
        run_workflow.bash --jobfile "$jobpath"
    fi
fi
