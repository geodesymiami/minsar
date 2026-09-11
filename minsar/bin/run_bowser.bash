#!/usr/bin/env bash
set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat << EOF
usage: $SCRIPT_NAME [-h] [STACK.nc] [bowser-run-args...]

Run bowser on a GeoZarr/NetCDF stack without cd'ing into tools/bowser.

Options:
  -h, --help    Show this help

If STACK.nc is omitted, uses the single *stack.nc in the current directory.

Examples:
  $SCRIPT_NAME
  $SCRIPT_NAME MiamiMiaCSLCOperaSenA48-stack.nc
  $SCRIPT_NAME /path/to/project-stack.nc --port 8001
EOF
    exit 0
fi

: "${MINSAR_HOME:?ERROR: MINSAR_HOME is required (source setup/environment.bash)}"

BOWSER_DIR="${MINSAR_HOME}/tools/bowser"
MANIFEST="${BOWSER_DIR}/pyproject.toml"
DIST_DIR="${BOWSER_DIR}/src/bowser/dist"

if [[ ! -f "$MANIFEST" ]]; then
    echo "Error: bowser not found at $BOWSER_DIR" >&2
    exit 1
fi
if [[ ! -d "$DIST_DIR" ]]; then
    echo "Error: missing frontend $DIST_DIR (build with npm, or copy dist from the bowser-insar wheel)" >&2
    exit 1
fi
if ! command -v pixi >/dev/null 2>&1; then
    echo "Error: pixi not found on PATH" >&2
    exit 1
fi

stack_file=""
extra_args=()
if [[ $# -gt 0 && "$1" != -* ]]; then
    stack_file="$1"
    shift
    extra_args=("$@")
else
    extra_args=("$@")
    shopt -s nullglob
    matches=(*stack.nc)
    shopt -u nullglob
    if [[ ${#matches[@]} -eq 0 ]]; then
        echo "Error: no *stack.nc in $PWD; pass STACK.nc explicitly" >&2
        exit 1
    fi
    if [[ ${#matches[@]} -gt 1 ]]; then
        echo "Error: multiple *stack.nc files; pass one explicitly:" >&2
        printf '  %s\n' "${matches[@]}" >&2
        exit 1
    fi
    stack_file="${matches[0]}"
fi

if [[ ! -f "$stack_file" ]]; then
    echo "Error: stack file not found: $stack_file" >&2
    exit 1
fi

# Absolute path so it still works if pixi ever changes cwd
stack_abs="$(cd "$(dirname "$stack_file")" && pwd)/$(basename "$stack_file")"

echo "bowser stack: $stack_abs"
exec pixi run --manifest-path "$MANIFEST" bowser run --stack-file "$stack_abs" "${extra_args[@]}"
