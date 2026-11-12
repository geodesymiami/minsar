#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    helptext="
usage: run_minsar.bash STEM [flags] [STEM [flags] ...] [-- flags]

Run one or more datasets from the custom options file. Templates are written only under \$ATE (AUTO_TEMPLATES). \$TE is not read or written.

Each STEM is a name such as GalapagosSenA106 or TamboraSenD134. SenA and SenAT are ascending. SenD and SenDT are descending. The text before that label is the project name. Flags after a name apply only to that dataset. Flags after -- apply to every dataset.

A log line for this command and for each minsarApp.bash command is appended to \$ATE/log.

options:
  -h, --help       show this help

Examples:
  run_minsar.bash GalapagosSenA106
  run_minsar.bash GalapagosSenA106 --start-date 20260101
  run_minsar.bash GalapagosSenA106 --start-date 20260101 CerroAzulSenA106 --no-mintpy --miaplpy
  run_minsar.bash GalapagosSenD128 GalapagosSenA106 -- --queue pvc
"
    echo "$helptext"
    exit 0
fi

if [[ $# -lt 1 ]]; then
    echo "Error: give at least one dataset name. Use $SCRIPT_NAME --help." >&2
    exit 1
fi

if [[ -z "${ATE:-}" ]]; then
    if [[ -n "${AUTO_TEMPLATES:-}" ]]; then
        ATE="$AUTO_TEMPLATES"
    elif [[ -n "${TEMPLATES:-}" ]]; then
        ATE="$(cd "$(dirname "$TEMPLATES")" && pwd)/AUTO_TEMPLATES"
    else
        echo "Error: set ATE, or TEMPLATES so AUTO_TEMPLATES can be placed next to it." >&2
        exit 1
    fi
fi
mkdir -p "$ATE"
ATE="$(cd "$ATE" && pwd)"
export ATE
export AUTO_TEMPLATES="$ATE"
if [[ -n "${TE:-}" ]]; then
    te_real="$(cd "$TE" && pwd)"
    if [[ "$ATE" == "$te_real" ]]; then
        echo "Error: ATE and TE are the same directory ($ATE)." >&2
        exit 1
    fi
fi

LOG="$ATE/log"
timestamp="$(date +"%Y%m%d:%H-%M")"
{
    echo "#############################################################################################"
    echo "$timestamp * $SCRIPT_NAME $*"
} | tee -a "$LOG"

planner="${SCRIPT_DIR}/../utils/custom_template_options.py"
plan_out="$(python3 "$planner" plan --template-dir "$ATE" "$@")"
mapfile -t commands <<< "$plan_out"
if [[ ${#commands[@]} -eq 0 ]]; then
    echo "Error: no minsarApp commands were planned." >&2
    exit 1
fi
for cmd in "${commands[@]}"; do
    timestamp="$(date +"%Y%m%d:%H-%M")"
    echo "$timestamp * $cmd" | tee -a "$LOG"
    eval "$cmd"
done
