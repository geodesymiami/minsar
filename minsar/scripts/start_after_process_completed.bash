#!/usr/bin/env bash
# Wait until a login-node process exits, then run a command.

set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

print_help() {
    cat <<EOF
usage: ${SCRIPT_NAME} [-h] [--cwd DIR] [--interval SECS] [--list] [--dry-run] WAIT COMMAND [ARGS...]

Wait until WAIT (PID or unique pgrep -f pattern) exits, then run COMMAND. Resolve WAIT to a PID once. Same login node as WAIT.

options:
  -h, --help            show this help
  --cwd DIR             match only processes with this cwd
  --interval SECS       poll interval in seconds (default: 30)
  --list                print matching PID, etime, cwd, cmd and exit
  --dry-run             print resolved PID and COMMAND, then exit

Examples:
  ${SCRIPT_NAME} --list 'SanFranAirport|run_isce3_workflow.bash'
  ${SCRIPT_NAME} 34256 minsarIsce3App.bash 37.604:37.634,-122.402:-122.354 SanFranAirport --flight-dir asc --dolphin-mode opera --stride 1
  ${SCRIPT_NAME} --cwd \$SCRATCHDIR/SanFranAirportCSLCOperaSenD115 run_isce3_workflow.bash minsarIsce3App.bash 37.604:37.634,-122.402:-122.354 SanFranAirport --flight-dir asc --dolphin-mode opera --stride 1
  nohup ${SCRIPT_NAME} 34256 minsarIsce3App.bash 37.604:37.634,-122.402:-122.354 SanFranAirport --flight-dir asc --dolphin-mode opera --stride 1 > start_asc.log 2>&1 &
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

is_pid() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

process_cwd() {
    readlink "/proc/$1/cwd" 2>/dev/null || true
}

process_cmd() {
    local pid="$1"
    local cmd
    if ! cmd="$(cat "/proc/${pid}/cmdline" 2>/dev/null | tr '\0' ' ')"; then
        return 1
    fi
    [[ -n "$cmd" ]] || return 1
    printf '%s\n' "$cmd"
}

process_etime() {
    ps -p "$1" -o etime= 2>/dev/null | tr -d ' '
}

print_proc_line() {
    local pid="$1"
    local etime cwd cmd
    etime="$(process_etime "$pid")"
    cwd="$(process_cwd "$pid")"
    cmd="$(process_cmd "$pid" || true)"
    printf '%s  %s  %s  %s\n' "$pid" "${etime:-?}" "${cwd:-?}" "${cmd:-?}"
}

cwd_matches() {
    local pid="$1"
    local got
    got="$(process_cwd "$pid")"
    [[ -n "$got" ]] || return 1
    [[ "$got" == "$cwd_filter" ]]
}

should_keep() {
    local pid="$1"
    local cmd
    [[ "$pid" != "$$" ]] || return 1
    [[ -d "/proc/${pid}" ]] || return 1
    cmd="$(process_cmd "$pid" || true)"
    [[ -n "$cmd" ]] || return 1
    [[ "$cmd" != *"${SCRIPT_NAME}"* ]] || return 1
    if [[ -n "$cwd_filter" ]]; then
        cwd_matches "$pid" || return 1
    fi
    return 0
}

collect_matches() {
    local spec="$1"
    local pid
    matches=()
    if is_pid "$spec"; then
        if kill -0 "$spec" 2>/dev/null && should_keep "$spec"; then
            matches+=("$spec")
        fi
        return 0
    fi
    while IFS= read -r pid; do
        [[ -n "$pid" ]] || continue
        if should_keep "$pid"; then
            matches+=("$pid")
        fi
    done < <(pgrep -u "$USER" -f -- "$spec" 2>/dev/null || true)
}

cwd_filter=""
interval="30"
list_mode=false
dry_run=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --cwd)
            require_value "$1" "${2:-}"
            cwd_filter="$2"
            shift 2
            ;;
        --interval)
            require_value "$1" "${2:-}"
            interval="$2"
            shift 2
            ;;
        --list)
            list_mode=true
            shift
            ;;
        --dry-run)
            dry_run=true
            shift
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1" >&2
            echo "Use $SCRIPT_NAME --help for available options" >&2
            exit 1
            ;;
        *)
            break
            ;;
    esac
done

[[ "$interval" =~ ^[1-9][0-9]*$ ]] || die "--interval must be a positive integer"
if [[ -n "$cwd_filter" && -d "$cwd_filter" ]]; then
    cwd_filter="$(cd "$cwd_filter" && pwd -P)"
fi

[[ $# -ge 1 ]] || die "WAIT is required"
wait_spec="$1"
shift
cmd=("$@")

if [[ "$list_mode" != true && ${#cmd[@]} -eq 0 ]]; then
    die "COMMAND is required"
fi

matches=()
collect_matches "$wait_spec"

if [[ "$list_mode" == true ]]; then
    if [[ ${#matches[@]} -eq 0 ]]; then
        if is_pid "$wait_spec"; then
            die "process $wait_spec is not running"
        fi
        die "no process matched: $wait_spec"
    fi
    for pid in "${matches[@]}"; do
        print_proc_line "$pid"
    done
    exit 0
fi

if [[ ${#matches[@]} -eq 0 ]]; then
    if is_pid "$wait_spec"; then
        if ! kill -0 "$wait_spec" 2>/dev/null; then
            die "process $wait_spec is not running"
        fi
        if [[ -n "$cwd_filter" ]]; then
            die "process $wait_spec does not match --cwd $cwd_filter"
        fi
        die "process $wait_spec is not a valid wait target"
    fi
    die "no process matched: $wait_spec"
fi

if [[ ${#matches[@]} -gt 1 ]]; then
    echo "Error: WAIT matched ${#matches[@]} processes; use a PID, a tighter pattern, or --cwd" >&2
    for pid in "${matches[@]}"; do
        print_proc_line "$pid"
    done
    exit 1
fi

wait_pid="${matches[0]}"

if [[ "$dry_run" == true ]]; then
    echo "PID ${wait_pid}"
    print_proc_line "$wait_pid"
    echo "COMMAND: ${cmd[*]}"
    exit 0
fi

echo "$(date +"%Y%m%d:%H-%M") * waiting for PID ${wait_pid} (interval ${interval}s)"
while kill -0 "$wait_pid" 2>/dev/null; do
    sleep "$interval"
done
echo "$(date +"%Y%m%d:%H-%M") * process ${wait_pid} completed; running: ${cmd[*]}"
"${cmd[@]}"
